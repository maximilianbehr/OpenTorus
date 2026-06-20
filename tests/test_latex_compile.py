"""Tests for LaTeX compilation helpers."""

from __future__ import annotations

from pathlib import Path

from opentorus.errors import OpenTorusError
from opentorus.research.authoring import compile_latex_project
from opentorus.tools.shell import ShellResult


def test_compile_latex_runs_bibtex_cycle(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "build"
    work.mkdir()
    (work / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Hi\end{document}",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_run(argv, cwd=None, timeout=180, label=None):
        name = label or argv[0]
        calls.append(name)
        if "latex" in name:
            (Path(cwd) / "main.aux").write_text(r"\bibdata{references}", encoding="utf-8")
            (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4")
        return ShellResult(command=name, stdout="", stderr="", exit_code=0)

    monkeypatch.setattr("opentorus.tools.shell.run_argv", fake_run)
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    result = compile_latex_project(work, "main")
    assert result.used_bibtex
    assert calls[0] == "pdflatex"
    assert calls[1] == "bibtex"
    assert calls[2] == "pdflatex"
    assert calls[3] == "pdflatex"
    assert (work / "build.log").is_file()


def test_compile_latex_skips_bibtex_without_citations(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "build"
    work.mkdir()
    (work / "main.tex").write_text(
        r"\documentclass{article}\begin{document}No citations here.\end{document}",
        encoding="utf-8",
    )
    (work / "references.bib").write_text("", encoding="utf-8")
    calls: list[str] = []

    def fake_run(argv, cwd=None, timeout=180, label=None):
        name = label or argv[0]
        calls.append(name)
        if "latex" in name:
            (Path(cwd) / "main.aux").write_text(r"\citation{}\newlabel{}{{}}", encoding="utf-8")
            (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4")
        return ShellResult(command=name, stdout="", stderr="", exit_code=0)

    monkeypatch.setattr("opentorus.tools.shell.run_argv", fake_run)
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    result = compile_latex_project(work, "main")
    assert not result.used_bibtex
    assert "bibtex" not in calls
    assert calls.count("pdflatex") == 3


def test_compile_latex_falls_back_when_engine_fmt_broken(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "build"
    work.mkdir()
    (work / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Hi\end{document}", encoding="utf-8"
    )
    calls: list[str] = []

    def fake_run(argv, cwd=None, timeout=180, label=None):
        name = label or Path(argv[0]).name
        calls.append(name)
        if name == "pdflatex":
            raise OpenTorusError("pdflatex failed (exit 1).\nFatal format file error; I'm stymied")
        if name.endswith("latex"):
            (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4")
        return ShellResult(command=name, stdout="", stderr="", exit_code=0)

    monkeypatch.setattr("opentorus.tools.shell.run_argv", fake_run)
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("pdflatex", "lualatex", "xelatex") else None,
    )
    result = compile_latex_project(work, "main")
    assert result.pdf_path.endswith("main.pdf")
    assert calls[0] == "pdflatex"
    assert "lualatex" in calls or "xelatex" in calls
