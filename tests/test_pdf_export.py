"""Tests for the LaTeX PDF report export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.dossier import store
from opentorus.research.dossier.pdf_export import (
    compile_latex_report,
    facts_to_latex,
    gather_dossier_facts,
    llm_compose_latex,
    sanitize_latex_body,
    wrap_preprint_document,
)
from opentorus.workspace import init_workspace, workspace_dir


def test_sanitize_latex_body_wraps_bare_gap_markers() -> None:
    raw = "Some text.\\\\\n[GAP-2] Missing link to lower bound."
    fixed = sanitize_latex_body(raw)
    # \gapmarker also guards the leading '[' from being read as an optional argument.
    assert r"\gapmarker{[GAP-2]}" in fixed


def test_sanitize_latex_body_fixes_pandoc_inline_math() -> None:
    raw = r"The rate \(\varepsilon_m^{*}\) remains open."
    fixed = sanitize_latex_body(raw)
    assert r"\(" not in fixed
    assert "$\\varepsilon_m^{*}$" in fixed


def test_sanitize_latex_body_fixes_text_in_display_math() -> None:
    raw = (
        r"\[ \Pi_{2^m}^{*} = \Bigl\{ p \mid "
        r"\text{$p$ can be evaluated with at most $2^{m}$ multiplications, "
        r"\textit{and any number of additions}\Bigr\}, \]"
    )
    fixed = sanitize_latex_body(raw)
    assert "$" not in fixed.split("\\text{")[1].split("}")[0]
    assert "\\ensuremath" in fixed
    assert "\\emph{" in fixed


def test_sanitize_latex_body_fixes_path_math_mix() -> None:
    raw = r"\path{bound\_ratio}=error / \bigl(2\,e^{-2}\bigr)"
    fixed = sanitize_latex_body(raw)
    assert "\\path{bound" not in fixed or "ratio" in fixed
    assert "$" in fixed
    assert "\\bigl" not in fixed


def test_plain_text_snippet_strips_latex() -> None:
    from opentorus.research.dossier.pdf_export import _plain_text_snippet

    text = "Let $\\Pi_{2^m}^*$ be the set. **Problem 6.3.**"
    plain = _plain_text_snippet(text)
    assert "$" not in plain
    assert "\\Pi" not in plain
    assert "Problem 6.3" in plain


def test_plain_text_snippet_strips_pandoc_math() -> None:
    from opentorus.research.dossier.pdf_export import _plain_text_snippet

    text = r"For polytope \(P\) with \(n\) facets and bound \(p(n,d)\)."
    plain = _plain_text_snippet(text)
    assert "\\(" not in plain
    assert "P" in plain
    assert "p(n,d)" in plain


def test_wrap_preprint_omits_abstract_and_keywords() -> None:
    facts = {
        "problem_id": "PROBLEM-0001",
        "title": "Problem 1",
        "status": "open",
        "tags": ["label:1", "source:notes.md"],
        "statement": "Prove submodularity for SDDM Laplacians.",
        "claims": [],
        "experiments": [],
        "proofs": [{"id": "PROOF-0001"}],
    }
    doc = wrap_preprint_document(facts, "\\section{Summary}\nTest.")
    assert "\\abstract{" not in doc
    assert "\\keywords{" not in doc
    assert "\\novelty{" not in doc
    assert "\\maketitle" in doc


def test_truncate_latex_safe_balances_math() -> None:
    from opentorus.research.dossier.pdf_export import _truncate_latex_safe

    text = "Intro " + r"$\Pi_{2^m}^{*}$ and more text " * 20
    cut = _truncate_latex_safe(text, 120)
    assert cut.endswith("…")
    assert cut.count("$") % 2 == 0


def test_sanitize_latex_body_fixes_texttt_math_mishmash() -> None:
    raw = (
        r"Define notation (e.g. \path{$\varepsilon$\_m^*}, \texttt{$\Pi$\_{2^m}^*}, "
        r"\path{$\delta$}, \texttt{I})."
    )
    fixed = sanitize_latex_body(raw)
    assert r"\path{$" not in fixed
    assert r"\texttt{$" not in fixed
    assert r"$\varepsilon_m^*$" in fixed
    assert r"$\Pi_{2^m}^*$" in fixed
    assert r"$\delta$" in fixed
    assert r"\texttt{I}" in fixed


def test_sanitize_latex_body_fixes_old_font_commands() -> None:
    raw = (
        r"Note [{\tt GAP-1}] and [{\bf GAP-2}: missing step] "
        r"with {\it emphasis}."
    )
    fixed = sanitize_latex_body(raw)
    assert r"{\tt" not in fixed
    assert r"{\bf" not in fixed
    assert r"{\it" not in fixed
    assert r"\texttt{GAP-1}" in fixed
    assert r"\textbf{GAP-2}" in fixed
    assert r"\textit{emphasis}" in fixed


def test_sanitize_latex_body_fixes_texttt_paths() -> None:
    raw = (
        "See \\texttt{experiments/check_submodular.py} and "
        "\\texttt{ACTION-0008} for details. "
        "Also \\cite{PAPER-0001}."
    )
    fixed = sanitize_latex_body(raw)
    assert "\\path{experiments/check_submodular.py}" in fixed
    assert "check_submodular" not in fixed or "\\path" in fixed
    assert "\\texttt{ACTION-0008}" in fixed
    assert "\\cite{PAPER-0001}" not in fixed
    assert "\\texttt{PAPER-0001}" in fixed


def test_sanitize_latex_body_normalizes_narrow_space() -> None:
    fixed = sanitize_latex_body("error\u202fbound")
    assert "\u202f" not in fixed
    assert "error bound" in fixed


def test_sanitize_latex_body_fixes_bare_unicode_kappa() -> None:
    raw = (
        "a spectral-clustering assumption could yield κ-independent convergence. "
        "Explore κ-independent backward error."
    )
    fixed = sanitize_latex_body(raw)
    assert "κ" not in fixed
    assert r"$\kappa$" in fixed
    assert "independent convergence" in fixed


def test_sanitize_latex_body_fixes_markdown_bold() -> None:
    raw = "such that for **all** invertible matrices. Status remains **open**."
    fixed = sanitize_latex_body(raw)
    assert "**" not in fixed
    assert r"\textbf{all}" in fixed
    assert r"\textbf{open}" in fixed


def test_sanitize_latex_body_preserves_math_blocks() -> None:
    raw = r"Known bound $\kappa(A)$ and also κ in text."
    fixed = sanitize_latex_body(raw)
    assert r"$\kappa(A)$" in fixed
    assert "κ" not in fixed
    assert r"$\kappa$" in fixed.split(r"$\kappa(A)$")[1]


def test_opentorus_cls_is_bundled() -> None:
    from opentorus.research.dossier.pdf_export import opentorus_cls_source

    path = opentorus_cls_source()
    assert path.is_file()
    assert path.name == "opentorus.cls"
    text = path.read_text(encoding="utf-8")
    # The macros the generator and the compose prompt both emit.
    for macro in (
        r"\newcommand{\artifact}",
        r"\newcommand{\gapmarker}",
        r"\newcommand{\otruncmd}",
        r"\newcommand{\otartifactindex}",
        r"\newcommand{\otdossierpanel}",
        r"\newenvironment{otcaution}",
        "otoutput",
    ):
        assert macro in text, macro


def test_install_templates_refreshes_class_and_clears_the_old_pair(tmp_path: Path) -> None:
    from opentorus.research.dossier.pdf_export import _install_templates

    # A workspace built by an older OpenTorus, carrying the retired template pair.
    (tmp_path / "preprint.cls").write_text("stale", encoding="utf-8")
    (tmp_path / "opentorus.sty").write_text("stale", encoding="utf-8")

    _install_templates(tmp_path)

    assert (tmp_path / "opentorus.cls").is_file()
    assert not (tmp_path / "preprint.cls").exists()
    assert not (tmp_path / "opentorus.sty").exists()


def test_wrap_preprint_loads_style_and_metadata_panel() -> None:
    facts = {
        "problem_id": "PROBLEM-0001",
        "title": "T",
        "status": "open",
        "formalization": "informal",
        "tags": [],
        "claims": [{"id": "CLAIM-0001"}],
        "experiments": [],
        "proofs": [{"id": "PROOF-0001"}],
    }
    doc = wrap_preprint_document(facts, "\\section{Summary}\nTest.")
    assert "\\documentclass[a4paper]{opentorus}" in doc
    assert "\\otdossierpanel{" in doc
    # Counts come from the artifacts actually present, and skip the empty kinds.
    assert "1 claim" in doc
    assert "1 proof sketch" in doc
    assert "experiment" not in doc.split("\\otdossierpanel{")[1].split("}\n")[0]
    # amssymb is deliberately NOT loaded here — opentorus.sty picks either it or
    # the Libertinus math font, and loading both clashes.
    loads = [ln for ln in doc.splitlines() if ln.startswith("\\usepackage")]
    assert not any("amssymb" in ln for ln in loads), loads


def test_status_chip_keeps_green_for_settled_statuses_only() -> None:
    """Colour must not upgrade an unverified claim into a settled-looking one."""
    from opentorus.research.dossier.pdf_export import status_chip

    assert status_chip("verified") == "\\statusok{verified}"
    assert status_chip("formally_verified") == "\\statusok{formally\\_verified}"
    assert status_chip("supported") == "\\statusok{supported}"
    assert status_chip("open") == "\\statuswarn{open}"
    assert status_chip("sketch") == "\\statuswarn{sketch}"
    assert status_chip("refuted") == "\\statusbad{refuted}"
    assert status_chip("contradicted") == "\\statusbad{contradicted}"
    # Neutral grey, never green.
    assert status_chip("unverified") == "\\statusbadge{unverified}"
    assert status_chip("unknown") == "\\statusbadge{unknown}"
    assert status_chip("") == ""


def test_latex_verbatim_uses_breaking_output_environment() -> None:
    from opentorus.research.dossier.pdf_export import _latex_verbatim

    block = _latex_verbatim("line one\nline two")
    assert block.startswith("\\begin{otoutput}")
    assert block.endswith("\\end{otoutput}")
    assert "verbatim" not in block


def test_sanitize_rewrites_verbatim_to_output_environment() -> None:
    raw = "\\begin{verbatim}\nstdout tail\n\\end{verbatim}"
    fixed = sanitize_latex_body(raw)
    # The old preprint.cls loaded lineno, which pinned the stock verbatim so
    # breaklines never fires and long output runs off the page.
    assert "\\begin{otoutput}" in fixed
    assert "\\end{otoutput}" in fixed
    assert "verbatim" not in fixed


def test_proof_fallback_does_not_double_escape_markdown_bold() -> None:
    """``**x**`` must become ``\\textbf{x}``, not a literal ``\\{}textbf{x}``."""
    from opentorus.research.dossier.pdf_export import _proof_markdown_to_latex_fallback

    md = "## Gaps\n- **[GAP-1] Quasi-polynomial transition**: no known mechanism for $\\log d$.\n"
    latex = _proof_markdown_to_latex_fallback(md)
    assert "\\textbackslash" not in latex
    assert "\\textbf{" in latex
    assert "$\\log d$" in latex


def test_proof_fallback_renders_numbered_steps_as_enumerate() -> None:
    from opentorus.research.dossier.pdf_export import _proof_markdown_to_latex_fallback

    md = "## Main proof\n1. Sample rows.\n2. Apply the bound.\n3. Conclude.\n"
    latex = _proof_markdown_to_latex_fallback(md)
    assert "\\begin{enumerate}" in latex
    assert latex.count("\\item") == 3
    assert "\\end{enumerate}" in latex


def test_markdown_display_math_does_not_corrupt_later_inline_math() -> None:
    """A multi-line ``$$…$$`` block used to shift ``$`` pairing for the whole body."""
    from opentorus.research.dossier.pdf_export import _markdown_to_latex

    md = (
        "Crouzeix's conjecture states that\n"
        "$$\n"
        "\\lVert p(A) \\rVert_2 \\le 2 \\max_{z \\in W(A)} |p(z)|,\n"
        "$$\n"
        "for every polynomial $p$.\n\n"
        "- Crouzeix-Palencia (2017): constant $1 + \\sqrt{2}$.\n"
    )
    latex = _markdown_to_latex(md)
    assert "\\[" in latex and "\\]" in latex
    assert "\\lVert p(A) \\rVert_2" in latex
    # The formula after the display block must survive intact.
    assert "$1 + \\sqrt{2}$" in latex
    assert "\\textbackslash" not in latex


def test_latex_item_guards_a_leading_bracket() -> None:
    """``\\item [REFEREE] …`` would otherwise be read as an optional argument."""
    from opentorus.research.dossier.pdf_export import _latex_item

    assert _latex_item("[REFEREE] unsupported claim") == "\\item {}[REFEREE] unsupported claim"
    assert _latex_item("ordinary gap") == "\\item ordinary gap"


def test_facts_to_latex_uses_booktabs_claim_table(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity question.", title="Test problem")
    from opentorus.research.dossier.claims import add_claim

    add_claim(
        ot,
        "PROBLEM-0001",
        claim_type="COUNTEREXAMPLE_CANDIDATE",
        statement="Error is not submodular for SDDM.",
    )
    body = facts_to_latex(gather_dossier_facts(ot, "PROBLEM-0001"))
    assert "\\begin{tabularx}" in body
    assert "\\toprule" in body and "\\midrule" in body and "\\bottomrule" in body
    assert "\\hline" not in body
    assert "\\artifact{CLAIM-0001}" in body
    # Long claim types must be able to wrap inside the narrow claim column.
    assert "COUNTEREXAMPLE\\_\\allowbreak{}CANDIDATE" in body
    # A counterexample candidate is flagged as not-a-refutation in a callout.
    assert "\\begin{otcaution}" in body
    assert "\\otartifactindex{" in body


def test_fix_corrupted_latex_norm_and_display_math() -> None:
    from opentorus.research.dossier.pdf_export import _fix_corrupted_latex

    raw = (
        "guarantee that $$12505\\|\\Pi_J A - A\\|_F \\le c(n,m,k)\\|\\Pi_J A - A\\|_F,$$ "
        "with high probability"
    )
    fixed = _fix_corrupted_latex(raw)
    assert "12505" not in fixed
    assert r"\|" in fixed
    assert "$$" not in fixed
    assert r"\$$" not in fixed
    # Display math becomes \[...\] so the equation is centred on its own line.
    assert fixed.count(r"\[") == 1
    assert fixed.count(r"\]") == 1


def test_replace_verbatim_proof_blocks() -> None:
    from opentorus.research.dossier.pdf_export import _replace_verbatim_proof_blocks

    facts = {
        "proofs": [
            {
                "id": "PROOF-0001",
                "title": "Sketch",
                "status": "sketch",
                "gaps": [],
                "body": "## Theorem\n\nLet $A$ be a matrix.\n",
            }
        ]
    }
    body = (
        "\\section{Proof sketches}\n"
        "\\begin{verbatim}\n# PROOF-0001 -- Sketch\n\n## Theorem\n\nLet A be a matrix.\n"
        "\\end{verbatim}\n"
    )
    out = _replace_verbatim_proof_blocks(body, facts, compose_llm=False)
    assert "\\begin{verbatim}" not in out
    assert "\\subsubsection{Theorem}" in out


def test_proof_markdown_to_latex_fallback_headings() -> None:
    from opentorus.research.dossier.pdf_export import _proof_markdown_to_latex_fallback

    md = (
        "# PROOF-0001 — Sketch\n"
        "_Status: sketch (NOT machine-checked)_\n\n"
        "## Theorem\n"
        "Let $A \\in \\mathbb{C}^{n \\times m}$ with $n \\ge m$.\n\n"
        "## Main proof\n"
        "1. Sample rows.\n"
        "[GAP-1] Matrix Chernoff bound.\n"
    )
    latex = _proof_markdown_to_latex_fallback(md)
    assert "\\subsubsection{Theorem}" in latex
    assert "\\subsubsection{Main proof}" in latex
    assert "[GAP-1]" in latex
    assert "\\begin{verbatim}" not in latex


def test_append_missing_proofs_adds_sketch_bodies() -> None:
    from opentorus.research.dossier.pdf_export import _append_missing_proofs

    facts = {
        "proofs": [
            {
                "id": "PROOF-0001",
                "title": "Main sketch",
                "status": "sketch",
                "gaps": ["Recurrence without log d"],
                "body": "Theorem: polynomial bound. [GAP-1] recurrence detail.",
            }
        ]
    }
    llm_body = "\\section{Summary}\nWe investigated the conjecture.\n"
    merged = _append_missing_proofs(llm_body, facts)
    assert "PROOF-0001" in merged
    assert "Recurrence without log d" in merged
    assert "[GAP-1]" in merged


def test_append_missing_proofs_skips_when_present() -> None:
    from opentorus.research.dossier.pdf_export import _append_missing_proofs

    facts = {
        "proofs": [{"id": "PROOF-0001", "title": "T", "status": "sketch", "gaps": [], "body": "x"}]
    }
    body = "\\section{Proof}\\nPROOF-0001 content"
    assert _append_missing_proofs(body, facts) == body


def test_facts_to_latex_includes_claims(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity question.", title="Test problem")
    from opentorus.research.dossier.claims import add_claim

    add_claim(
        ot,
        "PROBLEM-0001",
        claim_type="CONJECTURE",
        statement="Error is not submodular for SDDM.",
    )
    facts = gather_dossier_facts(ot, "PROBLEM-0001")
    body = facts_to_latex(facts)
    assert "CLAIM-0001" in body
    assert "Submodularity" in body
    doc = wrap_preprint_document(facts, body)
    assert "\\documentclass[a4paper]{opentorus}" in doc
    assert "\\maketitle" in doc


def test_llm_compose_uses_narrative_latex(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity?", title="Test")
    from opentorus.research.dossier.claims import add_claim

    add_claim(ot, "PROBLEM-0001", claim_type="CONJECTURE", statement="Not submodular.")

    class NarrativeProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "ollama"

        def generate(self, messages, tools=None):
            return ProviderResponse(
                kind="message",
                content=(
                    "\\section{Summary}\nFound counterexample via EXP-0001.\n"
                    "\\section{Results}\n\\begin{verbatim}\nMatrix L found\n\\end{verbatim}"
                ),
            )

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    facts = gather_dossier_facts(ot, "PROBLEM-0001")
    body = llm_compose_latex(facts, NarrativeProvider())
    assert "Summary" in body
    assert "EXP-0001" in body or "counterexample" in body.lower()


def test_wrap_preprint_includes_booktabs_for_llm_tables() -> None:
    facts = {"problem_id": "PROBLEM-0001", "title": "T", "status": "open", "tags": []}
    body = (
        "\\section{Claims}\n"
        "\\begin{tabular}{ll}\n"
        "\\toprule\nId & Statement \\\\\n"
        "\\midrule\n"
        "CLAIM-0001 & Test \\\\\n"
        "\\bottomrule\n"
        "\\end{tabular}\n"
    )
    doc = wrap_preprint_document(facts, body)
    # booktabs/tabularx now come from the class rather than a \usepackage line.
    assert "\\documentclass[a4paper]{opentorus}" in doc
    assert "\\toprule" in doc


def test_literature_phase_rejects_chat_until_session_gate(tmp_path: Path) -> None:
    """Literature phase with min_papers must not accept chat-only on the first turn."""
    from opentorus.agent.loop import AgentLoop
    from opentorus.config import default_config
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"

    class ChatOnlyProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            return ProviderResponse(
                kind="message",
                content="I'm ready — what would you like to work on?",
            )

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    loop = AgentLoop(
        tmp_path,
        ot,
        ChatOnlyProvider(),
        build_default_registry(tmp_path, ot, config),
        config,
        max_steps=8,
        deliverable_bootstrap=("paper_list", {}),
        session_gate=lambda: loop.tool_calls_this_run >= 1,
    )
    answer = loop.run("Literature survey — fetch papers.")
    assert loop.tool_calls_this_run >= 1
    assert loop.bootstrap_used
    assert "ready" in answer.lower() or answer


def test_compile_latex_report_calls_toolchain(tmp_path: Path) -> None:
    tex = tmp_path / "report.tex"
    tex.write_text(
        wrap_preprint_document(
            {"problem_id": "PROBLEM-0001", "title": "T", "status": "open", "tags": []},
            "\\section{Summary}\nTest.",
        ),
        encoding="utf-8",
    )
    pdf = tmp_path / "report.pdf"

    with patch(
        "opentorus.research.authoring.compile_latex_project",
        return_value=type("R", (), {"pdf_path": str(pdf)})(),
    ) as mocked:
        pdf.write_bytes(b"%PDF-fake")
        result = compile_latex_report(tex, pdf_path=pdf)

    mocked.assert_called_once()
    assert result == pdf


def test_llm_compose_fallback_to_template(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="X")

    class emptyProvider(BaseProvider):  # noqa: N801
        @property
        def name(self) -> str:
            return "ollama"  # usable model that returns empty → falls to template structure

        def generate(self, messages, tools=None):
            return ProviderResponse(kind="message", content="")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    pdf = tmp_path / "out.pdf"
    with patch(
        "opentorus.research.dossier.pdf_export.compile_latex_report",
        side_effect=lambda tex_path, pdf_path=None: (
            (pdf_path or tex_path.with_suffix(".pdf")).write_bytes(b"%PDF")
            or (pdf_path or tex_path.with_suffix(".pdf"))
        ),
    ):
        from opentorus.research.dossier.pdf_export import compose_and_render_pdf

        compose_and_render_pdf(
            ot,
            "PROBLEM-0001",
            pdf_path=pdf,
            provider=emptyProvider(),
            compose_llm=True,
        )
    assert pdf.is_file()
    assert pdf.with_suffix(".tex").is_file()


def test_curly_punctuation_survives_latex_sanitization() -> None:
    """Curly apostrophes/quotes map to LaTeX-safe ASCII instead of being dropped.

    Regression: NFKD has no ASCII decomposition for ’, so the last-resort
    transliteration deleted it — "Stewart's bound" typeset as "Stewarts bound"."""
    from opentorus.research.dossier.pdf_export import sanitize_latex_body

    out = sanitize_latex_body("Stewart’s bound “as stated” … done")
    assert "Stewart's bound" in out
    assert "``as stated''" in out
    assert "..." in out
