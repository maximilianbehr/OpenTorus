"""Extract open problems from papers or markdown into PROBLEM-* dossiers.

Workshop papers, surveys, and notes often list numbered open problems. This module
finds them (heuristics, LLM, or vision) and registers each as a full dossier under
``.opentorus/problems/PROBLEM-XXXX/``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from opentorus.errors import OpenTorusError

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider
    from opentorus.research.dossier.models import ProblemDossier

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def split_markdown_problems(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into ``(title, statement)`` problems, one per top-level heading.

    Deterministic and LLM-free (the opposite of the model-driven extractor): each
    heading at the *shallowest* level present starts a new problem; its text is the
    title and everything up to the next such heading is the statement. This gives a
    predictable 1:1 mapping from authored ``# Problem`` sections to dossiers. Returns
    ``[]`` when the file has no headings.
    """
    lines = markdown.splitlines()
    levels = [len(m.group(1)) for line in lines if (m := _HEADING.match(line))]
    if not levels:
        return []
    top = min(levels)
    sections: list[tuple[str, list[str]]] = []
    title: str | None = None
    body: list[str] = []
    for line in lines:
        m = _HEADING.match(line)
        if m and len(m.group(1)) == top:
            if title is not None:
                sections.append((title, body))
            title, body = m.group(2).strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        sections.append((title, body))
    out: list[tuple[str, str]] = []
    for t, b in sections:
        text = "\n".join(b).strip()
        statement = f"{t}\n\n{text}".strip() if text else t
        out.append((t, statement))
    return out


ExtractionMethod = Literal["vision", "llm", "heuristic", "none"]

# Explicit problem labels: "Problem 3.1.", "Problem 5.1(Title).", "Open Question 4.2:"
# The label is numeric ("3.1", "12") or an alphanumeric tag that CONTAINS a digit
# ("A1", "B2.3"). A bare letter is intentionally *not* allowed: it would match prose
# like "Question s of…" / "Problem of…" / "Problem for…", producing junk labels.
_LABEL = r"\d+(?:\.\d+)+|\d+|[A-Za-z]+\d+(?:\.\d+)*"
_EXPLICIT_PATTERNS = (
    re.compile(
        r"^(?:Problem|Open\s+[Pp]roblem|Open\s+[Qq]uestion|Research\s+[Pp]roblem|"
        r"Conjecture|Question|Exercise)\s*"
        rf"(?P<label>{_LABEL})\s*"
        r"\([^)]+\)\.\s*"
        r"(?P<body>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:Problem|Open\s+[Pp]roblem|Open\s+[Qq]uestion|Research\s+[Pp]roblem|"
        r"Conjecture|Question|Exercise)\s*"
        rf"(?P<label>{_LABEL})\s*[.:)\-–—]?\s*(?P<body>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<label>[\d]+(?:\.[\d]+)*)\s*[.)]\s+(?P<body>.{15,})$",
    ),
    re.compile(
        r"^\((?P<label>[\d]+(?:\.[\d]+)*)\)\s+(?P<body>.{15,})$",
    ),
)

# Section titles that signal an open-problems block (books, surveys, appendices).
_OPEN_SECTION = re.compile(
    r"(?:^#+\s*)?(?:\d+(?:\.\d+)+\s+)?"
    r"(?:Open\s+(?:Problems|Questions)|Research\s+Problems|Unsolved\s+Problems|"
    r"Problems?\s+and\s+(?:Conjectures|Open\s+Questions)|"
    r"Exercises?\s+and\s+(?:Open\s+)?Problems|Outstanding\s+Problems|"
    r"Some\s+Open\s+Problems)\b",
    re.IGNORECASE,
)

# In an open-problems section, also accept bare numbered items.
_RELAXED_NUMBERED = re.compile(
    r"^(?P<label>[\d]+(?:\.[\d]+)*)\s*[.)]\s+(?P<body>.{10,})$",
)

_SECTION_BREAK = re.compile(r"^(?:#+\s*)?(?:\d+(?:\.\d+)+\.?\s+)?[A-Z][A-Za-z0-9 \-/:]{2,60}\s*$")

_LLM_KEYWORD = re.compile(
    r"open\s+problem|research\s+problem|unsolved|conjecture|open\s+question",
    re.IGNORECASE,
)

_LLM_MAX_CHARS = 60_000
_VISION_BATCH_SIZE = 4
_VISION_DPI = 150

# Workshop/survey papers: ``Problem 2.1``, ``Problem 5.1(Title).…``
_PROBLEM_HEADER = re.compile(r"^Problem\s+(?P<label>\d+(?:\.\d+)*)\b", re.IGNORECASE | re.MULTILINE)
# Markdown workshop notes: ``## 4.1.5 …`` followed by ``### Problem``
_MD_PROBLEM_HEADING = re.compile(
    r"^(#{1,4})\s+(?:Problem|Open\s+Problem|Research\s+Problem|Conjecture)\s*$",
    re.IGNORECASE,
)
_MD_NUMBERED_SECTION = re.compile(r"^(#{1,6})\s+(?:([\d]+(?:\.[\d]+)+)\s+)?(.+)$")


@dataclass(frozen=True)
class ExtractionOutcome:
    problems: list[ProblemDossier]
    method: ExtractionMethod


def _label_tag(label: str) -> str:
    return f"label:{label.strip()}"


def _source_tag(source: str) -> str:
    return f"source:{source}"


def _dossier_tags(
    *,
    paper_id: str | None = None,
    label: str = "",
    source: str | None = None,
) -> list[str]:
    tags: list[str] = []
    if paper_id:
        tags.append(paper_id)
    if label.strip():
        tags.append(_label_tag(label))
    if source:
        tags.append(_source_tag(source))
    return tags


def _source_ref(*, paper_id: str | None = None, source: str | None = None) -> str:
    if paper_id:
        return paper_id
    if source:
        return source
    return "extracted"


def _format_dossier_statement(
    label: str,
    section: str | None,
    source_ref: str,
    body: str,
) -> str:
    parts: list[str] = []
    if label.strip():
        parts.append(f"Problem {label.strip()}")
    if section:
        parts.append(section.strip())
    header = " — ".join(parts) if parts else "Extracted problem"
    return f"{header} ({source_ref}):\n\n{body.strip()}"


def _is_open_section_header(line: str) -> bool:
    stripped = line.strip()
    if _match_problem_line(stripped, relaxed=False):
        return False
    return bool(_OPEN_SECTION.search(stripped))


def _match_problem_line(line: str, *, relaxed: bool) -> tuple[str, str] | None:
    for pattern in _EXPLICIT_PATTERNS:
        match = pattern.match(line)
        if match:
            body = match.group("body").strip()
            if len(body) >= 10:
                return match.group("label"), body
    if relaxed:
        match = _RELAXED_NUMBERED.match(line)
        if match:
            body = match.group("body").strip()
            if len(body) >= 10:
                return match.group("label"), body
    return None


def _looks_like_section_break(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if _is_open_section_header(stripped):
        return True
    if _SECTION_BREAK.match(stripped) and not _match_problem_line(stripped, relaxed=False):
        return True
    return False


def _collect_body(lines: list[str], start: int, first_body: str) -> tuple[str, int]:
    body = first_body
    j = start + 1
    while j < len(lines):
        nxt = lines[j].strip()
        if not nxt:
            if j + 1 < len(lines) and _match_problem_line(lines[j + 1].strip(), relaxed=False):
                break
            j += 1
            continue
        if _match_problem_line(nxt, relaxed=False) or _looks_like_section_break(nxt):
            break
        body = f"{body} {nxt}".strip()
        j += 1
    return body, j


def extract_labeled_problem_block(text: str, label: str) -> str | None:
    """Return the full ``Problem {label}…`` block from extracted paper text."""
    if not label.strip():
        return None
    lines = text.splitlines()
    header_re = re.compile(rf"^Problem\s+{re.escape(label.strip())}\b", re.IGNORECASE)
    start_idx: int | None = None
    for index, line in enumerate(lines):
        if header_re.match(line.strip()):
            start_idx = index
            break
    if start_idx is None:
        return None

    parts: list[str] = []
    index = start_idx
    while index < len(lines):
        stripped = lines[index].strip()
        if index > start_idx:
            if re.match(r"^(?:Problem|Open\s+[Qq]uestion)\s+[\d]", stripped, re.IGNORECASE):
                break
            if stripped.startswith("Likewise,"):
                break
        if stripped:
            parts.append(stripped)
        index += 1
    block = " ".join(parts)
    return block if len(block) >= 20 else None


def extract_markdown_workshop_problems(text: str) -> list[tuple[str, str, str | None]]:
    """Extract one problem per markdown ``### Problem`` block with section context.

    Workshop notes often use a numbered section (``## 4.1.5 Title``) for background
    and a bare ``### Problem`` heading for the actual question. Numbered sub-items
    (``1. … or 2. …``) are kept together as one statement — not split into separate
    dossiers.
    """
    lines = text.splitlines()
    found: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        heading = _MD_PROBLEM_HEADING.match(stripped)
        if not heading:
            index += 1
            continue

        problem_level = len(heading.group(1))
        parent_idx: int | None = None
        parent_label = ""
        parent_title = ""
        for back in range(index - 1, -1, -1):
            back_stripped = lines[back].strip()
            sec_match = _MD_NUMBERED_SECTION.match(back_stripped)
            if not sec_match:
                continue
            level = len(sec_match.group(1))
            if level < problem_level:
                parent_idx = back
                parent_label = (sec_match.group(2) or "").strip()
                parent_title = (sec_match.group(3) or "").strip()
                break

        start = parent_idx if parent_idx is not None else index
        body_lines: list[str] = []
        cursor = start
        while cursor < len(lines):
            line = lines[cursor]
            if cursor > index and line.strip().startswith("#"):
                level_match = re.match(r"^(#+)\s", line.strip())
                if level_match and len(level_match.group(1)) <= problem_level:
                    break
            body_lines.append(line)
            cursor += 1

        body = "\n".join(body_lines).strip()
        label = parent_label or "1"
        section = parent_title or "Problem"
        if len(body) >= 20:
            key = f"{label}:{body[:80]}"
            if key not in seen:
                seen.add(key)
                found.append((label, body, section))
        index = cursor if cursor > index else index + 1
    return found


def _looks_like_markdown(text: str) -> bool:
    return bool(re.search(r"^#{1,6}\s+\S", text, re.MULTILINE))


def _markdown_block_for_label(text: str, label: str) -> str | None:
    """Return the full ``### Problem`` workshop block for a section label."""
    key = label.strip()
    if not key:
        return None
    for block_label, body, _ in extract_markdown_workshop_problems(text):
        if block_label == key:
            return body
    return None


def _resolve_markdown_statement(
    text: str,
    label: str,
    statement: str,
    *,
    section: str | None = None,
) -> str:
    """Prefer full markdown workshop blocks over shortened LLM summaries."""
    best = statement.strip()
    block = _markdown_block_for_label(text, label)
    if block and len(block) > len(best) + 20:
        return block
    if section:
        section_key = section.strip().lower()
        for _, body, block_section in extract_markdown_workshop_problems(text):
            if block_section and section_key in block_section.strip().lower():
                if len(body) > len(best) + 20:
                    best = body
    return best


def extract_all_labeled_problems(text: str) -> list[tuple[str, str, str | None]]:
    """Extract every ``Problem X.Y`` block from paper text (full statements)."""
    labels: list[str] = []
    seen: set[str] = set()
    for match in _PROBLEM_HEADER.finditer(text):
        label = match.group("label")
        if label not in seen:
            seen.add(label)
            labels.append(label)

    found: list[tuple[str, str, str | None]] = []
    for label in labels:
        block = extract_labeled_problem_block(text, label)
        if block:
            found.append((label, block, None))
    return found


def _markdown_problem_line_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) line indices for each ``### Problem`` markdown block."""
    lines = text.splitlines()
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        heading = _MD_PROBLEM_HEADING.match(lines[index].strip())
        if not heading:
            index += 1
            continue
        problem_level = len(heading.group(1))
        parent_idx: int | None = None
        for back in range(index - 1, -1, -1):
            section = _MD_NUMBERED_SECTION.match(lines[back].strip())
            if section and len(section.group(1)) < problem_level:
                parent_idx = back
                break
        start = parent_idx if parent_idx is not None else index
        end = index + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped.startswith("#"):
                level_match = re.match(r"^(#+)\s", stripped)
                if level_match and len(level_match.group(1)) <= problem_level:
                    break
            end += 1
        spans.append((start, end))
        index = end
    return spans


def _merge_candidates(
    *groups: list[tuple[str, str, str | None]],
) -> list[tuple[str, str, str | None]]:
    """Merge extraction groups, keeping the longest statement per label."""
    by_label: dict[str, tuple[str, str, str | None]] = {}
    order: list[str] = []
    for group in groups:
        for label, statement, section in group:
            key = label.strip()
            existing = by_label.get(key)
            if existing is None:
                by_label[key] = (label, statement, section)
                order.append(key)
                continue
            _, existing_statement, existing_section = existing
            if len(statement) > len(existing_statement):
                by_label[key] = (label, statement, section or existing_section)
    return [by_label[key] for key in order]


def _read_paper_text(ot_dir: Path, paper_id: str) -> str | None:
    from opentorus.research.papers import get_paper

    paper = get_paper(ot_dir, paper_id)
    if paper is None or not paper.text_path:
        return None
    path = ot_dir / paper.text_path
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_statement(
    ot_dir: Path,
    label: str,
    statement: str,
    *,
    paper_id: str | None = None,
    text: str | None = None,
    section: str | None = None,
) -> str:
    """Prefer the full labeled block over a shortened candidate statement."""
    if not label.strip():
        return statement.strip()
    source_text = text
    if source_text is None and paper_id:
        source_text = _read_paper_text(ot_dir, paper_id)
    if source_text:
        block = extract_labeled_problem_block(source_text, label)
        if block and len(block) > len(statement.strip()) + 20:
            return block
        if _looks_like_markdown(source_text):
            return _resolve_markdown_statement(source_text, label, statement, section=section)
    return statement.strip()


def _heuristic_extract(text: str) -> list[tuple[str, str, str | None]]:
    """Return (label, statement, section) candidates from plain text."""
    found: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    section: str | None = None
    in_open_section = False
    lines = text.splitlines()
    md_spans = _markdown_problem_line_spans(text)
    i = 0
    while i < len(lines):
        if any(start <= i < end for start, end in md_spans):
            i += 1
            continue
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip() or section
            # ``section`` may still be None for a bare ``#`` before any titled
            # heading; treat that as not an open-problems section.
            in_open_section = _is_open_section_header(section or "")
            i += 1
            continue
        if _is_open_section_header(line):
            section = line.strip()
            in_open_section = True
            i += 1
            continue
        match = _match_problem_line(line, relaxed=in_open_section)
        if match:
            label, body = match
            block = extract_labeled_problem_block(text, label)
            if block and len(block) > len(body) + 20:
                body = block
                j = i + 1
                while j < len(lines):
                    stripped = lines[j].strip()
                    if stripped and re.match(
                        r"^(?:Problem|Open\s+[Qq]uestion)\s+[\d]", stripped, re.IGNORECASE
                    ):
                        break
                    if stripped.startswith("Likewise,"):
                        break
                    j += 1
                i = j
            else:
                body, i = _collect_body(lines, i, body)
            if len(body) < 10:
                i += 1
                continue
            key = f"{label}:{body[:80]}"
            if key not in seen:
                seen.add(key)
                found.append((label, body, section))
            continue
        i += 1
    return found


def _ensure_full_text(ot_dir: Path, paper) -> None:  # noqa: ANN001
    """Extract ``text.txt`` from the local PDF when only a reading note exists."""
    if paper.text_path:
        path = ot_dir / paper.text_path
        if path.is_file() and path.stat().st_size > 0:
            return
    if not paper.local_path:
        return
    from opentorus.research.papers import extract_paper

    extract_paper(ot_dir, paper.id)


def _paper_text(ot_dir: Path, paper) -> str:  # noqa: ANN001
    """Prefer full extracted PDF text; fall back to reading notes."""
    parts: list[str] = []
    if paper.title:
        parts.append(paper.title)
    if paper.abstract:
        parts.append(paper.abstract)

    seen_paths: set[Path] = set()
    for rel in (paper.text_path, paper.note_path, paper.summary_path):
        if not rel:
            continue
        path = ot_dir / rel
        if not path.is_file() or path in seen_paths:
            continue
        seen_paths.add(path)
        parts.append(path.read_text(encoding="utf-8", errors="replace"))

    if not parts:
        raise OpenTorusError(
            f"No readable text for {paper.id}. Run `opentorus paper extract {paper.id}` "
            f"Parse the paper with `opentorus paper fetch` (DOI/arXiv) or `paper ingest` first."
        )
    return "\n\n".join(parts)


def _llm_usable(provider: BaseProvider | None) -> bool:
    return provider is not None and getattr(provider, "name", "mock") != "mock"


def _select_text_for_llm(text: str, *, max_chars: int = _LLM_MAX_CHARS) -> str:
    """Pick the most relevant excerpt for LLM extraction (open-problem sections)."""
    if len(text) <= max_chars:
        return text

    lines = text.splitlines()
    windows: list[str] = []
    chunk: list[str] = []
    in_relevant = False

    for line in lines:
        stripped = line.strip()
        if (
            _is_open_section_header(stripped)
            or (_OPEN_SECTION.search(stripped) and len(stripped) < 100)
            or _MD_PROBLEM_HEADING.match(stripped)
        ):
            if chunk:
                windows.append("\n".join(chunk))
            chunk = [line]
            in_relevant = True
            continue
        if in_relevant:
            chunk.append(line)
            if len("\n".join(chunk)) > 15_000:
                windows.append("\n".join(chunk))
                chunk = []
                in_relevant = False
    if chunk:
        windows.append("\n".join(chunk))

    for match in _LLM_KEYWORD.finditer(text):
        start = max(0, match.start() - 2000)
        end = min(len(text), match.end() + 8000)
        windows.append(text[start:end])

    if windows:
        combined = "\n\n---\n\n".join(windows)
        return combined[:max_chars]

    return text[-max_chars:]


_EXTRACTION_RULES = """Rules:
- Return ONLY a JSON array of objects with keys: label, statement, section.
- Include only problems explicitly presented as open, unsolved, or conjectural.
- Include starred/challenging textbook problems (e.g. 'Problem 9.16*') when they ask
  for proof, classification, or construction — not trivial exercises.
- Do NOT invent problems that are not in the text.
- Do NOT include routine exercises with known answers unless marked open.
- Use the source numbering for label when present (e.g. '9.16', '12'); \
otherwise assign '1', '2', … in document order.
- statement must be self-contained: include definitions, notation, and the full
  question (not a one-sentence summary). For numbered workshop problems, copy the
  complete problem block from the source.
- section is the heading where the problem appears, or null.
- If none are found, return []."""


def _build_llm_prompt(
    *,
    paper_id: str,
    title: str | None,
    excerpt: str,
    is_markdown: bool = False,
) -> str:
    title_line = title or "(untitled)"
    markdown_note = ""
    if is_markdown:
        markdown_note = (
            "This is a markdown research note. Problems may appear as section headings, "
            "display math, or a final research question — not only as numbered "
            "'Problem X.Y' lines.\n\n"
        )
    return (
        "Extract open mathematical problems, conjectures, and research questions "
        f"from this document excerpt ({paper_id}: {title_line}).\n\n"
        f"{markdown_note}"
        f"{_EXTRACTION_RULES}\n\n"
        f"Excerpt:\n\n{excerpt}"
    )


def _build_vision_prompt(
    *,
    paper_id: str,
    title: str | None,
    page_from: int,
    page_to: int,
) -> str:
    title_line = title or "(untitled)"
    return (
        f"You are reading scanned pages {page_from}–{page_to} from {paper_id} ({title_line}).\n"
        "The attached PNG images are those pages, in order.\n\n"
        "This is a mathematics textbook: problems often appear at the END of a chapter "
        "(numbered like 'Problem 3.1' or 'Problem 9.16*').\n\n"
        "Extract open mathematical problems, conjectures, and research questions "
        "visible on these pages.\n\n"
        f"{_EXTRACTION_RULES}"
    )


def _parse_llm_questions(text: str) -> list[tuple[str, str, str | None]]:
    stripped = text.strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    found: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        statement = str(item.get("statement", "")).strip()
        section_raw = item.get("section")
        section = str(section_raw).strip() if section_raw else None
        if not label or len(statement) < 10:
            continue
        key = f"{label}:{statement[:80]}"
        if key in seen:
            continue
        seen.add(key)
        found.append((label, statement, section))
    return found


def _llm_extract(
    text: str,
    provider: BaseProvider,
    *,
    paper_id: str,
    title: str | None,
    prefer_full_text: bool = False,
    is_markdown: bool = False,
    on_progress: Callable[[str], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_llm_request: Callable[[list[Any], list[dict] | None], None] | None = None,
    on_llm_response: Callable[[Any], None] | None = None,
    stream: bool | None = None,
) -> list[tuple[str, str, str | None]]:
    from opentorus.agent.session import SessionMessage
    from opentorus.providers.base import provider_label

    if prefer_full_text and len(text) <= _LLM_MAX_CHARS:
        excerpt = text
    else:
        excerpt = _select_text_for_llm(text)
    prompt = _build_llm_prompt(
        paper_id=paper_id, title=title, excerpt=excerpt, is_markdown=is_markdown
    )
    label = provider_label(provider)
    if on_progress:
        on_progress(
            f"Finding open problems in {paper_id} with {label} "
            f"({len(excerpt):,} chars of paper text)…"
        )

    streamed = {"chars": 0, "last_report": 0}

    def _on_text(chunk: str) -> None:
        if on_text is not None:
            on_text(chunk)
            return
        streamed["chars"] += len(chunk)
        if on_progress and streamed["chars"] - streamed["last_report"] >= 200:
            streamed["last_report"] = streamed["chars"]
            on_progress(f"  …{label} returned {streamed['chars']:,} chars so far")

    def _on_thinking(chunk: str) -> None:
        if on_thinking is not None:
            on_thinking(chunk)

    messages = [SessionMessage(role="user", content=prompt)]
    if on_llm_request is not None:
        on_llm_request(messages, None)
    use_stream = stream if stream is not None else bool(on_text or on_thinking)
    try:
        response = provider.respond(
            messages,
            stream=use_stream,
            on_text=_on_text if use_stream else None,
            on_thinking=_on_thinking if use_stream else None,
        )
    except Exception as exc:  # noqa: BLE001 — LLM extraction is best-effort; fall back to none
        logger.debug("LLM question extraction failed (%s); returning no questions.", exc)
        return []
    if on_llm_response is not None:
        on_llm_response(response)
    if response.kind != "message" or not response.content:
        return []
    return _parse_llm_questions(response.content)


def _vision_extract_batch(
    provider: BaseProvider,
    pdf_path: Path,
    *,
    paper_id: str,
    title: str | None,
    page_from: int,
    page_to: int,
) -> list[tuple[str, str, str | None]]:
    """Run vision extraction on one page batch."""
    from opentorus.agent.session import SessionMessage
    from opentorus.research.pdf_text import render_pdf_pages_base64

    try:
        rendered = render_pdf_pages_base64(
            pdf_path,
            page_from=page_from,
            page_to=page_to,
            dpi=_VISION_DPI,
        )
    except Exception as exc:  # noqa: BLE001 — PDF render is best-effort; skip this batch
        logger.debug("Vision render of pages %d-%d failed (%s).", page_from, page_to, exc)
        return []

    images = [encoded for _, encoded in rendered]
    if not images:
        return []

    prompt = _build_vision_prompt(
        paper_id=paper_id,
        title=title,
        page_from=page_from,
        page_to=page_to,
    )
    try:
        response = provider.respond([SessionMessage(role="user", content=prompt, images=images)])
    except Exception as exc:  # noqa: BLE001 — vision extraction is best-effort; skip this batch
        logger.debug("Vision extraction of pages %d-%d failed (%s).", page_from, page_to, exc)
        return []

    if response.kind != "message" or not response.content:
        return []
    return _parse_llm_questions(response.content)


def _vision_extract_book(
    provider: BaseProvider,
    pdf_path: Path,
    batches: list[tuple[int, int]],
    *,
    ot_dir: Path,
    paper_id: str,
    title: str | None,
    total_pages: int,
    on_progress: Callable[[str], None] | None = None,
) -> list[ProblemDossier]:
    """Scan a book in page batches; persist each problem as soon as it is found."""
    ingested: list[ProblemDossier] = []
    seen: set[str] = set()
    total_batches = len(batches)

    for index, (batch_start, batch_end) in enumerate(batches, start=1):
        pct = int(100 * batch_end / total_pages) if total_pages else 0
        if on_progress:
            on_progress(
                f"[{index}/{total_batches}] pages {batch_start}–{batch_end} "
                f"({pct}% of {total_pages}) — {len(ingested)} problem(s) saved"
            )

        for label, statement, section in _vision_extract_batch(
            provider,
            pdf_path,
            paper_id=paper_id,
            title=title,
            page_from=batch_start,
            page_to=batch_end,
        ):
            problem = _register_one(
                ot_dir,
                label,
                statement,
                section,
                paper_id=paper_id,
                seen=seen,
            )
            if problem is None:
                continue
            if problem not in ingested:
                ingested.append(problem)
            if on_progress:
                snippet = statement[:72] + ("…" if len(statement) > 72 else "")
                on_progress(f"  + {problem.id} ({label}): {snippet}")

    return ingested


def _candidate_key(label: str, statement: str) -> str:
    return f"{label.strip()}:{statement.strip()[:120]}"


def _find_existing_dossier(
    ot_dir: Path,
    *,
    paper_id: str | None = None,
    label: str = "",
    source: str | None = None,
) -> ProblemDossier | None:
    from opentorus.research.dossier.store import list_dossiers

    label_tag = _label_tag(label) if label.strip() else None
    source_tag = _source_tag(source) if source else None
    by_label: ProblemDossier | None = None
    for dossier in list_dossiers(ot_dir):
        tags = set(dossier.tags)
        if paper_id and paper_id not in tags:
            continue
        if source_tag and source_tag not in tags:
            continue
        if label_tag:
            if label_tag not in tags:
                continue
            by_label = dossier
        else:
            return dossier
    if by_label is not None and re.match(r"^\d+(?:\.\d+)+", label.strip()):
        return by_label
    return None


def _register_one(
    ot_dir: Path,
    label: str,
    statement: str,
    section: str | None,
    *,
    paper_id: str | None = None,
    source: str | None = None,
    text: str | None = None,
    seen: set[str],
) -> ProblemDossier | None:
    """Persist one candidate as a dossier; return None if duplicate."""
    from opentorus.research.dossier.store import (
        add_related_paper,
        create_dossier,
        get_dossier,
        read_statement,
        write_statement,
    )
    from opentorus.research.papers import get_paper

    statement = _resolve_statement(
        ot_dir, label, statement, paper_id=paper_id, text=text, section=section
    )

    existing = _find_existing_dossier(ot_dir, paper_id=paper_id, label=label, source=source)
    source_ref = _source_ref(paper_id=paper_id, source=source)
    formatted = _format_dossier_statement(label, section, source_ref, statement)
    if existing is not None:
        current = read_statement(ot_dir, existing.id)
        if len(formatted) > len(current.strip()) + 20:
            write_statement(ot_dir, existing.id, formatted)
            refreshed = get_dossier(ot_dir, existing.id)
            return refreshed if refreshed is not None else existing
        return existing

    key = _candidate_key(label, statement)
    if key in seen:
        return None
    seen.add(key)

    title = f"Problem {label.strip()}" if label.strip() else "Extracted problem"
    dossier = create_dossier(
        ot_dir,
        formatted,
        title=title,
        tags=_dossier_tags(paper_id=paper_id, label=label, source=source),
    )

    if paper_id:
        paper = get_paper(ot_dir, paper_id)
        paper_title = paper.title if paper and paper.title else paper_id
        add_related_paper(
            ot_dir,
            dossier.id,
            title=paper_title,
            paper_artifact=paper_id,
            relevance=(
                f"Extracted from {paper_id}" + (f" (label {label})" if label.strip() else "")
            ),
        )
    return dossier


def _register_candidates(
    ot_dir: Path,
    candidates: list[tuple[str, str, str | None]],
    *,
    paper_id: str | None = None,
    source: str | None = None,
    text: str | None = None,
) -> list[ProblemDossier]:
    if not candidates:
        return []

    seen: set[str] = set()
    ingested: list[ProblemDossier] = []
    for label, statement, section in candidates:
        problem = _register_one(
            ot_dir,
            label,
            statement,
            section,
            paper_id=paper_id,
            source=source,
            text=text,
            seen=seen,
        )
        if problem is not None and problem not in ingested:
            ingested.append(problem)
    return ingested


def extract_problems_from_paper(
    ot_dir: Path,
    paper_id: str,
    *,
    provider: BaseProvider | None = None,
    use_llm: bool = True,
    prefer_llm: bool = False,
    force_vision: bool = False,
    on_progress: Callable[[str], None] | None = None,
    on_llm_text: Callable[[str], None] | None = None,
    on_llm_thinking: Callable[[str], None] | None = None,
    on_llm_request: Callable[[list[Any], list[dict] | None], None] | None = None,
    on_llm_response: Callable[[Any], None] | None = None,
    stream_llm: bool | None = None,
    page_from: int | None = None,
    page_to: int | None = None,
    batch_size: int = _VISION_BATCH_SIZE,
) -> ExtractionOutcome:
    """Extract open problems from a paper into PROBLEM-* dossiers (vision / LLM / heuristics).

    By default OpenTorus copies full ``Problem X.Y`` blocks straight from the paper
    text first (fast, verbatim) and only falls back to the LLM. Set ``prefer_llm`` to
    skip that text-block shortcut and drive extraction with the model (heuristics
    still act as a final fallback if the LLM yields nothing).

    ``force_vision`` renders the PDF pages to PNGs and sends them to a vision model
    even when a text layer exists — useful for math-heavy or multi-column layouts
    where text extraction mangles formulas.
    """
    from opentorus.research.papers import get_paper
    from opentorus.research.pdf_text import (
        DEFAULT_SKIP_TRAILING_PAGES,
        book_page_batches,
        extract_pdf_pages_pypdf,
        is_usable_extraction,
        pdf_page_count,
        pdftoppm_available,
    )

    paper = get_paper(ot_dir, paper_id)
    if paper is None:
        raise OpenTorusError(f"No paper with id '{paper_id}'.")

    _ensure_full_text(ot_dir, paper)
    paper = get_paper(ot_dir, paper_id)
    assert paper is not None

    pdf_path = (ot_dir / paper.local_path) if paper.local_path else None
    pypdf_pages: list[str] = []
    if pdf_path and pdf_path.is_file():
        pypdf_pages = extract_pdf_pages_pypdf(pdf_path)
    text_usable = is_usable_extraction(pypdf_pages)

    text = _paper_text(ot_dir, paper)

    skip_heuristic_first = (prefer_llm or force_vision) and use_llm and _llm_usable(provider)
    if not skip_heuristic_first and (text_usable or len(text.strip()) >= 100):
        block_candidates = extract_all_labeled_problems(text)
        heuristic_candidates = _heuristic_extract(text)
        merged = _merge_candidates(block_candidates, heuristic_candidates)
        if merged:
            if on_progress and block_candidates:
                on_progress(f"Found {len(block_candidates)} full Problem block(s) in paper text")
            questions = _register_candidates(ot_dir, merged, paper_id=paper_id)
            return ExtractionOutcome(problems=questions, method="heuristic")

    if use_llm and _llm_usable(provider):
        if (
            pdf_path
            and pdf_path.is_file()
            and (not text_usable or force_vision)
            and pdftoppm_available()
        ):
            from opentorus.providers.vision import require_vision_provider

            require_vision_provider(
                provider,
                getattr(provider, "config", None),
                context="Vision extraction" if force_vision else "Scanned PDF extraction",
            )
            total = pdf_page_count(pdf_path)
            batches = book_page_batches(
                total,
                batch_size=batch_size,
                skip_trailing=DEFAULT_SKIP_TRAILING_PAGES,
                page_from=page_from,
                page_to=page_to,
            )
            scan_from = batches[0][0] if batches else 1
            scan_to = batches[-1][1] if batches else total
            if on_progress:
                reason = "forced vision mode" if force_vision and text_usable else "no text layer"
                on_progress(
                    f"Rendering PDF to PNG ({total} pages, {reason}) — "
                    f"walking pages {scan_from}–{scan_to} in {len(batches)} batch(es)"
                )
            questions = _vision_extract_book(
                provider,  # type: ignore[arg-type]
                pdf_path,
                batches,
                ot_dir=ot_dir,
                paper_id=paper_id,
                title=paper.title,
                total_pages=total,
                on_progress=on_progress,
            )
            if questions:
                return ExtractionOutcome(problems=questions, method="vision")
            if force_vision:
                if on_progress:
                    on_progress(
                        "Vision scan finished with no problems extracted "
                        "(not falling back to text LLM because --vision was requested)."
                    )
                return ExtractionOutcome(problems=[], method="vision")

        if force_vision:
            # Vision path unavailable (no PDF / pdftoppm) but user explicitly asked for it.
            raise OpenTorusError(
                "--vision was requested but page rendering is unavailable "
                "(missing local PDF or pdftoppm)."
            )

        if text_usable or len(text.strip()) >= 100:
            llm_candidates = _llm_extract(
                text,
                provider,  # type: ignore[arg-type]
                paper_id=paper_id,
                title=paper.title,
                on_progress=on_progress,
                on_text=on_llm_text,
                on_thinking=on_llm_thinking,
                on_llm_request=on_llm_request,
                on_llm_response=on_llm_response,
                stream=stream_llm,
            )
            if on_progress:
                on_progress(f"Parsed {len(llm_candidates)} candidate(s) from the model response")
            if llm_candidates:
                questions = _register_candidates(ot_dir, llm_candidates, paper_id=paper_id)
                return ExtractionOutcome(problems=questions, method="llm")

    heuristic_candidates = _heuristic_extract(text)
    if heuristic_candidates:
        questions = _register_candidates(ot_dir, heuristic_candidates, paper_id=paper_id)
        return ExtractionOutcome(problems=questions, method="heuristic")

    return ExtractionOutcome(problems=[], method="none")


def extraction_hints(
    ot_dir: Path,
    paper_id: str,
    *,
    llm_available: bool = False,
    scanned_pdf: bool = False,
) -> list[str]:
    """Actionable hints when extraction finds nothing."""
    from opentorus.research.papers import get_paper

    paper = get_paper(ot_dir, paper_id)
    hints: list[str] = []
    if paper is None:
        return hints
    if scanned_pdf:
        hints.append(
            "This PDF has no embedded text layer (scanned pages). OpenTorus renders "
            "page PNGs and sends them to a vision-capable model."
        )
        if not llm_available:
            hints.append(
                "Configure a vision-capable model (e.g. llava, gemma with vision, "
                "gpt-4o) — the mock provider cannot read images."
            )
    if not paper.local_path:
        hints.append(
            "This paper has no local PDF. Fetch or add a PDF, then run "
            f"`opentorus paper extract {paper_id}`."
        )
    elif not paper.text_path and not scanned_pdf:
        hints.append(
            f"Full PDF text was missing; re-run `opentorus paper extract {paper_id}` "
            "if extraction still finds nothing."
        )
    if llm_available and not scanned_pdf:
        hints.append(
            "For text PDFs, OpenTorus first copies full 'Problem X.Y' blocks from the "
            "extracted paper text, then falls back to LLM parsing when needed."
        )
    elif not llm_available and not scanned_pdf:
        hints.append(
            "Configure a real model provider (openai, anthropic, ollama) for LLM-based "
            "extraction on books and irregular layouts."
        )
    hints.append(
        "Heuristics look for 'Problem 1.', 'Open Problem 2:', numbered items under "
        "'Open Problems' headings, and multi-line statements."
    )
    return hints


def extract_problems_from_markdown(
    ot_dir: Path,
    markdown_path: Path,
    *,
    provider: BaseProvider | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_llm_text: Callable[[str], None] | None = None,
    on_llm_thinking: Callable[[str], None] | None = None,
    on_llm_request: Callable[[list[Any], list[dict] | None], None] | None = None,
    on_llm_response: Callable[[Any], None] | None = None,
    stream_llm: bool | None = None,
) -> ExtractionOutcome:
    """Extract open problems from a markdown file into PROBLEM-* dossiers (LLM only)."""
    path = markdown_path.expanduser().resolve()
    if not path.is_file():
        raise OpenTorusError(f"Markdown file not found: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 20:
        raise OpenTorusError(f"Markdown file is empty or too short: {path}")

    if not _llm_usable(provider):
        raise OpenTorusError(
            "Markdown extraction requires a configured model provider "
            "(openai, anthropic, ollama, …)."
        )

    try:
        source = str(path.relative_to(ot_dir.parent))
    except ValueError:
        source = str(path)

    llm_candidates = _llm_extract(
        text,
        provider,  # type: ignore[arg-type]
        paper_id=path.name,
        title=path.stem,
        prefer_full_text=True,
        is_markdown=True,
        on_progress=on_progress,
        on_text=on_llm_text,
        on_thinking=on_llm_thinking,
        on_llm_request=on_llm_request,
        on_llm_response=on_llm_response,
        stream=stream_llm,
    )
    if on_progress:
        on_progress(f"Parsed {len(llm_candidates)} candidate(s) from the model response")

    if not llm_candidates:
        return ExtractionOutcome(problems=[], method="llm")

    problems = _register_candidates(ot_dir, llm_candidates, source=source, text=text)
    return ExtractionOutcome(problems=problems, method="llm")


def dossier_label_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("label:"):
            return tag.removeprefix("label:")
    return None


def dossier_paper_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("PAPER-"):
            return tag
    return None


def dossier_source_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("source:"):
            return tag.removeprefix("source:")
    return None


def refresh_dossier_statement_from_source(
    ot_dir: Path,
    problem_id: str,
    *,
    paper_id: str | None = None,
    label: str | None = None,
) -> str:
    """Rewrite a dossier statement from its linked paper or markdown source."""
    from opentorus.research.dossier.store import (
        read_statement,
        require_dossier,
        write_statement,
    )

    dossier = require_dossier(ot_dir, problem_id)
    linked_paper = paper_id or dossier_paper_from_tags(dossier.tags)
    linked_label = label or dossier_label_from_tags(dossier.tags)
    linked_source = dossier_source_from_tags(dossier.tags)

    body: str | None = None
    section: str | None = None
    if linked_paper and linked_label:
        text = _read_paper_text(ot_dir, linked_paper)
        if text:
            body = extract_labeled_problem_block(text, linked_label)
    elif linked_source and linked_label:
        source_path = Path(linked_source)
        if not source_path.is_file():
            source_path = ot_dir.parent / linked_source
        if source_path.is_file():
            text = source_path.read_text(encoding="utf-8", errors="replace")
            body = extract_labeled_problem_block(text, linked_label)
            if not body and _looks_like_markdown(text):
                body = _markdown_block_for_label(text, linked_label or "")

    if not body:
        current = read_statement(ot_dir, problem_id)
        if current.strip():
            return current.strip()
        raise OpenTorusError(
            f"Could not locate a fuller statement for {problem_id}. "
            "Ensure the dossier tags include PAPER-* or source:* and label:*."
        )

    source_ref = _source_ref(paper_id=linked_paper, source=linked_source)
    statement = _format_dossier_statement(
        linked_label or "",
        section,
        source_ref,
        body,
    )
    write_statement(ot_dir, problem_id, statement)
    return statement


def problems_to_json(ot_dir: Path, problems: list[ProblemDossier]) -> str:
    from opentorus.research.dossier.store import read_statement

    payload = []
    for problem in problems:
        payload.append(
            {
                "id": problem.id,
                "title": problem.title,
                "tags": problem.tags,
                "statement": read_statement(ot_dir, problem.id),
            }
        )
    return json.dumps(payload, indent=2)
