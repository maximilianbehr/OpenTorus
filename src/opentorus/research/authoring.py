"""LaTeX compilation helpers for dossier PDF export and workspace .tex files."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from opentorus.errors import OpenTorusError

# Common Unicode math/Greek → inline math (used by markdown_latex).
UNICODE_MATH: dict[str, str] = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\epsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "±": r"\pm",
    "×": r"\times",
    "·": r"\cdot",
    "∞": r"\infty",
    "∈": r"\in",
    "⊂": r"\subset",
    "→": r"\to",
    "⇒": r"\Rightarrow",
}

_SUPERSCRIPT_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPT_DIGITS = str.maketrans(_SUPERSCRIPT_CHARS, "0123456789")

# Typographic Unicode → LaTeX text commands (outside math).
UNICODE_TEXT: dict[str, str] = {
    "—": "---",
    "–": "--",
    "…": "\\ldots{}",
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
}


class LatexBuildResult(BaseModel):
    pdf_path: str
    log_path: str
    used_bibtex: bool


_LATEX_ENGINE_ORDER = ("pdflatex", "lualatex", "xelatex")


def _available_latex_engines() -> list[tuple[str, str]]:
    """Return installed LaTeX engines in preferred order (pdfLaTeX first)."""
    import shutil

    engines: list[tuple[str, str]] = []
    for name in _LATEX_ENGINE_ORDER:
        path = shutil.which(name)
        if path:
            engines.append((name, path))
    return engines


def _looks_like_engine_failure(exc: OpenTorusError) -> bool:
    """True when the failure is the engine/binary, not the document source."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "format file error",
            "fatal format file",
            "made by different executable",
            "stymied",
        )
    )


def compile_latex_project(
    work_dir: Path,
    main_stem: str = "main",
    *,
    timeout_per_step: int = 180,
) -> LatexBuildResult:
    """Compile ``main_stem.tex`` to PDF using pdfLaTeX/XeLaTeX and optional bibtex.

    When ``references.bib`` exists beside the ``.tex`` file, runs the standard
    cycle: latex → bibtex → latex → latex. Without bibliography metadata in the
    ``.aux`` file, runs latex three times (enough for cross-references).

    Prefers pdfLaTeX (stable on most TeX Live installs). If an engine fails with
    a broken format file, tries the next available engine.
    """
    engines = _available_latex_engines()
    if not engines:
        raise OpenTorusError(
            "No LaTeX engine found on PATH (tried pdflatex, lualatex, xelatex). "
            "Install TeX Live or MacTeX, then retry."
        )

    last_error: OpenTorusError | None = None
    for engine_name, engine_path in engines:
        try:
            return _compile_latex_with_engine(
                work_dir,
                main_stem,
                engine_name=engine_name,
                engine_path=engine_path,
                timeout_per_step=timeout_per_step,
            )
        except OpenTorusError as exc:
            if len(engines) > 1 and _looks_like_engine_failure(exc):
                last_error = exc
                continue
            raise
    assert last_error is not None
    raise last_error


def _compile_latex_with_engine(
    work_dir: Path,
    main_stem: str,
    *,
    engine_name: str,
    engine_path: str,
    timeout_per_step: int,
) -> LatexBuildResult:
    """Run the full latex/bibtex cycle with one engine."""
    from opentorus.tools.shell import run_argv

    tex_file = work_dir / f"{main_stem}.tex"
    if not tex_file.is_file():
        raise OpenTorusError(f"No {main_stem}.tex in {work_dir}")

    latex_argv = [
        engine_path,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"{main_stem}.tex",
    ]
    log_parts: list[str] = []

    def _run(label: str, argv: list[str]) -> None:
        result = run_argv(argv, cwd=work_dir, timeout=timeout_per_step, label=label)
        log_parts.append(f"=== {label} (exit {result.exit_code}) ===\n")
        if result.stdout:
            log_parts.append(result.stdout[-8000:])
        if result.stderr:
            log_parts.append(result.stderr[-4000:])
        if result.exit_code != 0:
            tail = (result.stderr or result.stdout)[-2000:]
            raise OpenTorusError(f"{label} failed (exit {result.exit_code}).\n{tail}")

    def _needs_bibtex() -> bool:
        aux = work_dir / f"{main_stem}.aux"
        if not aux.is_file():
            return False
        text = aux.read_text(encoding="utf-8", errors="replace")
        return "\\bibdata" in text

    import shutil

    _run(engine_name, latex_argv)
    has_bib = _needs_bibtex()
    bibtex = shutil.which("bibtex") if has_bib else None
    if has_bib and bibtex is None:
        raise OpenTorusError(
            "Document uses bibliography but bibtex not on PATH. Install a full TeX distribution."
        )
    if has_bib:
        _run("bibtex", [bibtex, main_stem])  # type: ignore[list-item]
    _run(engine_name, latex_argv)
    _run(engine_name, latex_argv)

    pdf = work_dir / f"{main_stem}.pdf"
    if not pdf.is_file():
        raise OpenTorusError(f"PDF not produced: {pdf}")

    log_path = work_dir / "build.log"
    log_path.write_text("".join(log_parts), encoding="utf-8")
    return LatexBuildResult(
        pdf_path=str(pdf),
        log_path=str(log_path),
        used_bibtex=has_bib,
    )


def compile_workspace_tex(root: Path, tex_path: str) -> LatexBuildResult:
    """Compile a workspace ``.tex`` file (same directory as ``references.bib`` if any)."""
    from opentorus.paths import resolve_workspace_path

    target = resolve_workspace_path(root, tex_path)
    if target.suffix.lower() != ".tex":
        raise OpenTorusError(f"Expected a .tex file, got '{tex_path}'.")
    if not target.is_file():
        raise OpenTorusError(f"Not a file: {tex_path}")
    return compile_latex_project(target.parent, target.stem)
