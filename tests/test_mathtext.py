"""Tests for LaTeX→Unicode math rendering and the StreamPrinter integration."""

from __future__ import annotations

from opentorus.mathtext import render_math, render_math_line
from opentorus.ux import StreamPrinter


def test_inline_math_basic() -> None:
    assert render_math_line(r"If $\gcd(a, n) = 1$ then") == "If gcd(a, n) = 1 then"


def test_display_math_superscript_and_pmod() -> None:
    out = render_math_line(r"$$a^{\phi(n)} \equiv 1 \pmod{n}$$")
    assert out == "a^(φ(n)) ≡ 1 (mod n)"


def test_blackboard_and_starred_group() -> None:
    assert render_math_line(r"$(\mathbb{Z}/n\mathbb{Z})^*$") == "(ℤ/nℤ)^*"


def test_simple_super_and_subscripts() -> None:
    assert render_math_line(r"$a^2 + b_1 = c^{n+1}$") == "a² + b₁ = cⁿ⁺¹"


def test_set_notation_braces_preserved() -> None:
    out = render_math_line(r"the set $\{x \in \{1, \dots, n\}\}$.")
    assert out == "the set {x ∈ {1, …, n}}."


def test_prose_with_underscores_is_untouched() -> None:
    line = "A sentence with snake_case and a_variable and x^y outside math."
    assert render_math_line(line) == line


def test_inline_code_is_preserved() -> None:
    line = r"use `x_1 = a^2` and then $a^2$"
    assert render_math_line(line) == "use `x_1 = a^2` and then a²"


def test_fenced_code_block_is_preserved() -> None:
    text = "Math $a^2$ here\n```\nx_1 = a^2\n```\nand $b_1$"
    out = render_math(text)
    lines = out.split("\n")
    assert lines[0] == "Math a² here"
    assert lines[2] == "x_1 = a^2"  # untouched inside the fence
    assert lines[4] == "and b₁"


def test_unknown_command_drops_backslash() -> None:
    assert render_math_line(r"$\foo x$") == "foo x"


class _FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text: str = "", **_: object) -> None:
        self.lines.append(text)


def test_streamprinter_transforms_non_streamed_answer() -> None:
    console = _FakeConsole()
    printer = StreamPrinter(console, transform=render_math_line)
    printer.finish(r"Result: $a^2 \equiv 1 \pmod{n}$")
    assert console.lines == ["Result: a² ≡ 1 (mod n)"]


def test_streamprinter_preserves_fence_while_streaming() -> None:
    console = _FakeConsole()
    printer = StreamPrinter(console, transform=render_math_line)
    printer("Math $a^2$\n```\n")
    printer("code_x = a^2\n```\n")
    printer.finish("")
    assert console.lines == ["Math a²", "```", "code_x = a^2", "```"]
