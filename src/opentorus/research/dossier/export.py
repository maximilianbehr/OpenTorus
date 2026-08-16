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
    # Why HTML was written instead of a PDF (None when a PDF was produced).
    # "no-engine" → no LaTeX toolchain on PATH; anything else is the actual
    # compile/honesty failure text, so the CLI can surface the real cause
    # instead of wrongly telling a user with TeX installed to install TeX.
    html_reason: str | None = None


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


def html_report_meta(ot_dir: Path, problem_id: str) -> list[tuple[str, str]]:
    """The metadata strip for the HTML report — the twin of ``\\otdossierpanel``.

    Same four fields, same counts and the same status-colour rule as the PDF, so
    the two renderings open with the same header rather than one of them starting
    cold on the first heading.
    """
    import html as _html

    from opentorus.research.dossier.pdf_export import artifact_counts, gather_dossier_facts
    from opentorus.research.dossier.theme import status_kind

    try:
        facts = gather_dossier_facts(ot_dir, problem_id)
    except OpenTorusError:  # a partial dossier still gets an (unadorned) report
        return []

    status = str(facts.get("status") or "unknown")
    counts = artifact_counts(facts)
    return [
        ("Dossier", f'<span class="artifact">{_html.escape(facts["problem_id"])}</span>'),
        ("Status", f'<span class="chip chip-{status_kind(status)}">{_html.escape(status)}</span>'),
        ("Formalization", _html.escape(str(facts.get("formalization") or "informal"))),
        ("Artifacts", _html.escape(counts)),
    ]


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
    allow_overclaims: bool = False,
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
    html_reason: str | None = None

    def _write_html() -> Path:
        """The HTML twin of the PDF: same design system, same metadata strip."""
        from opentorus.research.dossier.html_export import markdown_to_html

        path = md_path.with_suffix(".html")
        path.write_text(
            markdown_to_html(
                markdown,
                title=f"{pid} — OpenTorus report",
                meta=html_report_meta(ot_dir, pid),
                footer="OpenTorus investigation report",
            ),
            encoding="utf-8",
        )
        return path

    if pdf:
        from opentorus.research.dossier.pdf_export import compose_and_render_pdf, tex_available

        if not tex_available():
            # Graceful degradation: no LaTeX toolchain → emit a standalone HTML
            # rendering of the honest report instead of failing.
            written_html = _write_html()
            html_reason = "no-engine"
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
                    allow_overclaims=allow_overclaims,
                )
                written_pdf = target
                written_tex = tex_target
            except OpenTorusError as exc:
                # Even the deterministic template LaTeX failed to compile → emit an
                # HTML rendering so the report is always produced, rather than
                # failing the export with no output.
                written_html = _write_html()
                html_reason = str(exc)
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
        html_reason=html_reason,
    )
