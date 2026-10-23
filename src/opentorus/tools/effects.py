"""Effect classes: what a tool call does to the world, and what that permits.

Every tool has one of four effect classes:

* ``observation`` -- reads only (files, git, the web, the artifact store). Safe to
  repeat; a lost answer can simply be asked for again.
* ``reversible`` -- changes local state that can be put back exactly (a file write:
  the previous content is captured as a ``PATCH-*`` artifact).
* ``compensatable`` -- records something that cannot be erased but can be superseded
  (an append-only claim, evidence or memory record; failed attempts stay first-class).
* ``irreversible`` -- an effect outside OpenTorus' control: an arbitrary shell
  command, a code run, a Slurm submission, an external (MCP) tool.

Two rules follow, both enforced outside the tool itself:

1. **Approval granularity.** In ``ask`` mode an irreversible call is approved *per
   call*: ``[s] this session`` is not offered for it.
2. **No blind repeats.** A non-observation call whose outcome is unknown (a timeout
   after the request left) may already have taken effect. The identical call is
   refused for the rest of the session; the agent has to check the effect first.

The hard guarantees (dangerous commands, sensitive files, review mode) are
unaffected -- effects only make the gates finer, never looser.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

Effect = Literal["observation", "reversible", "compensatable", "irreversible"]
EFFECTS: tuple[Effect, ...] = ("observation", "reversible", "compensatable", "irreversible")

# Built-in classification by tool name (research tools live in tools/research.py;
# classifying them here keeps that module untouched).
BUILTIN_EFFECTS: dict[str, Effect] = {
    # observation
    "status": "observation",
    "git_diff": "observation",
    "memory_list": "observation",
    "list_files": "observation",
    "read_file": "observation",
    "glob_files": "observation",
    "lit_search": "observation",
    "web_search": "observation",
    "fetch_url": "observation",
    "paper_list": "observation",
    "paper_read": "observation",
    "kb_query": "observation",
    # reversible (previous content captured as a PATCH artifact)
    "write_file": "reversible",
    "apply_patch": "reversible",
    # compensatable (append-only artifact records)
    "paper_add": "compensatable",
    "paper_fetch": "compensatable",
    "paper_ingest_inbox": "compensatable",
    "paper_extract_problems": "compensatable",
    "memory_add": "compensatable",
    "claim_new": "compensatable",
    "evidence_add": "compensatable",
    "exp_new": "compensatable",
    "dossier_known_result_add": "compensatable",
    "dossier_related_paper_add": "compensatable",
    "proof_write": "compensatable",
    "shell_jobs": "compensatable",
    # irreversible
    "run_shell": "irreversible",
    "exp_run": "irreversible",
}

_DEFAULT_BY_PERMISSION: dict[str, Effect] = {
    "read": "observation",
    "write": "reversible",
    "command": "irreversible",
    "external": "irreversible",
}


def effect_of(tool: object) -> Effect:
    """A tool's effect class: its own ``effect``, the built-in table, or its permission."""
    declared = getattr(tool, "effect", None)
    if declared in EFFECTS:
        return declared
    name = getattr(tool, "name", "")
    if name in BUILTIN_EFFECTS:
        return BUILTIN_EFFECTS[name]
    return _DEFAULT_BY_PERMISSION.get(str(getattr(tool, "permission", "read")), "irreversible")


def canonical_args(args: dict) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


def call_digest(tool_name: str, args: dict) -> str:
    return hashlib.sha256(f"{tool_name}\0{canonical_args(args)}".encode()).hexdigest()


class UnknownOutcomeGuard:
    """Refuses to repeat a non-observation call whose earlier outcome is unknown."""

    def __init__(self) -> None:
        self._unknown: dict[str, str] = {}

    def note(self, tool: object, args: dict, metadata: dict) -> None:
        if metadata.get("outcome") != "unknown" or effect_of(tool) == "observation":
            return
        name = str(getattr(tool, "name", ""))
        self._unknown[call_digest(name, args)] = str(metadata.get("op_id") or "")

    def refusal(self, tool: object, args: dict) -> str | None:
        name = str(getattr(tool, "name", ""))
        op_id = self._unknown.get(call_digest(name, args))
        if op_id is None:
            return None
        ref = f" (operation {op_id})" if op_id else ""
        return (
            f"Refused: this exact {name} call already ran once with an unknown outcome{ref} "
            "-- it may have taken effect. Repeating it could do it twice. Check its effect "
            "with a read-only tool first; a human can repeat it if it really did not happen."
        )
