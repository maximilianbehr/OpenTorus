"""Tests for LaTeX preprint PDF export."""

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
    preprint_cls_source,
    sanitize_latex_body,
    wrap_preprint_document,
)
from opentorus.workspace import init_workspace, workspace_dir


def test_sanitize_latex_body_wraps_bare_gap_markers() -> None:
    raw = "Some text.\\\\\n[GAP-2] Missing link to lower bound."
    fixed = sanitize_latex_body(raw)
    assert r"\texttt{[GAP-2]}" in fixed


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


def test_preprint_cls_is_bundled() -> None:
    path = preprint_cls_source()
    assert path.is_file()
    assert path.name == "preprint.cls"


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
    assert "\\documentclass" in doc
    assert "preprint" in doc
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
    assert "\\usepackage{booktabs}" in doc
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
            return "mock"

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
