"""Append-only JSONL persistence helpers.

JSONL keeps project memory inspectable and Git-friendly. Reads are tolerant:
corrupt lines are warned about and skipped rather than crashing the session, so a
single bad line never makes a whole ledger unreadable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("opentorus")

ModelT = TypeVar("ModelT", bound=BaseModel)


def append_jsonl(path: Path, model: BaseModel) -> None:
    """Append a single model as one JSON line (datetimes serialized as ISO)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(model.model_dump_json())
        fh.write("\n")


def read_jsonl(path: Path, model_cls: type[ModelT]) -> list[ModelT]:
    """Read all valid records from ``path``, skipping (and warning on) bad lines."""
    return list(iter_jsonl(path, model_cls))


def rewrite_jsonl(path: Path, models: Sequence[BaseModel]) -> None:
    """Overwrite ``path`` with the given models (used for in-place updates).

    JSONL is append-only by default; rewriting the whole file is acceptable for
    small, mutable ledgers such as claims where an entry's status can change. The
    rewrite is atomic (temp file + rename) so a crash mid-write cannot truncate the
    ledger and silently lose records.
    """
    from opentorus.atomicio import atomic_write_text

    payload = "".join(model.model_dump_json() + "\n" for model in models)
    atomic_write_text(path, payload)


def iter_jsonl(path: Path, model_cls: type[ModelT]) -> Iterator[ModelT]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield model_cls.model_validate_json(line)
            except ValidationError as exc:
                logger.warning("Skipping corrupt JSONL line %d in %s: %s", lineno, path, exc)


def next_sequential_id(prefix: str, existing_count: int) -> str:
    """Build a deterministic, zero-padded artifact id, e.g. ``CLAIM-0001``."""
    return f"{prefix}-{existing_count + 1:04d}"


def next_id(prefix: str, existing_ids: Iterable[str]) -> str:
    """Next id derived from the highest existing numeric suffix, e.g. ``CLAIM-0007``.

    Unlike :func:`next_sequential_id`, this does not assume the record count
    equals the highest id. ``read_jsonl`` silently skips corrupt lines, so a
    count-based id can collide with a still-present record; deriving from the
    max suffix keeps ids unique even when a line is unparseable. Use this for
    ledgers whose records are later looked up or mutated by id.
    """
    highest = 0
    for ident in existing_ids:
        suffix = ident.rsplit("-", 1)[-1]
        try:
            highest = max(highest, int(suffix))
        except ValueError:
            continue
    return f"{prefix}-{highest + 1:04d}"
