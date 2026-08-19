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
from opentorus.research.dossier.experiments import experiment_dir, list_problem_experiments
from opentorus.research.dossier.theme import status_kind
from opentorus.research.memory import VALID_KINDS, list_memory
from opentorus.research.papers import is_paper_parsed, list_papers

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider
    from opentorus.research.dossier.honesty import ReportIssue

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
_OPENTORUS_CLS = _TEMPLATE_DIR / "opentorus.cls"

_COMPOSE_RULES = """\
Write a polished **research investigation report** as a LaTeX body fragment (no preamble,
no \\documentclass, no \\begin{document}).

Use the preprint article style: \\section, \\subsection, \\paragraph as needed.
Use LaTeX math ($...$ or \\(...\\)) for formulas; cite artifact ids inline (EXP-*, CLAIM-*, etc.).

Required sections (in this order):
1. \\section{Summary} — 2–4 sentences: problem, method, main finding, what remains open.
2. \\section{Problem statement} — restate clearly with proper math notation.
3. \\section{Investigation} — narrative of steps taken, tools run, artifact ids.
4. \\section{Literature} — only PAPER-* entries from JSON; if none, say so. Use the
   paper table shown below rather than a run-on paragraph.
5. \\section{Results} — for each experiment: \\subsection{EXP-...}, the command in
   \\otruncmd{...}, full stdout in \\begin{otoutput}...\\end{otoutput}, then interpret.
6. \\section{Claims and evidence} — use the claim table shown below.
7. \\section{Proof sketches (not machine-checked)} — for each entry in ``proofs`` in JSON:
   include \\subsection{PROOF-...}, list gaps, and the full ``body``.
   Open the section with an \\begin{otcaution}[Not a verified proof] ... \\end{otcaution}
   box stating that sketch status is NOT a verified proof.
8. \\section{Conclusions and open questions} — honest epistemic status.
9. \\section*{Artifact index} with \\addcontentsline{toc}{section}{Artifact index} and
   \\otartifactindex{...} holding a comma-separated list of every artifact id cited.

The document preamble already loads opentorus.sty. Use these macros — do NOT redefine
them and do NOT add a preamble:
- \\artifact{EXP-0001} for any artifact id (EXP-*, CLAIM-*, PAPER-*, PROOF-*, ACTION-*).
- \\statusok{verified} / \\statuswarn{open} / \\statusbad{refuted} / \\statusbadge{other}
  for status chips — green ONLY for genuinely settled statuses.
- \\gapmarker{[GAP-1]} for gap markers in proof sketches.
- \\begin{otoutput}...\\end{otoutput} for captured program output (never `verbatim`;
  otoutput wraps long lines instead of running off the page).
- \\otruncmd{python experiments/foo.py} for a command line.
- \\begin{otcaution}[Heading] ... \\end{otcaution} for epistemic caveats.
- \\othead{...} for table headings, \\ottype{...} for a secondary label in a cell.

Use the `L' column type for the one column that should absorb the leftover width
and `P{...}' for fixed ones; both wrap and are ragged-right. Artifact ids and
status chips are unbreakable boxes, so keep the fixed columns at least as wide as
below or they will run into the neighbouring cell.

Claim table (booktabs + tabularx, full width, type stacked under the id):
\\begin{tabularx}{\\linewidth}{@{}P{.175\\linewidth} L P{.18\\linewidth} P{.155\\linewidth}@{}}
\\toprule
\\othead{Claim} & \\othead{Statement} & \\othead{Status} & \\othead{Evidence} \\\\
\\midrule
\\artifact{CLAIM-0001}\\newline \\ottype{CONJECTURE} & ... & \\statuswarn{open} &
  \\artifact{EV-0001} \\\\
\\bottomrule
\\end{tabularx}

Paper table:
\\begin{tabularx}{\\linewidth}{@{}P{.155\\linewidth} L P{.22\\linewidth}@{}}
\\toprule
\\othead{Artifact} & \\othead{Title} & \\othead{DOI / arXiv} \\\\
\\midrule
\\artifact{PAPER-0001} & ... & \\ottype{10.1137/17m1140832} \\\\
\\bottomrule
\\end{tabularx}

Rules:
- Use ONLY facts from the JSON payload — never invent papers, experiments, or results.
- Counterexample candidates are NOT verified theorems — say so explicitly.
- In display math use \\[ ... \\] or align; never nest $...$ inside \\text{...}.
  For prose inside a set definition write: p \\in \\mathbb{R}[x] \\mid \\text{can be evaluated...}
  without dollar signs inside \\text.
- Escape LaTeX special characters in plain text (& % # _ { } ~ ^ \\).
- For file paths use \\path{experiments/script.py} (not \\texttt with raw underscores).
- Cite artifact ids inline as \\artifact{EXP-0001}; do not use \\cite (no .bib file).
- Professional prose suitable for a workshop preprint or short research note.
"""

_PROOF_MD_TO_LATEX_RULES = """\
Convert a natural-language proof sketch from Markdown into LaTeX body fragments
(no preamble, no \\documentclass, no \\begin{document}).

Use \\subsubsection{...} for ## headings, \\paragraph{...} for ### headings,
itemize/enumerate for lists, and $...$ / \\[...\\] for mathematics.
Numbered proof steps must become a real \\begin{enumerate} — never a run of
"1. ... 2. ..." inside one paragraph.
Wrap [GAP-n] markers as \\gapmarker{[GAP-n]}, keeping the text inside verbatim.
Cite PAPER-*, EXP-*, CLAIM-* as \\artifact{ID}.
Status is sketch — do NOT write QED or claim machine verification.
Escape LaTeX specials in plain text. Output ONLY the LaTeX fragment.
"""


def _llm_usable(provider: BaseProvider | None) -> TypeGuard[BaseProvider]:
    return provider is not None and getattr(provider, "name", "mock") != "mock"


def _read_experiment_stdout(ot_dir: Path, problem_id: str, exp_id: str) -> str:
    # Agent-run experiments live in the workspace store (.opentorus/experiments/),
    # dossier CRUD ones under problems/<pid>/experiments/ — check both homes.
    for base in (experiment_dir(ot_dir, problem_id, exp_id), ot_dir / "experiments" / exp_id):
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
    for exp in list_problem_experiments(ot_dir, pid):
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
        # Curly quotes/apostrophes and ellipsis \u2192 LaTeX-safe ASCII. NFKD has no
        # ASCII decomposition for these, so the last-resort transliteration used
        # to DROP them ("Stewart's bound" rendered as "Stewarts bound").
        "\u2018": "`",
        "\u2019": "'",
        "\u201c": "``",
        "\u201d": "''",
        "\u2026": "...",
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
# LLM-emitted verbatim blocks are rewritten to the styled `otoutput` environment
# (see opentorus.sty: preprint.cls loads lineno, which pins the stock `verbatim`
# so that fvextra's breaklines never fires and long output runs off the page).
_VERBATIM_ENV_RE = re.compile(r"\\(begin|end)\{verbatim\}")
_OLD_FONT_CMD_RE = re.compile(r"\{\\(tt|bf|it|rm|sl|sc|sf|mit)\s*([^}]*)\}")
_PANDOC_INLINE_RE = re.compile(r"\\\((.*?)\\\)")
# Segments that must not receive Unicode/markdown repair (math, verbatim, display).
_LATEX_PRESERVE_RE = re.compile(
    r"\$[^$\n]+\$|"
    r"\\\[[\s\S]*?\\\]|"
    r"\\begin\{verbatim\}[\s\S]*?\\end\{verbatim\}|"
    r"\\begin\{otoutput\}[\s\S]*?\\end\{otoutput\}|"
    r"\\begin\{lstlisting\}[\s\S]*?\\end\{lstlisting\}"
)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_ORDERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
# A display-math block in stored Markdown, which spans lines. It has to be lifted
# out before any per-line or Unicode-normalising pass touches the text: a naive
# "$...$" pairing reads the *second* dollar of an opening "$$" as an inline-math
# opener, and every later formula in the document then pairs off by one.
_MD_DISPLAY_MATH_RE = re.compile(r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]")


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
    return _GAP_MARKER_RE.sub(r"\\gapmarker{\1}", body)


def _use_output_environment(body: str) -> str:
    """Rewrite ``verbatim`` blocks to the styled, line-breaking ``otoutput`` env."""
    return _VERBATIM_ENV_RE.sub(r"\\\1{otoutput}", body)


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
    # Rewrite TeX-primitive display delimiters to the LaTeX form as balanced pairs
    # ($$…$$ -> \[…\]), so the equation is centred on its own line instead of being
    # crammed into the paragraph. Do NOT blindly replace every "$$" with "$": that
    # strips one delimiter from any display block the paired regex did not catch,
    # leaving odd '$' parity that aborts pdflatex.
    body = _DOUBLE_DOLLAR_RE.sub(lambda m: f"\\[{m.group(1).strip()}\\]", body)
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

    Tracks ``$`` / ``$$`` *and* ``\\[…\\]`` / ``\\(…\\)`` math context: a symbol in the
    Unicode→LaTeX map becomes its bare command inside math (``\\beta``) or ``$\\beta$``
    outside; anything unmapped is transliterated to ASCII (NFKD) and otherwise dropped.
    Backslash escapes are skipped. Getting the ``\\[…\\]`` case wrong would emit
    ``$\\beta$`` *inside* display math, which pdflatex rejects outright.
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
            if text[i + 1] in "[(":
                in_math = True
            elif text[i + 1] in "])":
                in_math = False
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
    body = _use_output_environment(body)
    # Last line of defense: never let a bare non-ASCII char reach pdflatex.
    body = _latex_safe_unicode(body)
    return body


def _latex_verbatim(text: str) -> str:
    """Wrap captured output in the styled ``otoutput`` environment."""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    for terminator in ("\\end{otoutput}", "\\end{verbatim}", "\\end{lstlisting}"):
        body = body.replace(terminator, "")
    return f"\\begin{{otoutput}}\n{body}\n\\end{{otoutput}}"


def _short_title(facts: dict[str, Any]) -> str:
    title = (facts.get("title") or facts["problem_id"]).strip()
    if len(title) > 60:
        return title[:57].rstrip() + "..."
    return title


def _clean_proof_markdown(body: str) -> str:
    body = _normalize_unicode(body)
    return body.replace("\ufffd", "?")


def _looks_like_latex_line(text: str) -> bool:
    """True when a Markdown line already carries LaTeX the escaper must not touch."""
    return "\\[" in text or "\\begin{" in text or "\\end{" in text


def _latex_item(text: str) -> str:
    """An ``\\item`` whose text is safe to start with ``[``.

    ``\\item [REFEREE] ...`` makes LaTeX read ``[REFEREE]`` as the item's optional
    argument and typeset it as a hanging description label; an empty group in
    front keeps it as ordinary text.
    """
    body = text.lstrip()
    return f"\\item {{}}{body}" if body.startswith("[") else f"\\item {body}"


def _inline_md_to_latex(text: str) -> str:
    """Escape a Markdown prose line for LaTeX, then apply Markdown emphasis.

    The order is the whole point. Converting first and escaping second turns the
    ``\\textbf{...}`` just produced into a literal ``\\textbackslash{}textbf\\{...\\}``,
    which is how ``\\{}textbf{[GAP-1] ...}`` used to reach the printed page.
    Escaping first is also strictly safer than the old "line contains ``$`` so
    skip escaping entirely" rule: ``$...$`` spans are preserved either way, but
    now a stray ``_``/``&``/``%`` in the surrounding prose can no longer abort
    the compile.
    """
    escaped = text if _looks_like_latex_line(text) else _latex_escape_preserving_math(text)
    escaped = _MD_BOLD_RE.sub(r"\\textbf{\1}", escaped)
    return _MD_ITALIC_RE.sub(r"\\emph{\1}", escaped)


def _markdown_to_latex(body: str, *, proof_meta: bool = False) -> str:
    """Deterministic Markdown → LaTeX for a stored body (no model).

    With ``proof_meta`` the proof-sketch conventions are honoured too: the
    ``# PROOF-0001`` title line is dropped (the caller already emits a heading)
    and a ``_Status: ..._`` line becomes an italic note.
    """
    from opentorus.research.markdown_latex import prepare_markdown_for_pdf

    body = _clean_proof_markdown(body)
    out: list[str] = []
    open_list: str | None = None

    def close_list() -> None:
        nonlocal open_list
        if open_list is not None:
            out.append(f"\\end{{{open_list}}}")
            open_list = None

    def open_as(env: str) -> None:
        nonlocal open_list
        if open_list != env:
            close_list()
            out.append(f"\\begin{{{env}}}")
            open_list = env

    def emit_prose(segment: str) -> None:
        nonlocal open_list
        if not segment.strip():
            return
        for raw in prepare_markdown_for_pdf(segment).splitlines():
            stripped = raw.strip()
            if not stripped:
                close_list()
                out.append("")
                continue
            if proof_meta:
                if stripped.startswith("# ") and "PROOF-" in stripped.upper():
                    continue
                if stripped.lower().startswith(("_status:", "*status:")):
                    out.append(f"\\textit{{{_latex_escape(stripped.strip('_* '))}}}")
                    continue
            if stripped.startswith("### "):
                close_list()
                out.append(f"\\paragraph{{{_latex_escape(stripped[4:].strip())}}}")
                continue
            if stripped.startswith("## "):
                close_list()
                out.append(f"\\subsubsection{{{_latex_escape(stripped[3:].strip())}}}")
                continue
            if stripped.startswith("# "):
                close_list()
                out.append(f"\\subsubsection{{{_latex_escape(stripped[2:].strip())}}}")
                continue
            if stripped.startswith(("- ", "* ")):
                open_as("itemize")
                out.append(_latex_item(_inline_md_to_latex(stripped[2:].strip())))
                continue
            ordered = _MD_ORDERED_RE.match(stripped)
            if ordered:
                # Numbered proof steps used to run together into one paragraph
                # ("1. … 2. … 3. …"); render them as a real enumerate.
                open_as("enumerate")
                out.append(_latex_item(_inline_md_to_latex(ordered.group(2).strip())))
                continue
            if open_list is not None and raw[:1].isspace() and out:
                # Indented continuation of the current bullet — appending it to the
                # item keeps it inside the list instead of ending the list early and
                # leaving an orphan line hanging under it.
                out[-1] = f"{out[-1]} {_inline_md_to_latex(stripped)}"
                continue
            close_list()
            out.append(_inline_md_to_latex(stripped))

    last = 0
    for match in _MD_DISPLAY_MATH_RE.finditer(body):
        emit_prose(body[last : match.start()])
        close_list()
        # Both delimiter pairs are two characters wide ("$$"…"$$", "\["…"\]").
        out.append(f"\\[{match.group(0)[2:-2].strip()}\\]")
        last = match.end()
    emit_prose(body[last:])
    close_list()
    return sanitize_latex_body("\n".join(out))


def _proof_markdown_to_latex_fallback(body: str) -> str:
    """Deterministic Markdown → LaTeX for a single proof sketch (no model).

    Used only as a per-proof fallback when the model conversion of *that* proof
    fails; the whole-document deterministic PDF path was removed (it could not
    render Unicode-in-prose mathematics legibly — see :func:`compose_and_render_pdf`).
    """
    return _markdown_to_latex(body, proof_meta=True)


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
        "\\begin{otcaution}[Not a verified proof]",
        "The natural-language arguments below are stored in the dossier as "
        "\\emph{sketches}: gaps remain, and nothing here has been machine-checked. "
        "They support the claims they accompany; they do not establish them.",
        "\\end{otcaution}",
        "",
    ]
    for proof in proofs:
        parts.append(
            "\\subsection{"
            + _latex_escape(f"{proof['id']} — {proof.get('title') or 'sketch'}")
            + " "
            + status_chip(str(proof.get("status") or ""))
            + "}"
        )
        if proof.get("gaps"):
            gaps = "\n".join(
                _latex_item(_latex_escape_preserving_math(_gap_text(g))) for g in proof["gaps"]
            )
            parts.extend(
                [
                    "\\textbf{Recorded gaps.}",
                    "\\begin{itemize}",
                    gaps,
                    "\\end{itemize}",
                ]
            )
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
    r"\\begin\{(?:verbatim|otoutput)\}[\s\S]*?#\s*(PROOF-\d{4})[\s\S]*?"
    r"\\end\{(?:verbatim|otoutput)\}",
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
        # statement.md is Markdown with real LaTeX math; escaping it wholesale
        # printed the source ("$W(A) = \\{}mathbb{C}...$") instead of the formula.
        _markdown_to_latex(facts["statement"])
        if (facts.get("statement") or "").strip()
        else "(no statement recorded)",
        "",
    ]

    if facts["claims"]:
        parts.extend(
            [
                "\\section{Claims and evidence}",
                # The type rides under the id rather than in its own column: five
                # columns cannot hold an artifact id, a type, a status chip and an
                # evidence list and still leave the statement a readable width.
                "\\begin{tabularx}{\\linewidth}"
                "{@{}P{.175\\linewidth} L P{.18\\linewidth} P{.155\\linewidth}@{}}",
                "\\toprule",
                "\\othead{Claim} & \\othead{Statement} & "
                "\\othead{Status} & \\othead{Evidence} \\\\",
                "\\midrule",
            ]
        )
        for claim in facts["claims"]:
            ev_ids = (
                ", ".join(f"\\artifact{{{_latex_escape(e['id'])}}}" for e in claim["evidence"])
                or "(none)"
            )
            parts.append(
                f"\\artifact{{{_latex_escape(claim['id'])}}}\\newline "
                f"\\ottype{{{_breakable_type(claim['type'])}}} & "
                f"{_latex_escape_preserving_math(claim['statement'])} & "
                f"{status_chip(str(claim['status']))} & "
                f"{ev_ids} \\\\"
            )
        parts.extend(["\\bottomrule", "\\end{tabularx}", ""])
    else:
        parts.extend(["\\section{Claims and evidence}", "(none recorded)", ""])

    if facts["experiments"]:
        parts.append("\\section{Experiments}")
        for exp in facts["experiments"]:
            parts.extend(
                [
                    "\\subsection{"
                    + _latex_escape(f"{exp['id']} — {exp['title']}")
                    + " "
                    + status_chip(str(exp["status"]))
                    + "}",
                    f"\\otruncmd{{{_latex_escape(exp['command'])}}}",
                    f"\\emph{{Random seed:}} {_latex_escape(str(exp['random_seed']))}.",
                ]
            )
            if exp["result_summary"]:
                parts.append(_latex_escape_preserving_math(exp["result_summary"]))
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
                "\\begin{otcaution}[Counterexample candidate]",
                "A computational counterexample candidate was recorded. This is "
                "\\textbf{not} a formally verified refutation unless the claim is "
                "explicitly marked verified above.",
                "\\end{otcaution}",
                "",
            ]
        )

    ids: list[str] = []
    for key in ("claims", "experiments", "proofs"):
        for item in facts.get(key) or []:
            item_id = item.get("id") or item.get("experiment_id")
            if item_id:
                ids.append(f"\\artifact{{{_latex_escape(str(item_id))}}}")
    parts.extend(
        [
            "\\section*{Artifact index}",
            "\\addcontentsline{toc}{section}{Artifact index}",
            "Every artifact this report draws on, by local id:",
            "",
            "\\otartifactindex{" + (", ".join(ids) if ids else "(none recorded)") + "}",
            "",
        ]
    )
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


#: Chip kind (from the shared theme) → the LaTeX macro that draws it.
_CHIP_MACRO = {"ok": "statusok", "warn": "statuswarn", "bad": "statusbad"}


def status_chip(status: str) -> str:
    """A colour-coded ``\\status*`` chip for a status string.

    The status → colour mapping lives in :mod:`opentorus.research.dossier.theme`
    so the PDF and the HTML report agree: green only for statuses the artifacts
    really license (``verified``, ``formally_verified``, ``supported``,
    ``succeeded``), amber for open or in-flight ones, red for negative outcomes.
    Anything unrecognised — including ``unverified`` and ``unknown`` — stays
    neutral grey rather than borrowing the colour of a stronger claim.
    """
    text = (status or "").strip()
    if not text:
        return ""
    cmd = _CHIP_MACRO.get(status_kind(text), "statusbadge")
    return f"\\{cmd}{{{_latex_escape(text)}}}"


def _breakable_type(claim_type: str) -> str:
    """A claim type that may wrap inside a narrow table column.

    ``COUNTEREXAMPLE_CANDIDATE`` is a single unbreakable word once escaped, and it
    is wider than any column that still leaves room for the statement; an explicit
    break opportunity after each underscore lets it wrap instead of running into
    the neighbouring cell.
    """
    return _latex_escape(claim_type).replace("\\_", "\\_\\allowbreak{}")


def artifact_counts(facts: dict[str, Any], *, separator: str = " · ") -> str:
    """`3 claims · 2 experiments · …`, listing only the non-empty artifact kinds.

    Shared with the HTML report so both metadata strips count the same things;
    the caller supplies the separator its markup needs.
    """
    pairs = (
        ("claim", "claims"),
        ("experiment", "experiments"),
        ("proof sketch", "proofs"),
        ("failed attempt", "failed_attempts"),
        ("paper", "literature"),
    )
    parts = []
    for label, key in pairs:
        count = len(facts.get(key) or [])
        if count:
            parts.append(f"{count} {label}{'' if count == 1 else 's'}")
    return separator.join(parts) if parts else "none recorded"


def _dossier_panel(facts: dict[str, Any]) -> str:
    """The metadata strip printed under the title."""
    status = status_chip(str(facts.get("status") or "")) or _latex_escape(
        str(facts.get("status") or "unknown")
    )
    formalization = _latex_escape(str(facts.get("formalization") or "informal"))
    counts = artifact_counts(facts, separator=" \\textperiodcentered{} ")
    return (
        "\\otdossierpanel{%\n"
        f"  \\otmeta{{Dossier}}{{\\artifact{{{_latex_escape(facts['problem_id'])}}}}} &\n"
        f"  \\otmeta{{Status}}{{{status}}} &\n"
        f"  \\otmeta{{Formalization}}{{{formalization}}} &\n"
        f"  \\otmeta{{Artifacts}}{{{counts}}}%\n"
        "}"
    )


def wrap_preprint_document(facts: dict[str, Any], body: str) -> str:
    """Wrap a LaTeX body fragment in the preprint document class."""
    title = _latex_escape(f"{facts['problem_id']} — {facts['title']}")
    short = _latex_escape(_short_title(facts))
    return f"""\
% opentorus.cls carries the whole design system: page geometry, fonts, headings,
% booktabs/tabularx tables and the OpenTorus macros (\\artifact, \\statusok,
% otoutput, otcaution, …). Nothing else needs loading here.
\\documentclass[a4paper]{{opentorus}}

\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[english]{{babel}}

\\title{{{title}}}

\\author[$\\ast$]{{OpenTorus Research Agent}}
\\affil[$\\ast$]{{Generated from local dossier artifacts.\\authorcr
 \\email{{opentorus@local}}}}

\\shorttitle{{{short}}}
\\shortauthor{{OpenTorus}}
\\shortinstitute{{OpenTorus investigation report}}

\\begin{{document}}

\\maketitle

{_dossier_panel(facts)}

{body.rstrip()}

\\end{{document}}
"""


def opentorus_cls_source() -> Path:
    """Path to the bundled opentorus.cls (the report document class)."""
    if not _OPENTORUS_CLS.is_file():
        raise OpenTorusError(
            "Bundled opentorus.cls is missing from the OpenTorus install. "
            "Reinstall the package or restore opentorus/research/dossier/templates/opentorus.cls."
        )
    return _OPENTORUS_CLS


def _install_templates(work_dir: Path) -> None:
    """Install or refresh the bundled LaTeX class.

    Copied on every compile rather than only when absent: template fixes have to
    reach workspaces that were built by an older OpenTorus (which also cleans up
    the preprint.cls/opentorus.sty pair those workspaces were built with).
    """
    shutil.copy2(opentorus_cls_source(), work_dir / "opentorus.cls")
    for stale in ("preprint.cls", "opentorus.sty"):
        (work_dir / stale).unlink(missing_ok=True)


def tex_available() -> bool:
    """True when a LaTeX engine (pdflatex/lualatex/xelatex) is installed on PATH."""
    from opentorus.research.authoring import _available_latex_engines

    return bool(_available_latex_engines())


_MATH_ENV_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline|displaymath|math)\*?\}.*?"
    r"\\end\{\1\*?\}",
    re.DOTALL,
)
_MATH_SPAN_RE = re.compile(r"\$\$.*?\$\$|\$.*?\$|\\\[.*?\\\]|\\\(.*?\\\)", re.DOTALL)
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?")


def _latex_to_prose(document: str) -> str:
    """Strip math and LaTeX commands so the honesty linter sees only narrative prose.

    Overclaim phrases ("we prove", "provably") live in prose, never inside math, so
    removing math spans/environments and command tokens avoids false positives while
    still catching narrative overclaiming.
    """
    text = _MATH_ENV_RE.sub(" ", document)
    text = _MATH_SPAN_RE.sub(" ", text)
    text = _LATEX_CMD_RE.sub(" ", text)
    return text.replace("{", " ").replace("}", " ").replace("%", " ")


# Lint kinds that are never emitted, in any composed document: an experiment-as-proof
# claim, or a proof/result claim the dossier's artifacts do not license. Softer kinds
# (weasel words, knowledge claims) are surfaced as warnings instead.
_HARD_OVERCLAIM_KINDS = ("experiment_proof", "proof_claim", "result_claim")


def _lint_composed_document(ot_dir: Path, problem_id: str, document: str) -> list[ReportIssue]:
    """Run the artifact-aware honesty linter over a composed LaTeX document's prose."""
    from opentorus.research.dossier.honesty import lint_report
    from opentorus.research.dossier.report import honesty_context

    has_p, has_r, has_t = honesty_context(ot_dir, problem_id)
    return lint_report(
        _latex_to_prose(document),
        has_verified_proof=has_p,
        has_reference=has_r,
        has_supported_theorem=has_t,
    )


def enforce_export_honesty(
    ot_dir: Path, problem_id: str, document: str, *, allow_overclaims: bool = False
) -> None:
    """Refuse a composed PDF that overclaims or exports an INVALID-status dossier.

    The model-composed LaTeX can reintroduce overclaims the honest ``report.md`` does
    not contain. This runs the artifact-aware honesty linter over the composed prose
    (with the dossier's own licensing context) and refuses to emit the PDF on a hard,
    unlicensed proof/result/experiment claim, or when the derived status is INVALID —
    unless ``allow_overclaims`` overrides. The caller then falls back to the honest
    HTML report.
    """
    if allow_overclaims:
        return
    from opentorus.research.dossier.status_gate import derive_status

    issues = _lint_composed_document(ot_dir, problem_id, document)
    hard = [i for i in issues if i.kind.value in _HARD_OVERCLAIM_KINDS]
    reasons: list[str] = []
    if hard:
        phrases = "; ".join(f"'{i.phrase}'" for i in hard[:5])
        reasons.append(f"{len(hard)} unlicensed overclaim(s) in the composed PDF ({phrases})")
    if derive_status(ot_dir, problem_id).status == "INVALID":
        reasons.append("the dossier's derived status is INVALID")
    if reasons:
        raise OpenTorusError(
            "Refusing to emit the PDF because " + "; ".join(reasons) + ". Fix the wording or "
            "back the claims, or pass --force to override (the honest HTML report is written "
            "instead)."
        )


def _append_honesty_warnings_tex(document: str, issues: list[ReportIssue]) -> str:
    """Attach the linter's soft findings to the narrative, mirroring report.md.

    ``report.md`` always carries an "Honesty Warnings" section; the narrative .tex
    gets the same treatment so a reader of the composed document sees every finding
    the linter could not justify from the artifacts.
    """
    lines = [
        "\\section*{Honesty warnings}",
        "% Appended by the artifact-aware honesty linter (mirrors report.md).",
        "\\begin{itemize}",
    ]
    for i in issues:
        item = f"line {i.line} [{i.kind.value}] '{i.phrase}': {i.suggestion}"
        lines.append(f"  \\item {_latex_escape(item)}")
    lines.append("\\end{itemize}")
    block = "\n".join(lines)
    marker = "\\end{document}"
    idx = document.rfind(marker)
    if idx == -1:
        return document.rstrip() + "\n\n" + block + "\n"
    return document[:idx] + block + "\n\n" + document[idx:]


def enforce_narrative_honesty(ot_dir: Path, problem_id: str, document: str) -> str:
    """Gate the LLM-composed narrative .tex with the same honesty machinery as the PDF.

    ``report.md`` is linted and the composed PDF passes ``enforce_export_honesty``,
    but the narrative .tex used to be written with no check at all. This refuses the
    same hard kinds the PDF gate refuses (experiment-as-proof, unlicensed
    proof/result claims) — loudly, with the lint findings — and appends the soft
    findings as an "Honesty warnings" section inside the document. Returns the
    (possibly warning-annotated) document.
    """
    issues = _lint_composed_document(ot_dir, problem_id, document)
    hard = [i for i in issues if i.kind.value in _HARD_OVERCLAIM_KINDS]
    if hard:
        findings = "; ".join(
            f"line {i.line} [{i.kind.value}] '{i.phrase}': {i.suggestion}" for i in hard[:5]
        )
        raise OpenTorusError(
            f"Refusing to write the narrative report: {len(hard)} unlicensed overclaim(s) "
            f"in the composed text — {findings} Fix the wording or back the claims with "
            "verification artifacts; the artifact report.md is unaffected."
        )
    soft = [i for i in issues if i.kind.value not in _HARD_OVERCLAIM_KINDS]
    if soft:
        document = _append_honesty_warnings_tex(document, soft)
    return document


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
    _install_templates(work_dir)
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
    document = wrap_preprint_document(facts, body)
    # The narrative used to bypass every honesty check report.md and the PDF get.
    # Gate it here so no caller can write an unlinted narrative: hard overclaims
    # refuse composition loudly; soft findings ride along inside the document.
    return enforce_narrative_honesty(ot_dir, problem_id, document)


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
    allow_overclaims: bool = False,
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
        # Refuse to typeset a PDF that overclaims relative to the artifacts (the model
        # may reintroduce proof language) or an INVALID-status dossier; the caller then
        # falls back to the honest HTML report unless --force was passed.
        enforce_export_honesty(ot_dir, problem_id, document, allow_overclaims=allow_overclaims)
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
