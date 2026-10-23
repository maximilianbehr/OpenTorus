"""Streamed output never shows the <memory_citations> bookkeeping block.

The loop strips the block from the stored answer, but streamed chunks reach the
terminal first (found in a live vLLM run), so the printer must suppress it too,
across chunk boundaries, without touching fenced code.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from opentorus.ux import StreamPrinter

TEXT = (
    "Answer line\n<memory_citations>\nOBS-0001 | used\nDEC-0001 | also\n"
    "</memory_citations>\nAfter\nInline <memory_citations>X | y</memory_citations> tail\n"
    "```\n<memory_citations>kept in code</memory_citations>\n```\n"
)


@pytest.mark.parametrize("chunk", [1, 7, 1000])
def test_citation_block_is_not_streamed(chunk: int) -> None:
    buf = StringIO()
    printer = StreamPrinter(Console(file=buf, width=200))
    for i in range(0, len(TEXT), chunk):
        printer(TEXT[i : i + chunk])
    printer.finish(TEXT)
    out = buf.getvalue()
    assert "OBS-0001" not in out and "X | y" not in out
    assert "Answer line" in out and "After" in out and "Inline" in out and "tail" in out
    assert "kept in code" in out  # fenced code is shown verbatim
