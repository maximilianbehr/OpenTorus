"""Dependency-free Markdown → standalone HTML for the dossier report.

Used as a graceful fallback when no LaTeX toolchain (or no model) is available: a
reader still gets a clean, self-contained HTML rendering of the honest report
instead of an error. The converter is intentionally small (headings, lists, fenced
code, blockquotes, tables, bold/inline-code, paragraphs) — enough for the report's
structure, with no third-party dependency.

The page is styled from :mod:`opentorus.research.dossier.theme`, the same design
system the LaTeX class uses, so the HTML fallback reads as the same document as
the PDF rather than as a plain-text dump: accent sans headings with a hairline
rule, tinted output panels, artifact ids and gap markers, status chips whose
colour follows the same rule as the PDF's (green only where the artifacts license
it), and a metadata strip under the title.

Math is typeset client-side by MathJax (loaded from a CDN): ``$…$`` / ``\\(…\\)``
inline and ``$$…$$`` / ``\\[…\\]`` display spans render as typeset mathematics in
the browser. The MathJax library is the only external fetch; the report content
itself never leaves the machine, and the stylesheet is inlined rather than
fetched. With no network (or scripting disabled) the page degrades gracefully to
the raw ``$…$`` source text.
"""

from __future__ import annotations

import html
import re

from opentorus.research.dossier.theme import report_css, status_kind

_BOLD = re.compile(r"\*\*(.+?)\*\*")
#: ``_text_`` / ``*text*``. Both guard against intra-word matches, so
#: ``HEURISTIC_ONLY`` and ``experiment_proof`` stay literal.
_ITALIC_US = re.compile(r"(?<![\w\\])_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)")
_ITALIC_STAR = re.compile(r"(?<![\w*\\])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^```(\w*)\s*$")
_HRULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
#: Opening delimiter of a display-math block that runs over several lines.
_DISPLAY_OPEN = re.compile(r"^\s*(\$\$|\\\[)\s*$")
#: Local artifact ids (CLAIM-0001, PAPER-0007, EXP-0001, ACTION-0048, KR-0002, …).
#: The prefix may be as short as two letters (``KR-`` for known results); the
#: 3-digit tail is what keeps ``[GAP-1]`` and prose like ``PAPER-*`` out.
_ARTIFACT = re.compile(r"\b([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3,})\b")
#: Gap markers inside proof sketches.
_GAP = re.compile(r"\[(GAP-\d+)\]")
#: ``**Status:** open — …`` lines, whose status token becomes a chip.
_STATUS_LINE = re.compile(r"(<strong>Status:</strong>)\s*([A-Za-z][A-Za-z0-9_]*)")
#: A ``$…$`` / ``$$…$$`` span, left untouched so MathJax sees its original source.
_MATH_SPAN = re.compile(r"\$\$[\s\S]*?\$\$|\$[^$\n]+\$")

# Client-side math typesetting. inlineMath enables single ``$`` (off by default in
# MathJax v3); processEscapes keeps ``\$`` a literal dollar; code/pre are skipped
# so verbatim spans are left untouched.
_MATHJAX = (
    "<script>\n"
    "MathJax = {\n"
    "  tex: {\n"
    "    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],\n"
    "    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],\n"
    "    processEscapes: true\n"
    "  },\n"
    "  options: {skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']}\n"
    "};\n"
    "</script>\n"
    '<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>\n'
)


def _decorate(text: str) -> str:
    """Artifact ids, gap markers and status tokens → their styled spans.

    The PDF gets these from ``\\artifact`` / ``\\gapmarker`` / ``\\status*``; here
    they are recovered from the Markdown so both renderings mark up the same
    things.
    """
    text = _GAP.sub(r'<span class="gapmarker">[\1]</span>', text)
    text = _ARTIFACT.sub(r'<span class="artifact">\1</span>', text)

    def chip(match: re.Match[str]) -> str:
        token = match.group(2)
        return f'{match.group(1)} <span class="chip chip-{status_kind(token)}">{token}</span>'

    return _STATUS_LINE.sub(chip, text)


def _inline(text: str) -> str:
    """Escape HTML, apply inline bold / code spans, then decorate artifacts.

    Math spans are copied through verbatim: MathJax needs the original ``$…$``
    source, and an id-looking token inside a formula is notation, not an artifact.
    """
    out: list[str] = []
    last = 0
    for match in _MATH_SPAN.finditer(text):
        out.append(_decorate(_inline_plain(text[last : match.start()])))
        out.append(html.escape(match.group(0)))
        last = match.end()
    out.append(_decorate(_inline_plain(text[last:])))
    return "".join(out)


def _inline_plain(text: str) -> str:
    out = html.escape(text)
    out = _INLINE_CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC_US.sub(r"<em>\1</em>", out)
    return _ITALIC_STAR.sub(r"<em>\1</em>", out)


def _starts_block(line: str) -> bool:
    """True when *line* opens a new block, so it cannot continue a paragraph."""
    if not line.strip():
        return True
    return bool(
        _HEADING.match(line)
        or _BULLET.match(line)
        or _ORDERED.match(line)
        or _FENCE.match(line)
        or _HRULE.match(line)
        or _DISPLAY_OPEN.match(line)
        or line.startswith(">")
        or line.lstrip().startswith("|")
    )


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_divider(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def markdown_to_html(
    markdown: str,
    *,
    title: str = "OpenTorus report",
    meta: list[tuple[str, str]] | None = None,
    footer: str = "",
) -> str:
    """Render a Markdown subset to a standalone, self-contained HTML document.

    ``meta`` is the metadata strip printed under the title — the same
    (label, value) pairs the PDF shows in ``\\otdossierpanel``. ``footer`` is the
    left-hand footer note, mirroring the PDF's running foot.
    """
    lines = markdown.splitlines()
    body: list[str] = []
    i = 0
    list_env: str | None = None

    def close_list() -> None:
        nonlocal list_env
        if list_env is not None:
            body.append(f"</{list_env}>")
            list_env = None

    def open_list(env: str) -> None:
        nonlocal list_env
        if list_env != env:
            close_list()
            body.append(f"<{env}>")
            list_env = env

    def gather_continuation(first: str) -> str:
        """Join a block's soft-wrapped continuation lines into one run of text.

        Markdown wraps prose at the source margin; without this every wrapped line
        became its own ``<p>``, so the HTML read as a column of fragments while the
        PDF flowed the same text into paragraphs.
        """
        nonlocal i
        parts = [first.strip()]
        while i + 1 < len(lines) and not _starts_block(lines[i + 1]):
            i += 1
            parts.append(lines[i].strip())
        return " ".join(p for p in parts if p)

    while i < len(lines):
        line = lines[i]
        # Display math spanning several lines. It must reach the browser as one
        # contiguous span or MathJax never matches the delimiters and the reader
        # sees raw "$$ \lVert p(A) …" source.
        if _DISPLAY_OPEN.match(line):
            close_list()
            opener = _DISPLAY_OPEN.match(line).group(1)  # type: ignore[union-attr]
            closer = "$$" if opener == "$$" else "\\]"
            math: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != closer:
                math.append(lines[i])
                i += 1
            i += 1  # skip the closing delimiter
            inner = html.escape("\n".join(math).strip())
            body.append(f'<p class="ot-display">{opener}\n{inner}\n{closer}</p>')
            continue
        # fenced code block (``` or ```lang) — rendered verbatim.
        fence = _FENCE.match(line)
        if fence:
            close_list()
            lang = fence.group(1)
            code: list[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code.append(html.escape(lines[i]))
                i += 1
            i += 1  # skip closing fence
            cls = f' class="language-{lang}"' if lang else ""
            body.append(f"<pre><code{cls}>" + "\n".join(code) + "</code></pre>")
            continue
        # pipe table: a header row followed by a |---|---| divider.
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _is_table_divider(lines[i + 1]):
            close_list()
            head = _split_row(line)
            body.append("<table>\n<thead><tr>")
            body.extend(f"<th>{_inline(c)}</th>" for c in head)
            body.append("</tr></thead>\n<tbody>")
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                body.append("<tr>")
                body.extend(f"<td>{_inline(c)}</td>" for c in _split_row(lines[i]))
                body.append("</tr>")
                i += 1
            body.append("</tbody>\n</table>")
            continue
        heading = _HEADING.match(line)
        if heading:
            close_list()
            level = len(heading.group(1))
            body.append(f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue
        if _HRULE.match(line):
            close_list()
            body.append("<hr>")
            i += 1
            continue
        bullet = _BULLET.match(line)
        if bullet:
            open_list("ul")
            body.append(f"<li>{_inline(gather_continuation(bullet.group(1)))}</li>")
            i += 1
            continue
        # Numbered steps used to render as separate paragraphs, losing the list.
        ordered = _ORDERED.match(line)
        if ordered:
            open_list("ol")
            body.append(f"<li>{_inline(gather_continuation(ordered.group(1)))}</li>")
            i += 1
            continue
        if line.startswith(">"):
            close_list()
            quote = gather_continuation(line.lstrip("> "))
            body.append(f"<blockquote>{_inline(quote)}</blockquote>")
            i += 1
            continue
        if line.strip() == "":
            close_list()
            i += 1
            continue
        close_list()
        body.append(f"<p>{_inline(gather_continuation(line))}</p>")
        i += 1
    close_list()

    if meta:
        cells = "".join(
            f'<div><span class="ot-meta-label">{html.escape(label)}</span>{value}</div>'
            for label, value in meta
        )
        panel = f'<div class="ot-panel">{cells}</div>'
        # Directly under the title, as \otdossierpanel sits under \maketitle.
        after_title = next(
            (n for n, el in enumerate(body) if el.startswith("<h1")),
            -1,
        )
        body.insert(after_title + 1, panel)

    if footer:
        body.append(
            f'<footer class="ot-foot"><span>{html.escape(footer)}</span><span></span></footer>'
        )

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>\n{report_css()}</style>\n"
        f"{_MATHJAX}"
        "</head>\n<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )
