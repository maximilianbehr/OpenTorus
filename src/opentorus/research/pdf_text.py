"""PDF text extraction with OCR and vision-page rendering for scanned documents.

``pypdf`` only reads embedded text layers. Many books arrive as page images
(``/ProcSet [/ImageB]``) with no selectable text — extraction then looks empty
even though the PDF is readable on screen. ``pdftoppm`` renders page PNGs for
vision models; optional ``tesseract`` adds a local OCR fallback.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

from opentorus.errors import OpenTorusError

# Trailing pages are often bibliography / index in large textbooks.
DEFAULT_SKIP_TRAILING_PAGES = 50
DEFAULT_VISION_BATCH_SIZE = 4
# Below this page count we treat the PDF as a paper/preprint, not a textbook.
_SHORT_PDF_PAGE_THRESHOLD = 100


def effective_trailing_skip(
    num_pages: int,
    skip_trailing: int = DEFAULT_SKIP_TRAILING_PAGES,
) -> int:
    """Pages to skip at the end; scaled down for short PDFs (arXiv, workshop notes).

    A 380-page textbook may skip ~50 bibliography/index pages. A 57-page preprint
    should scan almost everything — the old fixed skip of 50 left only pages 1–7.
    """
    if num_pages <= 0:
        return 0
    if num_pages < _SHORT_PDF_PAGE_THRESHOLD:
        # ~5% tail, at most 5 pages (references), always leave ≥90% of the document.
        return min(5, max(0, num_pages // 20))
    if num_pages < 200:
        return min(skip_trailing, 25)
    return min(skip_trailing, max(0, num_pages // 4))


def pdftoppm_available() -> bool:
    return shutil.which("pdftoppm") is not None


def ocr_tools_available() -> bool:
    return pdftoppm_available() and shutil.which("tesseract") is not None


def pdf_page_count(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def extract_pdf_pages_pypdf(path: Path) -> list[str]:
    """Extract per-page text with ``pypdf`` (embedded text layer only)."""
    reader = PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages]


def extraction_char_count(pages: list[str]) -> int:
    return sum(len(page.strip()) for page in pages)


def is_usable_extraction(pages: list[str], *, min_chars: int = 100) -> bool:
    """True when extracted text is plausibly non-empty (not a scanned-only PDF)."""
    if not pages:
        return False
    total = extraction_char_count(pages)
    if total < min_chars:
        return False
    # Require some text on at least ~5% of pages for multi-page docs.
    if len(pages) >= 20:
        nonempty = sum(1 for page in pages if len(page.strip()) >= 20)
        if nonempty < max(1, len(pages) // 20):
            return False
    return True


def _render_pdf_png_files(
    path: Path,
    *,
    page_from: int,
    page_to: int,
    dpi: int,
    tmp_path: Path,
) -> list[Path]:
    prefix = tmp_path / "page"
    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(dpi),
        "-f",
        str(page_from),
        "-l",
        str(page_to),
        str(path),
        str(prefix),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "pdftoppm failed").strip()
        raise OpenTorusError(f"Failed to render PDF pages as PNG: {detail}")
    images = sorted(tmp_path.glob("page-*.png"))
    if not images:
        raise OpenTorusError("PDF page rendering produced no PNG files.")
    return images


def render_pdf_pages_base64(
    path: Path,
    *,
    page_from: int = 1,
    page_to: int | None = None,
    dpi: int = 150,
) -> list[tuple[int, str]]:
    """Render PDF pages to base64 PNG strings for vision models."""
    if not pdftoppm_available():
        raise OpenTorusError(
            "Page rendering requires 'pdftoppm' (poppler) on PATH. On macOS: brew install poppler"
        )

    total = pdf_page_count(path)
    start = max(1, page_from)
    end = min(page_to or total, total)
    if start > end:
        raise OpenTorusError(f"Invalid page range: {start}–{end} (document has {total} pages).")

    rendered: list[tuple[int, str]] = []
    with tempfile.TemporaryDirectory(prefix="opentorus-pdfpng-") as tmp:
        images = _render_pdf_png_files(
            path, page_from=start, page_to=end, dpi=dpi, tmp_path=Path(tmp)
        )
        for index, image in enumerate(images):
            page_no = start + index
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            rendered.append((page_no, encoded))
    return rendered


def extract_pdf_pages_ocr(
    path: Path,
    *,
    page_from: int = 1,
    page_to: int | None = None,
    dpi: int = 200,
) -> list[str]:
    """OCR a PDF page range via ``pdftoppm`` + ``tesseract``."""
    if not ocr_tools_available():
        raise OpenTorusError(
            "OCR requires 'pdftoppm' (poppler) and 'tesseract' on PATH. "
            "On macOS: brew install poppler tesseract"
        )

    total = pdf_page_count(path)
    start = max(1, page_from)
    end = min(page_to or total, total)
    if start > end:
        raise OpenTorusError(f"Invalid page range: {start}–{end} (document has {total} pages).")

    pages: list[str] = []
    with tempfile.TemporaryDirectory(prefix="opentorus-ocr-") as tmp:
        images = _render_pdf_png_files(
            path,
            page_from=start,
            page_to=end,
            dpi=dpi,
            tmp_path=Path(tmp),
        )

        for image in images:
            ocr = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", "eng"],
                capture_output=True,
                text=True,
                check=False,
            )
            if ocr.returncode != 0:
                detail = (ocr.stderr or ocr.stdout or "tesseract failed").strip()
                raise OpenTorusError(f"OCR failed on {image.name}: {detail}")
            pages.append(ocr.stdout or "")

    return pages


def book_page_batches(
    num_pages: int,
    *,
    batch_size: int = DEFAULT_VISION_BATCH_SIZE,
    skip_trailing: int = DEFAULT_SKIP_TRAILING_PAGES,
    page_from: int | None = None,
    page_to: int | None = None,
) -> list[tuple[int, int]]:
    """Split a book into consecutive page batches for vision scanning.

    By default scans from page 1 through ``num_pages - skip_trailing`` (skipping
    bibliography/index at the very end). Textbook problems often appear at the
    end of each chapter, so the full main matter is walked in order.
    """
    if num_pages <= 0:
        return [(1, 1)]
    start = page_from if page_from is not None else 1
    tail_skip = effective_trailing_skip(num_pages, skip_trailing)
    end = page_to if page_to is not None else max(1, num_pages - tail_skip)
    start = max(1, min(start, num_pages))
    end = max(start, min(end, num_pages))
    size = max(1, batch_size)
    batches: list[tuple[int, int]] = []
    page = start
    while page <= end:
        batch_end = min(page + size - 1, end)
        batches.append((page, batch_end))
        page = batch_end + 1
    return batches


def tail_page_range(
    num_pages: int,
    tail: int = 60,
    *,
    skip_trailing: int = DEFAULT_SKIP_TRAILING_PAGES,
) -> tuple[int, int]:
    """Return (first, last) 1-based pages for a trailing main-content window."""
    if num_pages <= 0:
        return 1, 1
    content_end = max(1, num_pages - effective_trailing_skip(num_pages, skip_trailing))
    first = max(1, content_end - tail + 1)
    return first, content_end


def extract_pdf_pages(
    path: Path,
    *,
    ocr: bool = False,
    page_from: int | None = None,
    page_to: int | None = None,
) -> tuple[list[str], str]:
    """Extract PDF text; return ``(pages, method)`` where method is ``pypdf`` or ``ocr``."""
    if ocr:
        start = page_from or 1
        end = page_to
        pages = extract_pdf_pages_ocr(path, page_from=start, page_to=end)
        return pages, "ocr"

    pages = extract_pdf_pages_pypdf(path)
    if is_usable_extraction(pages):
        return pages, "pypdf"
    return pages, "pypdf-empty"


def extract_pdf_text_from_pages(pages: list[str]) -> str:
    return "\n".join(pages)
