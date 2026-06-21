"""Compose dossier reports with the LLM and render PDF via the preprint LaTeX template."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard

from opentorus.actions import list_actions
from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store
from opentorus.research.dossier.experiments import experiment_dir, list_experiments
from opentorus.research.memory import VALID_KINDS, list_memory
from opentorus.research.papers import is_paper_parsed, list_papers

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportComposeHooks:
    """Optional progress and LLM streaming callbacks for report composition."""

    on_progress: Callable[[str], None] | None = None
    on_llm_text: Callable[[str], None] | None = None
    on_llm_thinking: Callable[[str], None] | None = None
    on_llm_request: Callable[[list[Any], list[dict] | None], None] | None = None
    on_llm_response: Callable[[Any], None] | None = None
    stream_llm: bool | None = None


_STDOUT_TAIL = 6000
_LLM_MAX_CHARS = 48_000
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PREPRINT_CLS = _TEMPLATE_DIR / "preprint.cls"

_COMPOSE_RULES = """\
Write a polished **research investigation report** as a LaTeX body fragment (no preamble,
no \\documentclass, no \\begin{document}).

Use the preprint article style: \\section, \\subsection, \\paragraph as needed.
Use LaTeX math ($...$ or \\(...\\)) for formulas; cite artifact ids inline (EXP-*, CLAIM-*, etc.).

Required sections (in this order):
1. \\section{Summary} — 2–4 sentences: problem, method, main finding, what remains open.
2. \\section{Problem statement} — restate clearly with proper math notation.
3. \\section{Investigation} — narrative of steps taken, tools run, artifact ids.
4. \\section{Literature} — only PAPER-* entries from JSON; if none, say so.
5. \\section{Results} — for each experiment: \\subsection{EXP-...} with full stdout in
   \\begin{verbatim}...\\end{verbatim}, then interpret (e.g. submodularity violation).
6. \\section{Claims and evidence} — use a \\begin{tabular}{llp{0.45\\linewidth}l} table.
7. \\section{Proof sketches (not machine-checked)} — for each entry in ``proofs`` in JSON:
   include \\subsection{PROOF-...}, list gaps, and the full ``body`` in verbatim.
   Say explicitly that sketch status is NOT a verified proof.
8. \\section{Conclusions and open questions} — honest epistemic status.
9. \\section*{References} with \\addcontentsline{toc}{section}{References} and itemize
   of every artifact id cited.

Rules:
- Use ONLY facts from the JSON payload — never invent papers, experiments, or results.
- Counterexample candidates are NOT verified theorems — say so explicitly.
- In display math use \\[ ... \\] or align; never nest $...$ inside \\text{...}.
  For prose inside a set definition write: p \\in \\mathbb{R}[x] \\mid \\text{can be evaluated...}
  without dollar signs inside \\text.
- Escape LaTeX special characters in plain text (& % # _ { } ~ ^ \\).
- For file paths use \\path{experiments/script.py} (not \\texttt with raw underscores).
- Cite artifact ids inline as \\texttt{EXP-0001}; do not use \\cite (no .bib file).
- Professional prose suitable for a workshop preprint or short research note.
"""

_PROOF_MD_TO_LATEX_RULES = """\
Convert a natural-language proof sketch from Markdown into LaTeX body fragments
(no preamble, no \\documentclass, no \\begin{document}).

Use \\subsubsection{...} for ## headings, \\paragraph{...} for ### headings,
itemize/enumerate for lists, and $...$ / \\[...\\] for mathematics.
Preserve [GAP-n] markers verbatim. Cite PAPER-*, EXP-*, CLAIM-* as \\texttt{ID}.
Status is sketch — do NOT write QED or claim machine verification.
Escape LaTeX specials in plain text. Output ONLY the LaTeX fragment.
"""


def _llm_usable(provider: BaseProvider | None) -> TypeGuard[BaseProvider]:
    return provider is not None and getattr(provider, "name", "mock") != "mock"


def _read_experiment_stdout(ot_dir: Path, problem_id: str, exp_id: str) -> str:
    base = experiment_dir(ot_dir, problem_id, exp_id)
    for name in ("stdout.log", "results/stdout.txt", "stdout.txt"):
        path = base / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > _STDOUT_TAIL:
                return text[-_STDOUT_TAIL:]
            return text
    return ""


def _gather_investigation_steps(ot_dir: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for action in list_actions(ot_dir, limit=limit):
        args = {k: (str(v)[:240] if v is not None else "") for k, v in action.args.items()}
        steps.append(
            {
                "id": action.id,
                "tool": action.tool_name,
                "args": args,
                "ok": action.ok,
                "summary": (action.stdout_summary or "")[:800],
            }
        )
    return steps


def _gather_literature(ot_dir: Path, problem_id: str) -> list[dict[str, Any]]:
    pid = problem_id.strip().upper()
    papers = [
        {
            "id": p.id,
            "title": p.title or "",
            "parsed": is_paper_parsed(ot_dir, p),
            "doi": p.doi or "",
        }
        for p in list_papers(ot_dir)
    ]
    related = [
        {
            "id": r.id,
            "title": r.title or "",
            "paper_artifact": r.paper_artifact or "",
        }
        for r in store.list_related_papers(ot_dir, pid)
    ]
    return papers + related


def _gather_memory_notes(ot_dir: Path, *, per_kind: int = 8) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    for kind in VALID_KINDS:
        for entry in list_memory(ot_dir, kind)[-per_kind:]:
            notes.append(
                {
                    "kind": kind,
                    "id": entry.id,
                    "text": entry.text[:600],
                }
            )
    return notes


def gather_dossier_facts(ot_dir: Path, problem_id: str) -> dict[str, Any]:
    """Structured artifact snapshot for LLM composition or deterministic LaTeX."""
    pid = problem_id.strip().upper()
    dossier = store.require_dossier(ot_dir, pid)
    statement = store.read_statement(ot_dir, pid).strip()
    if statement.startswith("#"):
        statement = "\n".join(
            line for line in statement.splitlines() if not line.startswith("#")
        ).strip()

    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for ev in store.list_evidence(ot_dir, pid):
        evidence_by_claim.setdefault(ev.claim_id, []).append(
            {
                "id": ev.id,
                "type": ev.type,
                "direction": ev.direction,
                "summary": ev.summary,
                "limitations": ev.limitations,
            }
        )

    claims = [
        {
            "id": c.id,
            "type": c.type,
            "status": c.status,
            "statement": c.statement,
            "evidence": evidence_by_claim.get(c.id, []),
        }
        for c in store.list_claims(ot_dir, pid)
    ]

    experiments = []
    for exp in list_experiments(ot_dir, pid):
        experiments.append(
            {
                "id": exp.experiment_id,
                "title": exp.title,
                "status": exp.status,
                "command": exp.command,
                "random_seed": exp.random_seed,
                "result_summary": exp.result_summary or "",
                "stdout_tail": _read_experiment_stdout(ot_dir, pid, exp.experiment_id),
            }
        )

    proofs = []
    dossier_dir = store.dossier_dir(ot_dir, pid)
    for proof in store.list_proof_attempts(ot_dir, pid):
        body = ""
        if proof.body_path:
            body_file = dossier_dir / proof.body_path
            if body_file.is_file():
                body = body_file.read_text(encoding="utf-8", errors="replace")
                if len(body) > 8000:
                    body = body[:8000] + "\n…"
        proofs.append(
            {
                "id": proof.id,
                "title": proof.title,
                "status": proof.status,
                "gaps": proof.gaps,
                "body": body,
            }
        )

    return {
        "problem_id": pid,
        "title": dossier.title,
        "status": dossier.status,
        "domain": dossier.domain or "",
        "formalization": dossier.formalization_status,
        "tags": dossier.tags,
        "statement": statement,
        "definitions": [
            {"id": d.id, "term": d.term, "definition": d.definition}
            for d in store.list_definitions(ot_dir, pid)
        ],
        "assumptions": [
            {"id": a.id, "statement": a.statement, "rationale": a.rationale or ""}
            for a in store.list_assumptions(ot_dir, pid)
        ],
        "known_results": [
            {"id": k.id, "statement": k.statement, "sources": k.source_artifacts}
            for k in store.list_known_results(ot_dir, pid)
        ],
        "claims": claims,
        "experiments": experiments,
        "proofs": proofs,
        "failed_attempts": [
            {"id": f.id, "summary": f.summary, "reason_failed": f.reason_failed}
            for f in store.list_failed_attempts(ot_dir, pid)
        ],
        "approaches": [
            {
                "id": a.id,
                "strategy": a.strategy,
                "objective": a.objective,
                "method": a.method,
            }
            for a in store.list_approaches(ot_dir, pid)
        ],
        "literature": _gather_literature(ot_dir, pid),
        "investigation_steps": _gather_investigation_steps(ot_dir),
        "memory_notes": _gather_memory_notes(ot_dir),
    }


def _latex_escape(text: str) -> str:
    """Escape plain text for LaTeX (not math mode)."""
    text = _normalize_unicode(text)
    replacements = (
        ("\\", r"\textbackslash{}"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("$", r"\$"),
        ("&", r"\&"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("%", r"\%"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    )
    out = text
    for old, new in replacements:
        out = out.replace(old, new)
    return out


_UNICODE_SPACES = str.maketrans(
    {
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u200a": " ",
        "\u200b": "",
        # Hyphen/dash block + minus sign \u2192 ASCII so pdfLaTeX renders them and the
        # ASCII gap-marker handling (e.g. "[GAP-1]") matches model-emitted variants.
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "--",
        "\u2015": "-",
        "\u2212": "-",
    }
)


def _normalize_unicode(text: str) -> str:
    """Replace Unicode spaces and invisible chars that break pdfLaTeX/XeLaTeX fonts."""
    return text.translate(_UNICODE_SPACES)


def _escape_unescaped_specials(text: str) -> str:
    """Escape LaTeX specials in inline text, skipping existing backslash sequences
    and inline math spans.

    A balanced ``$...$`` span is copied verbatim so its delimiters and in-math
    characters (``_``, ``^``, ``\\neq`` …) survive — otherwise math embedded in
    ``\\textbf{...}`` (e.g. ``\\textbf{Case ($A \\neq 0$)}``) would be corrupted
    into ``\\$A \\neq 0\\$`` and fail to compile. A lone ``$`` is escaped.
    """
    special = {"#": r"\#", "%": r"\%", "&": r"\&", "_": r"\_"}
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "$":
            close = text.find("$", i + 1)
            if close != -1:
                out.append(text[i : close + 1])  # preserve $...$ math verbatim
                i = close + 1
            else:
                out.append(r"\$")  # unbalanced → literal dollar
                i += 1
            continue
        out.append(special.get(ch, ch))
        i += 1
    return "".join(out)


_TEXT_CMD_RE = re.compile(r"\\(textbf|textit|emph)\{([^{}]*)\}")
_PATH_LIKE = re.compile(r"[/\\]|\.(?:py|sh|tex|md|json|yaml|yml)$")
_CITE_ARTIFACT_RE = re.compile(r"\\cite\{([A-Z]+-\d+)\}")
# \path{key\_name}=text / \bigl(...\bigr) outside math mode (common LLM mistake)
_PATH_MATH_RE = re.compile(
    r"\\path\{([^}]+)\}\s*=\s*([^\\][^\n]*?)\s*(\\bigl\(.*?\\bigr\))",
    re.DOTALL,
)
# \text{$p$ ... , \textit{...} immediately before \Bigr\} (LLM forgets to close \text)
_TEXT_ITEXT_BBIGL_RE = re.compile(
    r"\\text\{(\$[^$]+\$.*?),\s*\\textit\{([^}]+)\}(?=\\Bigr\\})",
    re.DOTALL,
)
_GAP_MARKER_RE = re.compile(r"(?<![\\{}\w])(\[GAP-\d+\])")
_OLD_FONT_CMD_RE = re.compile(r"\{\\(tt|bf|it|rm|sl|sc|sf|mit)\s*([^}]*)\}")
_PANDOC_INLINE_RE = re.compile(r"\\\((.*?)\\\)")
# Segments that must not receive Unicode/markdown repair (math, verbatim, display).
_LATEX_PRESERVE_RE = re.compile(
    r"\$[^$\n]+\$|"
    r"\\\[[\s\S]*?\\\]|"
    r"\\begin\{verbatim\}[\s\S]*?\\end\{verbatim\}|"
    r"\\begin\{lstlisting\}[\s\S]*?\\end\{lstlisting\}"
)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _fix_old_font_commands(body: str) -> str:
    """Replace LaTeX 2.09 ``{\\tt ...}``, ``{\\bf ...}``, etc. (KOMA/pdfLaTeX)."""
    mapping = {
        "tt": "texttt",
        "bf": "textbf",
        "it": "textit",
        "sl": "textsl",
        "sc": "textsc",
        "sf": "textsf",
        "rm": "textrm",
        "mit": "textit",
    }

    def repl(match: re.Match[str]) -> str:
        cmd, inner = match.group(1), match.group(2)
        latex_cmd = mapping.get(cmd, "text")
        return f"\\{latex_cmd}{{{inner}}}"

    return _OLD_FONT_CMD_RE.sub(repl, body)


def _fix_gap_markers(body: str) -> str:
    """Wrap bare [GAP-n] markers so LaTeX does not treat ``[`` as an optional argument."""
    return _GAP_MARKER_RE.sub(r"\\texttt{\1}", body)


def _fix_pandoc_inline_math(body: str) -> str:
    """Convert Pandoc-style ``\\(...\\)`` to ``$...$`` for the preprint template."""
    return _PANDOC_INLINE_RE.sub(lambda m: f"${m.group(1).strip()}$", body)


def _map_plain_latex_segments(body: str, mapper: Callable[[str], str]) -> str:
    """Apply *mapper* only outside preserved math/verbatim blocks."""
    parts = _LATEX_PRESERVE_RE.split(body)
    preserved = _LATEX_PRESERVE_RE.findall(body)
    out: list[str] = []
    for idx, part in enumerate(parts):
        out.append(mapper(part))
        if idx < len(preserved):
            out.append(preserved[idx])
    return "".join(out)


def _fix_markdown_bold(body: str) -> str:
    """Convert leftover ``**bold**`` markdown from LLM output to ``\\textbf{}``."""
    return _MD_BOLD_RE.sub(r"\\textbf{\1}", body)


def _fix_bare_unicode_math(body: str) -> str:
    """Wrap bare Unicode math symbols (e.g. κ) in ``$...$`` for pdfLaTeX."""
    from opentorus.research.markdown_latex import prepare_markdown_for_pdf

    return prepare_markdown_for_pdf(body)


def _fix_llm_markdown_leaks(body: str) -> str:
    """Repair common LLM markdown/Unicode leaks in LaTeX body text."""

    def fix_segment(segment: str) -> str:
        segment = _fix_markdown_bold(segment)
        return _fix_bare_unicode_math(segment)

    return _map_plain_latex_segments(body, fix_segment)


def _extract_braced(s: str, open_brace: int) -> tuple[str, int]:
    """Return (inner, index of closing brace) for ``s[open_brace] == '{'``."""
    if open_brace >= len(s) or s[open_brace] != "{":
        return "", open_brace
    depth = 0
    j = open_brace
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[open_brace + 1 : j], j
        j += 1
    return s[open_brace + 1 :], len(s) - 1


def _dollars_to_ensuremath(text: str) -> str:
    return re.sub(r"\$([^$]+)\$", lambda m: f"\\ensuremath{{{m.group(1)}}}", text)


def _fix_amsmath_text(body: str) -> str:
    """Fix \\text{...} blocks that illegally contain $...$ or nested font commands."""
    body = _TEXT_ITEXT_BBIGL_RE.sub(
        lambda m: f"\\text{{{_dollars_to_ensuremath(m.group(1))}, \\emph{{{m.group(2)}}}}}",
        body,
    )

    out: list[str] = []
    i = 0
    while i < len(body):
        if body.startswith("\\text{", i):
            inner, close = _extract_braced(body, i + 5)
            if "$" in inner or "\\textit{" in inner:
                inner = _dollars_to_ensuremath(inner)
                inner = re.sub(r"\\textit\{([^{}]*)\}", r"\\emph{\1}", inner)
                # Drop stray \\Bigr inside \\text (LLM nesting mistake)
                inner = re.sub(r"\\Bigr\\?", "", inner)
                out.append("\\text{" + inner + "}")
                i = close + 1
                continue
        out.append(body[i])
        i += 1
    return "".join(out)


def _fix_path_math_mix(body: str) -> str:
    """Rewrite ``\\path{key}=... \\bigl(...\\bigr)`` outside math mode."""
    if re.search(r"\\\([^)]*\\texttt\{[^}]*bound", body):
        return body

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        bigl = match.group(3)
        inner = bigl.replace("\\bigl(", "").replace("\\bigr)", "").strip()
        return f"the ratio \\texttt{{{key}}} (\\emph{{error}} divided by ${inner}$)"

    return _PATH_MATH_RE.sub(repl, body)


_CORRUPTED_NORM = re.compile(r"12505\\?\|")
_DOUBLE_DOLLAR_RE = re.compile(r"\$\$([^$]+)\$\$", re.DOTALL)


def _fix_corrupted_latex(body: str) -> str:
    """Repair common PDF/OCR corruptions and display-math delimiters in LaTeX fragments."""
    body = _normalize_unicode(body)
    # Collapse display delimiters to inline as balanced pairs ($$…$$ -> $…$). Do NOT
    # blindly replace every "$$" with "$": that strips one delimiter from any display
    # block the paired regex did not catch, leaving odd '$' parity that aborts pdflatex.
    body = _DOUBLE_DOLLAR_RE.sub(lambda m: f"${m.group(1).strip()}$", body)
    body = _CORRUPTED_NORM.sub(r"\\|", body)
    body = body.replace(r"\$$", "$")
    return body


def _strip_latex_to_plain(text: str) -> str:
    """Aggressively remove LaTeX markup for short plain-text fields (titles, snippets)."""
    text = _normalize_unicode(text)
    text = re.sub(r"\\[\(\[](.*?)\\[\)\]]", r" \1 ", text)
    text = re.sub(r"\$\$[\s\S]+?\$\$", " ", text)
    text = re.sub(r"\$([^$]+)\$", r" \1 ", text)
    text = re.sub(r"\\begin\{[^{}]+\}[\s\S]*?\\end\{[^{}]+\}", " ", text)
    for _ in range(8):
        text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})*", " ", text)
    text = re.sub(r"[{}^_\\$]", " ", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]", "", text)
    return " ".join(text.split())


def _plain_text_snippet(text: str, *, limit: int = 400) -> str:
    """Strip Markdown/LaTeX for short plain-text fields."""
    text = _strip_latex_to_plain(text)
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _brace_depth(text: str) -> int:
    """Count unmatched ``{`` after the last balanced segment."""
    depth = 0
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth = max(0, depth - 1)
        i += 1
    return depth


def _truncate_latex_safe(text: str, limit: int) -> str:
    """Truncate without leaving unbalanced ``$`` or ``{``."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    if cut.endswith("\\"):
        cut = cut[:-1].rstrip()
    # Prefer breaking at a word boundary when still within budget.
    if " " in cut:
        word_cut = cut.rsplit(" ", 1)[0].rstrip()
        if len(word_cut) >= max(40, limit // 2):
            cut = word_cut
    dollar_count = 0
    i = 0
    while i < len(cut):
        if cut[i] == "$" and (i == 0 or cut[i - 1] != "\\"):
            dollar_count += 1
        i += 1
    if dollar_count % 2 == 1:
        cut += "$"
    cut += "}" * _brace_depth(cut)
    return cut + "…"


def _latex_escape_preserving_math(text: str, *, limit: int | None = None) -> str:
    """Escape LaTeX specials in text but leave $...$ math segments intact."""
    text = _normalize_unicode(text)
    parts = re.split(r"(\$[^$]+\$)", text)
    out: list[str] = []
    for part in parts:
        if part.startswith("$") and part.endswith("$") and len(part) > 2:
            out.append(part)
        else:
            out.append(_latex_escape(part))
    result = "".join(out)
    if limit is not None and len(result) > limit:
        return _truncate_latex_safe(result, limit)
    return result


def _looks_like_math_in_text_cmd(inner: str) -> bool:
    """True when LLM put math ($, subscripts, carets) inside \\texttt/\\path."""
    if "$" in inner:
        return True
    if re.search(r"\\[_^]", inner):
        return True
    if "^" in inner:
        return True
    return False


def _unwrap_text_cmd_to_math(inner: str) -> str:
    """Turn ``\\texttt{$\\Pi$\\_{2^m}^*}``-style fragments into ``$...$``."""
    text = inner.strip()
    while "$" in text:
        updated = re.sub(r"\$([^$]+)\$", r"\1", text, count=1)
        if updated == text:
            break
        text = updated
    text = text.replace(r"\_", "_").replace(r"\^", "^").replace(r"\^{}", "")
    return f"${text}$"


def _fix_texttt_and_path_commands(body: str) -> str:
    """Repair \\texttt/\\path with nested braces or illegal inline math."""
    pat = re.compile(r"\\(texttt|path)\{")
    out: list[str] = []
    last = 0
    for match in pat.finditer(body):
        out.append(body[last : match.start()])
        open_brace = match.end() - 1
        inner, close = _extract_braced(body, open_brace)
        cmd = match.group(1)
        if _looks_like_math_in_text_cmd(inner):
            out.append(_unwrap_text_cmd_to_math(inner))
        elif cmd == "texttt" and _PATH_LIKE.search(inner):
            out.append(f"\\path{{{inner}}}")
        else:
            out.append(f"\\{cmd}{{{_escape_unescaped_specials(inner)}}}")
        last = close + 1
    out.append(body[last:])
    return "".join(out)


def _fix_text_cmd(match: re.Match[str]) -> str:
    cmd, inner = match.group(1), match.group(2)
    return f"\\{cmd}{{{_escape_unescaped_specials(inner)}}}"


_TAG_RE = re.compile(r"\\tag\*?\{([^{}]*)\}")


def _latex_safe_unicode(text: str) -> str:
    """Final guard: no bare non-ASCII reaches pdflatex (which aborts on undeclared
    Unicode, even inside math mode).

    Tracks ``$`` / ``$$`` math context: a symbol in the Unicode→LaTeX map becomes its
    bare command inside math (``\\beta``) or ``$\\beta$`` outside; anything unmapped is
    transliterated to ASCII (NFKD) and otherwise dropped. Backslash escapes are skipped.
    """
    import unicodedata

    from opentorus.research.markdown_latex import _UNICODE_MATH_ALL

    out: list[str] = []
    in_math = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "$":
            if i + 1 < n and text[i + 1] == "$":
                out.append("$$")
                in_math = not in_math
                i += 2
                continue
            out.append("$")
            in_math = not in_math
            i += 1
            continue
        if ord(ch) < 128:
            out.append(ch)
            i += 1
            continue
        cmd = _UNICODE_MATH_ALL.get(ch)
        if cmd:
            if in_math:
                out.append(cmd)
                # separate a control word from a following letter (\surd m, not \surdm)
                if cmd[-1:].isalpha() and i + 1 < n and text[i + 1].isalpha():
                    out.append(" ")
            else:
                out.append(f"${cmd}$")
        else:
            out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode())
        i += 1
    return "".join(out)


def sanitize_latex_body(body: str) -> str:
    """Repair common LLM LaTeX mistakes so preprint compiles under -halt-on-error."""
    body = _fix_corrupted_latex(body)
    body = _normalize_unicode(body)
    body = _fix_pandoc_inline_math(body)
    body = _fix_llm_markdown_leaks(body)
    body = _fix_gap_markers(body)
    body = _fix_old_font_commands(body)
    body = _fix_amsmath_text(body)
    body = _fix_path_math_mix(body)
    body = _fix_texttt_and_path_commands(body)
    body = _TEXT_CMD_RE.sub(_fix_text_cmd, body)
    body = _CITE_ARTIFACT_RE.sub(r"\\texttt{\1}", body)
    # \tag is only valid inside an equation; models emit it in prose (e.g.
    # "\tag{GAP-2}"), which aborts amsmath — render it as a parenthetical instead.
    body = _TAG_RE.sub(r"(\1)", body)
    # Last line of defense: never let a bare non-ASCII char reach pdflatex.
    body = _latex_safe_unicode(body)
    return body


def _latex_verbatim(text: str) -> str:
    """Wrap text in a verbatim environment (handles most stdout safely)."""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\\end{verbatim}" in body or "\\end{lstlisting}" in body:
        body = body.replace("\\end{verbatim}", "").replace("\\end{lstlisting}", "")
    return f"\\begin{{verbatim}}\n{body}\n\\end{{verbatim}}"


def _short_title(facts: dict[str, Any]) -> str:
    title = (facts.get("title") or facts["problem_id"]).strip()
    if len(title) > 60:
        return title[:57].rstrip() + "..."
    return title


def _clean_proof_markdown(body: str) -> str:
    body = _normalize_unicode(body)
    return body.replace("\ufffd", "?")


def _proof_markdown_to_latex_fallback(body: str) -> str:
    """Deterministic Markdown → LaTeX for a single proof sketch (no model).

    Used only as a per-proof fallback when the model conversion of *that* proof
    fails; the whole-document deterministic PDF path was removed (it could not
    render Unicode-in-prose mathematics legibly — see :func:`compose_and_render_pdf`).
    """
    from opentorus.research.markdown_latex import prepare_markdown_for_pdf

    body = _clean_proof_markdown(body)
    body = prepare_markdown_for_pdf(body)
    bold_re = re.compile(r"\*\*(.+?)\*\*")
    italic_re = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    out: list[str] = []
    in_itemize = False

    def close_list() -> None:
        nonlocal in_itemize
        if in_itemize:
            out.append("\\end{itemize}")
            in_itemize = False

    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            close_list()
            out.append("")
            continue
        if stripped.startswith("# ") and "PROOF-" in stripped.upper():
            continue
        if stripped.lower().startswith("_status:") or stripped.lower().startswith("*status:"):
            status = stripped.strip("_* ")
            out.append(f"\\textit{{{_latex_escape(status)}}}")
            continue
        if stripped.startswith("## "):
            close_list()
            out.append(f"\\subsubsection{{{_latex_escape(stripped[3:].strip())}}}")
            continue
        if stripped.startswith("### "):
            close_list()
            out.append(f"\\paragraph{{{_latex_escape(stripped[4:].strip())}}}.")
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_itemize:
                out.append("\\begin{itemize}")
                in_itemize = True
            content = stripped[2:].strip()
            item = bold_re.sub(r"\\textbf{\1}", content)
            item = italic_re.sub(r"\\emph{\1}", item)
            out.append(f"\\item {_latex_escape_preserving_math(item)}")
            continue
        close_list()
        text = bold_re.sub(r"\\textbf{\1}", stripped)
        text = italic_re.sub(r"\\emph{\1}", text)
        if "$" in text or "\\[" in text:
            out.append(text)
        else:
            out.append(_latex_escape(text))
    close_list()
    return sanitize_latex_body("\n".join(out))


def llm_convert_proof_to_latex(
    proof: dict[str, Any],
    provider: BaseProvider,
    *,
    hooks: ReportComposeHooks | None = None,
) -> str:
    """Use the configured model to turn a Markdown proof sketch into LaTeX."""
    from opentorus.agent.session import SessionMessage
    from opentorus.providers.base import provider_label

    body = _clean_proof_markdown(proof.get("body") or "")
    if not body.strip():
        return ""
    pid = proof.get("id") or "PROOF-0001"
    prompt = (
        f"{_PROOF_MD_TO_LATEX_RULES}\n\n"
        f"Proof artifact: {pid}\n"
        f"Title: {proof.get('title') or 'sketch'}\n"
        f"Status: {proof.get('status') or 'sketch'}\n\n"
        f"Markdown source:\n\n{body[:14_000]}"
    )
    if hooks and hooks.on_progress:
        hooks.on_progress(
            f"Converting {pid} proof sketch to LaTeX with {provider_label(provider)}…"
        )

    messages = [SessionMessage(role="user", content=prompt)]
    if hooks and hooks.on_llm_request is not None:
        hooks.on_llm_request(messages, None)
    response = provider.respond(
        messages,
        stream=bool(hooks and hooks.stream_llm),
        on_text=hooks.on_llm_text if hooks else None,
        on_thinking=hooks.on_llm_thinking if hooks else None,
    )
    if hooks and hooks.on_llm_response is not None:
        hooks.on_llm_response(response)
    if response.kind != "message" or not response.content.strip():
        raise OpenTorusError(f"Model returned no LaTeX for {pid}.")
    return sanitize_latex_body(_extract_latex_fragment(response.content))


def proof_body_to_latex(
    proof: dict[str, Any],
    provider: BaseProvider | None = None,
    *,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
    cache: dict[str, str] | None = None,
) -> str:
    """Render a proof sketch body as integrated LaTeX (LLM, deterministic per-proof fallback).

    A ``cache`` keyed by proof id memoizes the (expensive) LLM conversion so a
    failed whole-document attempt does not pay to re-convert every proof on the
    next, deterministic-structure attempt.
    """
    body = proof.get("body") or ""
    if not body.strip():
        return ""
    if compose_llm and _llm_usable(provider):
        pid = proof.get("id") or ""
        if cache is not None and pid in cache:  # reuse a prior LLM conversion
            return cache[pid]
        try:
            latex = llm_convert_proof_to_latex(proof, provider, hooks=hooks)
            if cache is not None and pid:
                cache[pid] = latex
            return latex
        except Exception as exc:  # noqa: BLE001 — fall back to deterministic LaTeX rendering
            logger.debug("LLM proof-to-LaTeX conversion failed (%s); using fallback.", exc)
    return _proof_markdown_to_latex_fallback(body)


def _gap_text(gap: Any) -> str:
    """A human-readable gap label, whether a gap is a plain string or a record dict."""
    if isinstance(gap, dict):
        label = gap.get("id")
        desc = gap.get("description") or gap.get("text") or ""
        return f"{label}: {desc}" if label and desc else (desc or str(label or ""))
    return str(gap)


def _proofs_section_latex(
    facts: dict[str, Any],
    provider: BaseProvider | None = None,
    *,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
    cache: dict[str, str] | None = None,
) -> str:
    """LaTeX section with proof sketch bodies rendered as math-aware LaTeX."""
    proofs = facts.get("proofs") or []
    if not proofs:
        return ""
    parts = [
        "\\section{Proof sketches (not machine-checked)}",
        "The following natural-language arguments are stored in the dossier. "
        "Status \\textbf{sketch} means gaps remain; they are \\emph{not} formally verified.",
        "",
    ]
    for proof in proofs:
        parts.append(
            "\\subsection{"
            + _latex_escape(f"{proof['id']} — {proof.get('title') or 'sketch'}")
            + f" [{_latex_escape(proof['status'])}]"
            + "}"
        )
        if proof.get("gaps"):
            gaps = ", ".join(_latex_escape(_gap_text(g)) for g in proof["gaps"])
            parts.append(f"\\textit{{Recorded gaps:}} {gaps}")
        latex_body = proof_body_to_latex(
            proof,
            provider,
            compose_llm=compose_llm,
            hooks=hooks,
            cache=cache,
        )
        if latex_body:
            parts.append(latex_body)
        parts.append("")
    return "\n".join(parts).rstrip()


def _append_missing_proofs(
    body: str,
    facts: dict[str, Any],
    provider: BaseProvider | None = None,
    *,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
    cache: dict[str, str] | None = None,
) -> str:
    """Ensure every PROOF-* body appears in the LaTeX report body (LLM often omits them)."""
    proofs = facts.get("proofs") or []
    if not proofs:
        return body
    missing = [p for p in proofs if p.get("id") and p["id"] not in body]
    if not missing:
        return body
    partial = {**facts, "proofs": missing}
    section = _proofs_section_latex(
        partial,
        provider,
        compose_llm=compose_llm,
        hooks=hooks,
        cache=cache,
    )
    return body.rstrip() + "\n\n" + section + "\n"


_VERBATIM_PROOF_RE = re.compile(
    r"\\begin\{verbatim\}[\s\S]*?#\s*(PROOF-\d{4})[\s\S]*?\\end\{verbatim\}",
    re.IGNORECASE,
)


def _replace_verbatim_proof_blocks(
    body: str,
    facts: dict[str, Any],
    provider: BaseProvider | None = None,
    *,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
    cache: dict[str, str] | None = None,
) -> str:
    """Swap LLM-emitted verbatim proof dumps for converted LaTeX proof sections."""
    proofs = {p["id"]: p for p in (facts.get("proofs") or []) if p.get("id")}

    def repl(match: re.Match[str]) -> str:
        pid = match.group(1).upper()
        proof = proofs.get(pid)
        if proof is None:
            return match.group(0)
        latex = proof_body_to_latex(
            proof,
            provider,
            compose_llm=compose_llm,
            hooks=hooks,
            cache=cache,
        )
        return latex if latex else match.group(0)

    return _VERBATIM_PROOF_RE.sub(repl, body)


def facts_to_latex(
    facts: dict[str, Any],
    *,
    provider: BaseProvider | None = None,
    proof_compose_llm: bool = False,
    cache: dict[str, str] | None = None,
) -> str:
    """LaTeX body from local artifacts with a deterministic, always-well-formed structure.

    The document scaffold (summary, claims table, experiments) is template-generated.
    With ``proof_compose_llm=True`` and a usable ``provider``, the proof-sketch bodies
    are converted to clean LaTeX by the model (reliable typeset math) while the
    surrounding structure stays deterministic — the robust "pretty math" path used
    when whole-document LLM composition truncates or fails to compile.
    """
    parts: list[str] = [
        "\\section{Summary}",
        _latex_escape(
            f"Auto-generated report for {facts['problem_id']}. "
            "See sections below for claims, experiments, and proof attempts."
        ),
        "",
        "\\section{Problem statement}",
        _latex_escape(facts.get("statement") or "(no statement recorded)"),
        "",
        f"\\paragraph{{Status.}} "
        f"Status: \\textbf{{{_latex_escape(str(facts.get('status', '')))}}}; "
        f"formalization: {_latex_escape(str(facts.get('formalization', '')))}.",
        "",
    ]

    if facts["claims"]:
        parts.extend(
            [
                "\\section{Claims and evidence}",
                "\\begin{tabular}{llp{0.45\\linewidth}l}",
                "\\hline",
                "Id & Type & Statement & Evidence \\\\",
                "\\hline",
            ]
        )
        for claim in facts["claims"]:
            ev_ids = ", ".join(e["id"] for e in claim["evidence"]) or "(none)"
            parts.append(
                f"{_latex_escape(claim['id'])} & "
                f"{_latex_escape(claim['type'])} & "
                f"{_latex_escape(claim['statement'])} & "
                f"{_latex_escape(ev_ids)} \\\\"
            )
        parts.extend(["\\hline", "\\end{tabular}", ""])
    else:
        parts.extend(["\\section{Claims and evidence}", "(none recorded)", ""])

    if facts["experiments"]:
        parts.append("\\section{Experiments}")
        for exp in facts["experiments"]:
            heading = (
                "\\subsection{"
                + _latex_escape(f"{exp['id']} — {exp['title']}")
                + f" [{_latex_escape(exp['status'])}]"
            )
            parts.extend(
                [
                    heading,
                    f"\\texttt{{{_latex_escape(exp['command'])}}} "
                    f"(seed: {_latex_escape(str(exp['random_seed']))})",
                ]
            )
            if exp["result_summary"]:
                parts.append(_latex_escape(exp["result_summary"]))
            if exp["stdout_tail"]:
                parts.append(_latex_verbatim(exp["stdout_tail"]))
            parts.append("")
    else:
        parts.extend(["\\section{Experiments}", "(none recorded)", ""])

    proof_section = _proofs_section_latex(
        facts,
        provider,
        compose_llm=proof_compose_llm,
        cache=cache,
    )
    if proof_section:
        parts.extend([proof_section, ""])
    else:
        parts.extend(["\\section{Proof attempts}", "(none recorded)", ""])

    counter = [c for c in facts["claims"] if "COUNTEREXAMPLE" in c["type"]]
    if counter:
        parts.extend(
            [
                "\\section{Conclusions}",
                "A computational counterexample candidate was recorded. "
                "This is \\textbf{not} a formally verified refutation unless marked verified.",
                "",
            ]
        )

    parts.extend(
        [
            "\\section*{References}",
            "\\addcontentsline{toc}{section}{References}",
            "\\begin{itemize}",
        ]
    )
    for key in ("claims", "experiments", "proofs"):
        for item in facts.get(key) or []:
            item_id = item.get("id") or item.get("experiment_id")
            if item_id:
                parts.append(f"\\item \\texttt{{{_latex_escape(str(item_id))}}}")
    parts.extend(["\\end{itemize}", ""])
    return "\n".join(parts)


def _extract_latex_fragment(text: str) -> str:
    stripped = text.strip()
    fence = re.search(r"```(?:latex|tex)?\s*([\s\S]+?)```", stripped)
    if fence:
        stripped = fence.group(1).strip()
    if stripped.lower().startswith("\\documentclass"):
        begin = re.search(r"\\begin\{document\}([\s\S]*)\\end\{document\}", stripped)
        if begin:
            return begin.group(1).strip()
    return stripped


def llm_compose_latex(
    facts: dict[str, Any],
    provider: BaseProvider,
    *,
    markdown_context: str = "",
    hooks: ReportComposeHooks | None = None,
) -> str:
    """Ask the configured model to write a LaTeX report body from artifact facts."""
    from opentorus.agent.session import SessionMessage
    from opentorus.providers.base import provider_label

    payload = json.dumps(facts, ensure_ascii=False, indent=2)
    if len(payload) > _LLM_MAX_CHARS:
        payload = payload[:_LLM_MAX_CHARS] + "\n…"
    context = ""
    if markdown_context.strip():
        context = f"\n\nExisting report.md (reference only):\n\n{markdown_context[:12000]}\n"
    prompt = (
        f"Compose the final research report body for dossier {facts['problem_id']}.\n\n"
        f"{_COMPOSE_RULES}\n\n"
        f"Investigation payload (JSON — sole source of truth):\n\n{payload}{context}"
    )
    label = provider_label(provider)
    if hooks and hooks.on_progress:
        hooks.on_progress(
            f"Writing report narrative for {facts['problem_id']} with {label} "
            f"({len(payload):,} chars of dossier facts)…"
        )

    streamed = {"chars": 0, "last_report": 0}

    def _on_text(chunk: str) -> None:
        if hooks and hooks.on_llm_text is not None:
            hooks.on_llm_text(chunk)
            return
        streamed["chars"] += len(chunk)
        if hooks and hooks.on_progress and streamed["chars"] - streamed["last_report"] >= 200:
            streamed["last_report"] = streamed["chars"]
            hooks.on_progress(f"  …{label} returned {streamed['chars']:,} chars so far")

    def _on_thinking(chunk: str) -> None:
        if hooks and hooks.on_llm_thinking is not None:
            hooks.on_llm_thinking(chunk)

    messages = [SessionMessage(role="user", content=prompt)]
    if hooks and hooks.on_llm_request is not None:
        hooks.on_llm_request(messages, None)
    use_stream = (
        hooks.stream_llm
        if hooks is not None and hooks.stream_llm is not None
        else bool(hooks and (hooks.on_llm_text or hooks.on_llm_thinking))
    )
    response = provider.respond(
        messages,
        stream=use_stream,
        on_text=_on_text if use_stream else None,
        on_thinking=_on_thinking if use_stream else None,
    )
    if hooks and hooks.on_llm_response is not None:
        hooks.on_llm_response(response)
    if response.kind != "message" or not response.content.strip():
        raise OpenTorusError("Model returned no LaTeX for the PDF report.")
    return sanitize_latex_body(_extract_latex_fragment(response.content))


def wrap_preprint_document(facts: dict[str, Any], body: str) -> str:
    """Wrap a LaTeX body fragment in the preprint document class."""
    title = _latex_escape(f"{facts['problem_id']} — {facts['title']}")
    short = _latex_escape(_short_title(facts))
    return f"""\
\\documentclass[a4paper,colorlinks]{{preprint}}

\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[english]{{babel}}
\\usepackage{{graphicx}}
\\usepackage{{amsmath,amssymb,amsthm}}
\\usepackage{{booktabs}}

\\title{{{title}}}

\\author[$\\ast$]{{OpenTorus Research Agent}}
\\affil[$\\ast$]{{Generated from local dossier artifacts.\\authorcr
 \\email{{opentorus@local}}}}

\\shorttitle{{{short}}}
\\shortauthor{{OpenTorus}}
\\shortinstitute{{OpenTorus investigation report}}

\\begin{{document}}

\\maketitle

{body.rstrip()}

\\end{{document}}
"""


def preprint_cls_source() -> Path:
    """Path to the bundled preprint.cls (ninsteve/preprint-template, BSD-2)."""
    if not _PREPRINT_CLS.is_file():
        raise OpenTorusError(
            "Bundled preprint.cls is missing from the OpenTorus install. "
            "Reinstall the package or restore opentorus/research/dossier/templates/preprint.cls."
        )
    return _PREPRINT_CLS


def _install_preprint_cls(work_dir: Path) -> None:
    """Install or refresh bundled preprint.cls (template fixes must reach old workspaces)."""
    shutil.copy2(preprint_cls_source(), work_dir / "preprint.cls")


def tex_available() -> bool:
    """True when a LaTeX engine (pdflatex/lualatex/xelatex) is installed on PATH."""
    from opentorus.research.authoring import _available_latex_engines

    return bool(_available_latex_engines())


def latex_lint(document: str) -> list[str]:
    """Cheap structural pre-compile checks that catch common opaque-failure causes.

    Advisory, not a hard gate: verbatim/listings blocks can legitimately contain
    unbalanced-looking characters, so findings are surfaced to *explain* a failed
    compile rather than to block a compile that would otherwise succeed.
    """
    from collections import Counter

    issues: list[str] = []
    # A bare ``[GAP-n]`` is read as an optional argument and breaks compilation; a
    # marker already guarded as ``\texttt{[GAP-n]}`` (``[`` preceded by ``{``) is safe.
    for m in re.finditer(r"(?<!\{)\[GAP-\d+\]", document):
        issues.append(f"bare gap marker '{m.group(0)}' left in the document")
    # Inline math $...$: count '$' that are neither escaped (\$) nor display ($$).
    stripped = re.sub(r"\\\$", "", document).replace("$$", "")
    if stripped.count("$") % 2 != 0:
        issues.append("odd number of unescaped '$' — inline math is unbalanced")
    if document.count(r"\[") != document.count(r"\]"):
        issues.append(r"unbalanced display math: \[ vs \] counts differ")
    if document.count(r"\(") != document.count(r"\)"):
        issues.append(r"unbalanced inline math: \( vs \) counts differ")
    begins = Counter(re.findall(r"\\begin\{([^}]+)\}", document))
    ends = Counter(re.findall(r"\\end\{([^}]+)\}", document))
    for env in set(begins) | set(ends):
        if begins[env] != ends[env]:
            issues.append(
                f"unbalanced environment '{env}': {begins[env]} \\begin vs {ends[env]} \\end"
            )
    no_esc = re.sub(r"\\[{}]", "", document)
    if no_esc.count("{") != no_esc.count("}"):
        issues.append(f"unbalanced braces: {no_esc.count('{')} '{{' vs {no_esc.count('}')} '}}'")
    return issues


def compile_latex_report(tex_path: Path, *, pdf_path: Path | None = None) -> Path:
    """Compile a preprint .tex file to PDF using the workspace LaTeX toolchain."""
    from opentorus.research.authoring import compile_latex_project

    work_dir = tex_path.parent
    main_stem = tex_path.stem
    _install_preprint_cls(work_dir)
    result = compile_latex_project(work_dir, main_stem)
    built = Path(result.pdf_path)
    if pdf_path is not None and built.resolve() != pdf_path.resolve():
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, pdf_path)
        return pdf_path
    return built


def compose_narrative_tex(
    ot_dir: Path,
    problem_id: str,
    *,
    provider: BaseProvider | None = None,
    compose_llm: bool = True,
    markdown_context: str = "",
    hooks: ReportComposeHooks | None = None,
) -> str:
    """Return a full preprint .tex document (LLM or deterministic fallback)."""
    from opentorus.agent.prove_harvest import harvest_prove_session

    if hooks and hooks.on_progress:
        hooks.on_progress("Gathering artifacts from the dossier…")
    harvest_prove_session(ot_dir, problem_id, create_proof=True)
    facts = gather_dossier_facts(ot_dir, problem_id)
    body = facts_to_latex(facts)
    if compose_llm and _llm_usable(provider):
        if hooks and hooks.on_progress:
            hooks.on_progress("Composing narrative report with the model…")
        try:
            body = llm_compose_latex(
                facts,
                provider,
                markdown_context=markdown_context,
                hooks=hooks,
            )
        except Exception:
            body = facts_to_latex(facts)
    body = _replace_verbatim_proof_blocks(
        body, facts, provider, compose_llm=compose_llm, hooks=hooks
    )
    body = _append_missing_proofs(body, facts, provider, compose_llm=compose_llm, hooks=hooks)
    body = sanitize_latex_body(body)
    return wrap_preprint_document(facts, body)


def compose_and_render_pdf(
    ot_dir: Path,
    problem_id: str,
    *,
    pdf_path: Path,
    tex_path: Path | None = None,
    markdown_context: str = "",
    provider: BaseProvider | None = None,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
) -> Path:
    """Build a preprint PDF with model-composed LaTeX (a model is required).

    Stored proofs hold mathematics as Unicode-in-prose; turning that into valid
    typeset LaTeX is only reliable with a model. Without one the old deterministic
    path produced math as literal escaped text (e.g. ``AinC\\textasciicircum{}…``),
    which is unreadable — so we refuse here and let the caller fall back to the
    MathJax HTML report instead of emitting a math-broken PDF.

    Two model attempts: the whole-document narrative first, then a deterministic
    document structure with per-proof model conversion (which survives a truncated
    or non-compiling whole-document call). On failure the caller renders HTML.
    """
    from opentorus.agent.prove_harvest import harvest_prove_session

    if not (compose_llm and _llm_usable(provider)):
        raise OpenTorusError(
            "PDF export requires a configured model to render mathematics; "
            "falling back to the HTML report (math rendered via MathJax)."
        )

    if hooks and hooks.on_progress:
        hooks.on_progress("Gathering artifacts from the dossier…")
    harvest_prove_session(ot_dir, problem_id, create_proof=True)
    facts = gather_dossier_facts(ot_dir, problem_id)

    # Shared across attempts so a failed whole-document attempt does not pay to
    # re-run the per-proof model conversions on the next, deterministic-structure one.
    proof_cache: dict[str, str] = {}

    def _document(*, use_llm: bool) -> str:
        # The whole-document body is a throwaway baseline (overwritten by the model),
        # so only convert proofs in the baseline when it IS the final structure.
        body = facts_to_latex(
            facts, provider=provider, proof_compose_llm=not use_llm, cache=proof_cache
        )
        if use_llm:
            if hooks and hooks.on_progress:
                hooks.on_progress("Composing narrative report with the model…")
            try:
                body = llm_compose_latex(
                    facts, provider, markdown_context=markdown_context, hooks=hooks
                )
            except Exception:
                body = facts_to_latex(
                    facts, provider=provider, proof_compose_llm=True, cache=proof_cache
                )
        body = _replace_verbatim_proof_blocks(
            body, facts, provider, compose_llm=True, hooks=hooks, cache=proof_cache
        )
        body = _append_missing_proofs(
            body, facts, provider, compose_llm=True, hooks=hooks, cache=proof_cache
        )
        return wrap_preprint_document(facts, sanitize_latex_body(body))

    target_tex = tex_path or pdf_path.with_suffix(".tex")
    target_tex.parent.mkdir(parents=True, exist_ok=True)

    last_exc: OpenTorusError | None = None
    last_lint: list[str] = []
    # whole-document model narrative, then deterministic structure + per-proof model conversion.
    for idx, use_llm in enumerate((True, False)):
        document = _document(use_llm=use_llm)
        target_tex.write_text(document, encoding="utf-8")
        last_lint = latex_lint(document)
        if last_lint and hooks and hooks.on_progress:
            hooks.on_progress("LaTeX pre-check flagged: " + "; ".join(last_lint))
        if hooks and hooks.on_progress:
            hooks.on_progress("Compiling PDF with LaTeX…")
        try:
            return compile_latex_report(target_tex, pdf_path=pdf_path)
        except OpenTorusError as exc:
            last_exc = exc
            if idx == 0 and hooks and hooks.on_progress:
                hooks.on_progress(
                    "Whole-document LaTeX failed; retrying with a deterministic "
                    "structure and per-proof model conversion…"
                )
    detail = ""
    if last_lint:
        detail = "\n\nPre-compile checks flagged (likely cause):\n" + "\n".join(
            f"  - {i}" for i in last_lint
        )
    raise OpenTorusError(f"{last_exc}{detail}\n\nLaTeX source saved at: {target_tex}") from last_exc
