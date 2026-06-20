"""Dependency-free Markdown → standalone HTML for the dossier report.

Used as a graceful fallback when no LaTeX toolchain is installed: a reader still
gets a clean, self-contained HTML rendering of the honest report instead of an
error. The converter is intentionally small (headings, lists, fenced code,
blockquotes, bold/inline-code, paragraphs) — enough for the report's structure,
with no third-party dependency.

Math is typeset client-side by MathJax (loaded from a CDN): ``$…$`` / ``\\(…\\)``
inline and ``$$…$$`` / ``\\[…\\]`` display spans render as typeset mathematics in
the browser. The MathJax library is the only external fetch; the report content
itself never leaves the machine. With no network (or scripting disabled) the page
degrades gracefully to the raw ``$…$`` source text.
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE = re.compile(r"`([^`]+)`")

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


def _inline(text: str) -> str:
    """Escape HTML then apply inline bold / code spans."""
    out = html.escape(text)
    out = _INLINE_CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    return out


def markdown_to_html(markdown: str, *, title: str = "OpenTorus report") -> str:
    """Render a Markdown subset to a standalone, self-contained HTML document."""
    lines = markdown.splitlines()
    body: list[str] = []
    i = 0
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        # fenced code block (``` or ```lang) — rendered verbatim.
        fence = re.match(r"^```(\w*)\s*$", line)
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
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            body.append(f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(bullet.group(1).strip())}</li>")
            i += 1
            continue
        if line.startswith(">"):
            close_list()
            body.append(f"<blockquote>{_inline(line.lstrip('> ').strip())}</blockquote>")
            i += 1
            continue
        if line.strip() == "":
            close_list()
            i += 1
            continue
        close_list()
        body.append(f"<p>{_inline(line.strip())}</p>")
        i += 1
    close_list()

    style = (
        "body{max-width:50rem;margin:2rem auto;padding:0 1rem;"
        "font-family:system-ui,sans-serif;line-height:1.5}"
        "code{background:#f4f4f4;padding:.1em .3em;border-radius:3px}"
        "pre{background:#f4f4f4;padding:1rem;overflow:auto;border-radius:5px}"
        "blockquote{border-left:3px solid #ccc;margin:0;padding-left:1rem;color:#555}"
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>{style}</style>\n"
        f"{_MATHJAX}"
        "</head>\n<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )
