"""A minimal, real PDF for tests that must exercise the pypdf parsing path offline.

``papers.read_paper`` extracts text with pypdf; the theorem-reference tests bypass it
with a ``page_extractor`` and ``b"%PDF"`` bytes. The librarian parses registered PDFs
itself, so its tests need bytes pypdf can actually read: one page, Helvetica, one text
line per entry — hand-assembled so no PDF library is needed to *write* it.
"""

from __future__ import annotations

from pathlib import Path

PAPER_LINES = [
    "1 Introduction",
    "We study finite groups. By Theorem 2.1 we get the bound.",
    "2 Main results",
    "Theorem 2.1 (Main theorem). Let G be a finite group of order n.",
    "Then every element of G has order dividing n.",
    "Lemma 2.2. Suppose H is a subgroup of G. Then |H| divides |G|.",
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def minimal_pdf(lines: list[str]) -> bytes:
    """A one-page PDF whose extracted text is ``lines`` joined by newlines."""
    content = (
        "BT /F1 11 Tf 72 740 Td 14 TL "
        + " ".join(f"({_escape(line)}) Tj T*" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref_at = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    return out.encode("latin-1")


def register_unparsed_paper(ot_dir: Path, lines: list[str] | None = None) -> str:
    """A registered paper with a real (pypdf-readable) local PDF and no parse artifacts
    -- the state a driver's ``paper add`` leaves when parsing did not happen. Returns
    the paper id."""
    from opentorus.research.papers import acquire_paper, is_paper_parsed, papers_dir
    from opentorus.research.sources.base import SourceRecord

    text = list(lines or PAPER_LINES)
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot_dir, record, downloader=lambda _url: minimal_pdf(text))
    for name in ("structure.json", "text.txt", "note.json"):
        (papers_dir(ot_dir) / paper.id / name).unlink(missing_ok=True)
    assert paper.local_path and not is_paper_parsed(ot_dir, paper)
    return paper.id


__all__ = ["PAPER_LINES", "minimal_pdf", "register_unparsed_paper"]
