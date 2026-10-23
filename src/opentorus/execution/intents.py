"""Intent-before-dispatch records for effects that cannot be safely repeated.

Submitting a Slurm job or calling an external MCP tool has an effect *outside*
this process. If the connection dies after the request left (an ssh timeout
after ``sbatch``, an MCP server that never answers), the caller does not know
whether the effect happened. Retrying blindly duplicates it: two Slurm jobs, two
issues filed, two emails sent.

So every such dispatch is bracketed in an append-only JSONL log:

1. an ``intent`` line with a stable operation id, written and ``fsync``'d
   *before* the request goes out;
2. an ``outcome`` line (``succeeded`` / ``failed`` / ``unknown``) afterwards.

An intent without an outcome -- or with ``unknown`` -- means "may have happened".
Recovery queries the remote side by the operation id (the Slurm job name *is* the
op id) instead of dispatching again.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Outcome = Literal["succeeded", "failed", "unknown"]

INTENTS_FILENAME = "intents.jsonl"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_operation_id(kind: str) -> str:
    """A fresh, filesystem- and Slurm-job-name-safe operation id."""
    safe = "".join(c if c.isalnum() else "-" for c in kind.lower()).strip("-") or "op"
    return f"ot-{safe}-{uuid.uuid4().hex[:16]}"


def args_digest(payload: object) -> str:
    """Stable digest of the dispatched parameters (canonical JSON)."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IntentLog:
    """Append-only, fsync'd intent/outcome log at ``path``."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def intent(self, op_id: str, kind: str, *, target: str, digest: str, **extra: object) -> None:
        """Record that ``op_id`` is about to be dispatched. Durable before returning."""
        self._append(
            {
                "record": "intent",
                "op_id": op_id,
                "kind": kind,
                "target": target,
                "args_digest": digest,
                "at": _now(),
                **extra,
            }
        )

    def outcome(self, op_id: str, outcome: Outcome, **extra: object) -> None:
        self._append(
            {"record": "outcome", "op_id": op_id, "outcome": outcome, "at": _now(), **extra}
        )

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from a crash mid-append
            if isinstance(rec, dict):
                out.append(rec)
        return out

    def state(self, op_id: str) -> Outcome | Literal["pending", "absent"]:
        """``absent`` (never intended), ``pending`` (intent, no outcome) or the outcome."""
        seen = False
        result: Outcome | None = None
        for rec in self.records():
            if rec.get("op_id") != op_id:
                continue
            if rec.get("record") == "intent":
                seen = True
            elif rec.get("record") == "outcome":
                value = rec.get("outcome")
                if value in ("succeeded", "failed", "unknown"):
                    result = value
        if result is not None:
            return result
        return "pending" if seen else "absent"

    def unresolved(self) -> list[dict]:
        """Intents whose outcome is missing or ``unknown`` -- they may have happened."""
        latest: dict[str, dict] = {}
        intents: dict[str, dict] = {}
        for rec in self.records():
            op = rec.get("op_id")
            if not isinstance(op, str):
                continue
            if rec.get("record") == "intent":
                intents[op] = rec
            elif rec.get("record") == "outcome":
                latest[op] = rec
        return [
            rec
            for op, rec in intents.items()
            if op not in latest or latest[op].get("outcome") == "unknown"
        ]
