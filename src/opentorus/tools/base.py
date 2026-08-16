"""Tool protocol and call/result schemas.

Tools are the unit of agent capability. Keeping ``ToolCall``/``ToolResult`` and an
abstract ``Tool`` base in one place lets the registry, the agent loop, and future
plugins share a stable contract.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.permissions.policy import RiskLevel

# How a tool's call must be permission-checked before it runs:
# - "read": no gate (read tools enforce their own sensitive-file guard);
# - "write": gated by ``evaluate_write`` using the call's ``path`` argument;
# - "command": gated by ``evaluate_command`` using the call's ``command`` argument;
# - "external": opaque external (e.g. MCP) tool, gated by ``evaluate_external_tool``.
PermissionKind = Literal["read", "write", "command", "external"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


class ToolCall(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str
    args: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class ToolResult(BaseModel):
    tool_call_id: str
    ok: bool
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class Tool(ABC):
    """Abstract base for all tools.

    Subclasses declare a name, description, input schema, and a default risk
    level, and implement :meth:`run`.
    """

    name: str
    description: str
    input_schema: dict
    risk_level: RiskLevel = "low"
    permission: PermissionKind = "read"

    @abstractmethod
    def run(self, call: ToolCall) -> ToolResult:  # pragma: no cover - interface
        raise NotImplementedError

    def to_spec(self) -> dict:
        """Return a provider-neutral tool spec (name, description, JSON schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema or {"type": "object", "properties": {}},
        }

    def ok(self, call: ToolCall, content: str, **metadata: object) -> ToolResult:
        return ToolResult(tool_call_id=call.id, ok=True, content=content, metadata=dict(metadata))

    def fail(self, call: ToolCall, content: str, **metadata: object) -> ToolResult:
        return ToolResult(tool_call_id=call.id, ok=False, content=content, metadata=dict(metadata))


# JSON-schema ``type`` → accepted Python types for lightweight argument checking.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _article(declared: str) -> str:
    return f"an {declared}" if declared[:1] in "aeiou" else f"a {declared}"


def _coerced(declared: str, value: object) -> object | None:
    """Return ``value`` in the declared type when the change loses nothing, else None.

    Teaching the shape in the rejection was not enough: llama3.1:70b sent ``gaps`` as a
    string sixteen times across two examples, with the required JSON spelled out in
    every reply. What it sent, though, was ``'["[GAP-1] We need to show …"]'`` — the
    right array, JSON-encoded once too often — and ``limit='10'`` for an integer. Those
    are encodings of the intended value, not different values, so re-reading them is
    honest rather than lenient.

    What is *not* coerced: a multi-line string for an array. Splitting it on newlines
    would guess how many items the model meant, and a gap count is load-bearing — the
    referee counts them. That case keeps the teaching rejection.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if declared in ("array", "object") and text[:1] in "[{":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None  # not JSON after all — an array may still be one bare item
        if isinstance(parsed, _JSON_TYPES[declared]):
            return parsed
        if declared == "object":
            return None
    if declared == "array" and "\n" not in text:
        # One item, written bare (``"[GAP-1]"`` looks like JSON but is not). Wrapping it
        # invents no boundaries; splitting a multi-line string would.
        return [text]
    if declared in ("integer", "number"):
        try:
            return int(text) if declared == "integer" else float(text)
        except ValueError:
            return None
    if declared == "boolean" and text.lower() in ("true", "false"):
        return text.lower() == "true"
    return None


def coerce_tool_args(input_schema: dict, args: dict) -> dict:
    """Re-read arguments a model encoded as strings, leaving everything else alone."""
    try:
        properties = input_schema.get("properties")
        if not isinstance(input_schema, dict) or not isinstance(properties, dict):
            return args
        out = dict(args)
        for key, value in args.items():
            spec = properties.get(key)
            if not isinstance(spec, dict):
                continue
            declared = spec.get("type")
            accepted = _JSON_TYPES.get(declared) if isinstance(declared, str) else None
            if accepted is None or isinstance(value, accepted):
                continue
            if declared in ("integer", "number") and isinstance(value, bool):
                continue  # a boolean where a number belongs is a real mistake
            coerced = _coerced(str(declared), value)
            if coerced is not None:
                out[key] = coerced
        return out
    except Exception:  # noqa: BLE001 — coercion must never crash a tool call
        return args


def _wrong_type_message(key: str, declared: str, value: object) -> str:
    """Say what arrived and what the right shape looks like.

    "Argument 'gaps' must be a array." is ungrammatical, does not say what was sent,
    and does not show the shape to send instead — so a model that wrote its gaps as a
    markdown bullet list has nothing to correct against. Observed on a Sendov run,
    where the whole gap list was passed as one newline-separated string.
    """
    got = type(value).__name__
    message = f"Argument '{key}' must be {_article(declared)}, got {got}."
    if declared == "array" and isinstance(value, str):
        first = value.strip().splitlines()[0].lstrip("-*• ").strip() if value.strip() else "first"
        message += (
            f' Send a JSON array of strings, one entry per item: ["{first[:60]}", "…"] '
            "— not one string with newlines or bullets."
        )
    elif declared == "object" and isinstance(value, str):
        message += ' Send a JSON object, e.g. {"key": "value"} — not a string.'
    return message


def validate_tool_args(input_schema: dict, args: dict) -> str | None:
    """Validate ``args`` against a tool's ``input_schema``, returning an error
    message on the first violation or ``None`` when the call is well-formed.

    Intentionally conservative — it enforces only what is unambiguous from the
    schema (required keys, declared types, and ``enum`` membership) and fails
    *open* on anything it does not understand, so a tool's own validation still
    runs. It exists to give the model a uniform, actionable error instead of a
    misleading "missing argument" failure from a half-applied call.
    """
    try:
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            return None
        properties = input_schema.get("properties")
        if not isinstance(properties, dict):
            return None

        for key in input_schema.get("required", []) or []:
            if key not in args:
                return f"Missing required argument '{key}'."

        for key, value in args.items():
            spec = properties.get(key)
            if not isinstance(spec, dict):
                continue  # unknown / additional property — leave it to the tool
            declared = spec.get("type")
            accepted = _JSON_TYPES.get(declared) if isinstance(declared, str) else None
            if accepted is not None and value is not None:
                # bool is a subclass of int; reject it where a number is expected.
                if declared in ("integer", "number") and isinstance(value, bool):
                    return f"Argument '{key}' must be {_article(declared)}, got boolean."
                if not isinstance(value, accepted):
                    return _wrong_type_message(key, str(declared), value)
            enum = spec.get("enum")
            if isinstance(enum, list) and enum and value not in enum:
                allowed = ", ".join(repr(v) for v in enum)
                return f"Argument '{key}' must be one of: {allowed}."
    except Exception:  # noqa: BLE001 — validation must never crash a tool call
        return None
    return None
