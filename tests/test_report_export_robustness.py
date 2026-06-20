"""Tests for LaTeX pre-validation and the HTML export fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.export import export_problem
from opentorus.research.dossier.html_export import markdown_to_html
from opentorus.research.dossier.pdf_export import latex_lint
from opentorus.workspace import init_workspace, workspace_dir


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
