"""Export a problem dossier as merged Markdown or PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store
from opentorus.research.dossier.report import build_report

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider
    from opentorus.research.dossier.pdf_export import ReportComposeHooks


@dataclass
class ProblemExportResult:
    problem_id: str
    markdown_path: Path
    pdf_path: Path | None = None
    tex_path: Path | None = None
    html_path: Path | None = None


def assemble_export_markdown(ot_dir: Path, problem_id: str, *, refresh_report: bool = True) -> str:
    """Merge report.md (includes full proof bodies) for export."""
    pid = problem_id.strip().upper()
    store.require_dossier(ot_dir, pid)
    if refresh_report:
        build_report(ot_dir, pid)

    dossier_dir = store.dossier_dir(ot_dir, pid)
    report_path = dossier_dir / "report.md"
    if not report_path.is_file():
        raise OpenTorusError(f"No report.md for {pid}. Run `opentorus problem report {pid}` first.")

    return report_path.read_text(encoding="utf-8").rstrip() + "\n"


def export_problem(
    ot_dir: Path,
    problem_id: str,
    *,
    out: Path | None = None,
    pdf: bool = False,
    refresh_report: bool = True,
    provider: BaseProvider | None = None,
    compose_llm: bool = True,
    hooks: ReportComposeHooks | None = None,
) -> ProblemExportResult:
    """Write merged Markdown (and optionally LLM-composed PDF) for a problem dossier."""
    pid = problem_id.strip().upper()
    dossier_dir = store.dossier_dir(ot_dir, pid)
    if hooks and hooks.on_progress:
        hooks.on_progress("Assembling report from artifacts…")
    markdown = assemble_export_markdown(ot_dir, pid, refresh_report=refresh_report)

    if out is None:
        md_path = dossier_dir / f"{pid}-full.md"
        pdf_path = dossier_dir / f"{pid}-full.pdf" if pdf else None
        tex_path = dossier_dir / f"{pid}-full.tex" if pdf else None
    elif pdf and out.suffix.lower() == ".pdf":
        pdf_path = out
        md_path = out.with_suffix(".md")
        tex_path = out.with_suffix(".tex")
    elif out.suffix.lower() in {".md", ".markdown"}:
        md_path = out
        pdf_path = out.with_suffix(".pdf") if pdf else None
        tex_path = out.with_suffix(".tex") if pdf else None
    else:
        md_path = out / f"{pid}-full.md" if out.is_dir() else out.with_suffix(".md")
        pdf_path = md_path.with_suffix(".pdf") if pdf else None
        tex_path = md_path.with_suffix(".tex") if pdf else None

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    written_pdf: Path | None = None
    written_tex: Path | None = None
    written_html: Path | None = None
    if pdf:
        from opentorus.research.dossier.pdf_export import compose_and_render_pdf, tex_available

        if not tex_available():
            # Graceful degradation: no LaTeX toolchain → emit a standalone HTML
            # rendering of the honest report instead of failing.
            from opentorus.research.dossier.html_export import markdown_to_html

            written_html = md_path.with_suffix(".html")
            written_html.write_text(
                markdown_to_html(markdown, title=f"{pid} — OpenTorus report"),
                encoding="utf-8",
            )
            if hooks and hooks.on_progress:
                hooks.on_progress(
                    f"No LaTeX engine on PATH; wrote HTML instead of PDF: {written_html}"
                )
        else:
            target = pdf_path or md_path.with_suffix(".pdf")
            tex_target = tex_path or md_path.with_suffix(".tex")
            try:
                compose_and_render_pdf(
                    ot_dir,
                    pid,
                    pdf_path=target,
                    tex_path=tex_target,
                    markdown_context=markdown,
                    provider=provider,
                    compose_llm=compose_llm,
                    hooks=hooks,
                )
                written_pdf = target
                written_tex = tex_target
            except OpenTorusError as exc:
                # Even the deterministic template LaTeX failed to compile → emit an
                # HTML rendering so the report is always produced, rather than
                # failing the export with no output.
                from opentorus.research.dossier.html_export import markdown_to_html

                written_html = md_path.with_suffix(".html")
                written_html.write_text(
                    markdown_to_html(markdown, title=f"{pid} — OpenTorus report"),
                    encoding="utf-8",
                )
                if tex_target.exists():
                    written_tex = tex_target
                if hooks and hooks.on_progress:
                    hooks.on_progress(
                        f"PDF compile failed ({exc}); wrote HTML instead: {written_html}"
                    )

    return ProblemExportResult(
        problem_id=pid,
        markdown_path=md_path,
        pdf_path=written_pdf,
        tex_path=written_tex,
        html_path=written_html,
    )
