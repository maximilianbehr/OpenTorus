"""Tests for LaTeX pre-validation and the HTML export fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.export import export_problem
from opentorus.research.dossier.html_export import markdown_to_html
from opentorus.research.dossier.pdf_export import (
    _gap_text,
    _proof_markdown_to_latex_fallback,
    latex_lint,
)
from opentorus.workspace import init_workspace, workspace_dir

# A proof body in the failure class that previously aborted pdflatex: bare Unicode
# math (∈, ×, ρ), super/subscripts outside math mode (C^{n×n}, W(m)=…), ``$$…$$``
# interleaved with prose, and ``\cdotN``-style command-eats-letter.
_MALFORMED_PROOF_BODY = (
    "## Definitions\n\n"
    "Let A∈C^{n×n} and b∈C^n. The total work is "
    "W(m)=C_{cycle}(m)$\\cdotN$_{cycles}(m,$$\\varepsilon$$), where "
    "C_{cycle}(m)$\\approxO$(m$\\cdotnnz$(A)). [GAP-1]\n\n"
    "- Error decays like ρ^{-m} per cycle and **dominates** for small m.\n"
)


def test_latex_lint_clean_document() -> None:
    doc = r"\documentclass{article}\begin{document}Hello $a+b$ and \[x^2\].\end{document}"
    assert latex_lint(doc) == []


def test_latex_lint_flags_bare_gap_marker() -> None:
    issues = latex_lint(r"\begin{document}see [GAP-3] here\end{document}")
    assert any("GAP-3" in i for i in issues)


def test_latex_lint_flags_unbalanced_math_and_envs() -> None:
    assert any("inline math" in i for i in latex_lint(r"text $a+b here"))
    assert any("display math" in i for i in latex_lint(r"open \[ x^2 only"))
    assert any("environment" in i for i in latex_lint(r"\begin{align} x \end{equation}"))


def test_latex_lint_ignores_escaped_dollar() -> None:
    assert latex_lint(r"a cost of \$5 and \$10") == []


def test_sanitize_preserves_inline_math_inside_text_commands() -> None:
    # Regression: inline math inside \textbf{...} must not have its $ delimiters
    # escaped to \$, which orphaned \neq outside math mode and aborted pdflatex.
    from opentorus.research.dossier.pdf_export import sanitize_latex_body

    out = sanitize_latex_body(r"\item \textbf{General Case ($A \neq 0$):}")
    assert r"\$" not in out  # math delimiters not escaped
    assert "$A \\neq 0$" in out  # math span preserved verbatim
    # In-math subscripts/superscripts inside bold survive too.
    assert "$x_i^2$" in sanitize_latex_body(r"\textbf{value $x_i^2$ here}")
    # A genuinely lone dollar is still escaped.
    assert r"\$5" in sanitize_latex_body(r"\textbf{costs $5 total}")


def test_markdown_to_html_renders_structure() -> None:
    md = "# Title\n\n- one\n- two\n\n```mermaid\ngraph LR\n```\n\n**bold** and `code`.\n"
    html = markdown_to_html(md, title="T")
    assert "<!doctype html>" in html
    assert "<h1>Title</h1>" in html
    assert "<li>one</li>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<pre><code" in html
    assert "<title>T</title>" in html


def test_export_falls_back_to_html_without_tex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: X.", domain="demo")
    claims.add_claim(base, d.id, claim_type="CONJECTURE", statement="X holds.")
    # Simulate no LaTeX toolchain installed.
    monkeypatch.setattr("opentorus.research.dossier.pdf_export.tex_available", lambda: False)
    result = export_problem(base, d.id, pdf=True, compose_llm=False)
    assert result.pdf_path is None
    assert result.html_path is not None and result.html_path.is_file()
    assert "<html" in result.html_path.read_text(encoding="utf-8")


def test_proof_fallback_preserves_intended_math() -> None:
    # The per-proof deterministic fallback preserves well-formed inline math.
    out = _proof_markdown_to_latex_fallback("The rate is $\\rho^{-m}$ per cycle.\n")
    assert "$\\rho^{-m}$" in out


def test_gap_text_renders_dict_and_string_gaps() -> None:
    assert _gap_text({"id": "GAP-1", "description": "close the bound"}) == "GAP-1: close the bound"
    assert _gap_text({"description": "no id here"}) == "no id here"
    assert _gap_text("plain gap label") == "plain gap label"


def test_markdown_to_html_embeds_mathjax_and_preserves_math() -> None:
    html = markdown_to_html("The rate $\\rho^{-m}$ and display $$\\int_0^1 f$$.\n", title="T")
    assert "mathjax@3" in html  # MathJax library is referenced
    assert "inlineMath" in html and "displayMath" in html  # configured for $…$ and $$…$$
    assert "$\\rho^{-m}$" in html  # inline math span survives into the document
    assert "$$\\int_0^1 f$$" in html  # display math span survives


def test_facts_to_latex_uses_llm_proofs_with_cache(tmp_path: Path) -> None:
    # Deterministic structure + per-proof LLM conversion: the proof body is the
    # model's clean LaTeX (not the raw Unicode-in-prose), and a shared cache means
    # the conversion runs once even across repeated renders.
    from opentorus.providers.base import BaseProvider, ProviderResponse
    from opentorus.research.dossier.pdf_export import facts_to_latex, gather_dossier_facts

    calls = {"n": 0}

    class StubProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "ollama"

        def generate(self, messages, tools=None):
            calls["n"] += 1
            return ProviderResponse(kind="message", content="$A\\in\\mathbb{C}^{n}$ as required.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: P.", domain="demo")
    claims.add_proof_attempt(base, d.id, title="Sketch", body=_MALFORMED_PROOF_BODY)

    facts = gather_dossier_facts(base, d.id)
    cache: dict[str, str] = {}
    prov = StubProvider()
    body = facts_to_latex(facts, provider=prov, proof_compose_llm=True, cache=cache)
    assert "$A\\in\\mathbb{C}^{n}$ as required." in body  # model LaTeX, not raw Unicode prose
    assert "A∈C^{n×n}" not in body  # raw Unicode-in-prose was replaced
    assert calls["n"] == 1 and cache  # converted once, cached
    facts_to_latex(facts, provider=prov, proof_compose_llm=True, cache=cache)
    assert calls["n"] == 1  # second render reuses the cache, no extra model call


def test_export_pdf_without_model_falls_back_to_html(tmp_path: Path) -> None:
    # PDF export requires a model to render mathematics; with --no-llm there is no
    # deterministic math PDF (it rendered math as literal text), so export emits the
    # MathJax HTML report instead of a math-broken PDF.
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: Z.", domain="demo")
    claims.add_proof_attempt(
        base, d.id, title="Sketch with bad math", body=_MALFORMED_PROOF_BODY, gaps=["GAP-1"]
    )
    result = export_problem(base, d.id, pdf=True, compose_llm=False)
    assert result.pdf_path is None  # no deterministic math PDF
    assert result.html_path is not None and result.html_path.is_file()
    assert "mathjax@3" in result.html_path.read_text(encoding="utf-8")


def test_export_falls_back_to_html_when_pdf_compile_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even with a LaTeX toolchain present, malformed model-authored math can abort
    # pdflatex (after both the model and deterministic LaTeX). Export must then emit
    # HTML instead of failing with no output.
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: Y.", domain="demo")
    claims.add_claim(base, d.id, claim_type="CONJECTURE", statement="Y holds.")
    monkeypatch.setattr("opentorus.research.dossier.pdf_export.tex_available", lambda: True)

    def _boom(*args, **kwargs):
        raise OpenTorusError("pdflatex failed")

    monkeypatch.setattr("opentorus.research.dossier.pdf_export.compose_and_render_pdf", _boom)
    result = export_problem(base, d.id, pdf=True, compose_llm=False)
    assert result.pdf_path is None
    assert result.html_path is not None and result.html_path.is_file()
