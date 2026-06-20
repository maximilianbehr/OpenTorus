"""Tests for Markdown → PDF Unicode preprocessing."""

from __future__ import annotations

from opentorus.research.markdown_latex import prepare_markdown_for_pdf


def test_unicode_norm_and_inequality() -> None:
    text = "Bound ≤ (1+ε) · min norm with Ω injection."
    out = prepare_markdown_for_pdf(text)
    assert r"\leq" in out
    assert r"\varepsilon" in out or r"\epsilon" in out
    assert r"\Omega" in out
    assert "≤" not in out
    assert "Ω" not in out


def test_frobenius_norm_and_tilde() -> None:
    text = "Error ‖A X̃ − B‖_F is small."
    out = prepare_markdown_for_pdf(text)
    assert r"\|" in out
    assert r"\tilde{X}" in out
    assert "‖" not in out


def test_preserves_fenced_code() -> None:
    text = "Use `Ω` in code.\n\n```python\nx = 1\n```\n"
    out = prepare_markdown_for_pdf(text)
    assert "```python\nx = 1\n```" in out
    assert "`Ω`" in out


def test_existing_dollar_math_unchanged() -> None:
    text = r"Already $\Omega^{\top} A$ is fine."
    out = prepare_markdown_for_pdf(text)
    assert r"$\Omega^{\top} A$" in out


def test_ascii_exponent_not_split() -> None:
    text = "Problem 5.1 (Sketch-and-solve). Let A in R^{n x d} full rank."
    out = prepare_markdown_for_pdf(text)
    assert "$(Sketch-and-solve)$" not in out
    assert "$R^{n x d}$" in out
    assert "R^${" not in out


def test_latex_commands_wrapped() -> None:
    text = r"Use \in and \times with \leq bound."
    out = prepare_markdown_for_pdf(text)
    assert r"$\in$" in out
    assert r"$\times$" in out
    assert r"$\leq$" in out


def test_latex_paren_math_normalized() -> None:
    text = r"subset \(\mathcal{I}\) and display \[\|x\|_{*}\]"
    out = prepare_markdown_for_pdf(text)
    assert r"$\mathcal{I}$" in out
    assert r"\(\mathcal{I}\)" not in out
    assert "$$" in out
    assert r"\|x\|_{*}" in out


def test_em_dash_not_wrapped_as_math() -> None:
    text = "Problem 1 — 4.1.5 Inverses of Laplacians"
    out = prepare_markdown_for_pdf(text)
    assert "$---$" not in out
    assert "---" in out or "—" in out
