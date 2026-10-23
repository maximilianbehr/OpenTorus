"""Structured Lean/Coq feedback: error classes, first error, open goals.

A 4000-character dump of checker output is the worst possible repair signal for a
model: the first error is buried, the unsolved goal is somewhere in the middle, and
cascading errors look as important as the cause. :func:`summarize` parses checker
output into a compact, deterministic summary — one class per error (the
open-math-harness ``classify_error`` rules, ``interfaces/discovery/src/scoring.rs``),
the first error's line and message, the text of the first unsolved goal, the count of
``sorry`` warnings, and a ``repairable`` flag (≤ 3 errors) — which
``proof_submit`` returns *instead of* the raw dump. The raw output is kept verbatim in
the ``PROOF-*`` artifact.
"""

from __future__ import annotations

import re

ERROR_CLASSES: tuple[str, ...] = (
    "timeout",
    "syntax",
    "unsolved_goals",
    "unknown_identifier",
    "no_goals",
    "synth_failed",
    "rewrite_failed",
    "automation_failed",
    "type_mismatch",
    "tactic_misapplied",
    "other",
)

REPAIRABLE_MAX_ERRORS = 3
_MAX_MESSAGE = 600
_MAX_GOAL = 1200

# ``file.lean:12:4: error: message`` (Lean 4), optionally with an end position.
_LEAN_MSG = re.compile(
    r"^(?P<file>[^\s:]*?):(?P<line>\d+):(?P<col>\d+):(?:\s*\d+:\d+:)?\s*"
    r"(?P<sev>error|warning|info)\s*:\s?(?P<msg>.*)$"
)
# Coq: ``File "x.v", line 3, characters 0-5:`` followed by ``Error: …``.
_COQ_LOC = re.compile(r'^File "[^"]*", line (?P<line>\d+), characters')

_AUTOMATION_TACTICS = (
    "omega",
    "linarith",
    "nlinarith",
    "simp",
    "simp_all",
    "norm_num",
    "decide",
    "aesop",
    "tauto",
    "positivity",
    "ring",
    "field_simp",
    "exact?",
)


def _line_starts(message: str, heads: tuple[str, ...]) -> bool:
    return any(line.lstrip().startswith(heads) for line in message.splitlines())


def _contains_any(message: str, needles: tuple[str, ...]) -> bool:
    return any(n in message for n in needles)


def classify_error(message: str) -> str:
    """The class of one error message (first matching rule wins; ``other`` else)."""
    if _contains_any(message, ("deterministic) timeout", "maximum recursion depth", "heartbeats")):
        return "timeout"
    if _line_starts(
        message,
        (
            "unexpected token",
            "unexpected end of input",
            "expected token",
            "unexpected identifier",
            "expected '",
            "unexpected;",
        ),
    ) or message.startswith("Syntax error"):
        return "syntax"
    if _line_starts(message, ("unsolved goals",)):
        return "unsolved_goals"
    if (
        _line_starts(
            message,
            ("Unknown constant", "Unknown identifier", "unknown constant", "unknown identifier"),
        )
        or "The environment does not contain" in message
        or re.search(r"The reference \S+ was not found", message)
    ):
        return "unknown_identifier"
    if _line_starts(message, ("No goals to be solved", "no goals")):
        return "no_goals"
    if _line_starts(message, ("failed to synthesize",)) or (
        "typeclass instance problem is stuck" in message
    ):
        return "synth_failed"
    if _contains_any(
        message,
        (
            "Did not find an occurrence of the pattern",
            "tactic failed, pattern",
            "Invalid rewrite argument",
            "motive is not type correct",
            "equality or iff proof",
        ),
    ):
        return "rewrite_failed"
    if (
        _line_starts(
            message, ("omega could not prove", "linarith failed", "ring failed", "decide failed")
        )
        or _contains_any(
            message,
            (
                "ring_nf made no progress",
                "made no progress",
                "exhaustive search",
                "interval_cases failed",
                "failed to prove",
                "positivity failed",
                "nlinarith failed",
                "norm_num failed",
                "could not close the goal",
            ),
        )
        or any(f"Tactic `{t}` failed" in message for t in _AUTOMATION_TACTICS)
    ):
        return "automation_failed"
    if (
        _line_starts(
            message,
            (
                "Type mismatch",
                "type mismatch",
                "Application type mismatch",
                "application type mismatch",
                "Function expected",
                "function expected",
                "Failed to infer type",
                "Invalid `",
                "Invalid projection",
                "Invalid argument name",
                "overloaded",
                "Ambiguous term",
                "Invalid field notation",
                "Invalid field",
                "unnecessary",
            ),
        )
        or _contains_any(
            message,
            (
                "mod_cast has type",
                "expression has type",
                "must not contain metavariables",
                "Insufficient number of fields",
                "expected result type of cast",
                "has type",  # Coq: "The term … has type … while it is expected to have type"
            ),
        )
        or re.search(r"invalid `[^`]*` notation", message)
    ):
        return "type_mismatch"
    if _line_starts(
        message,
        ("Tactic `", "Alternative", "invalid ", "Invalid target", "Invalid alternative"),
    ) or (
        _contains_any(
            message,
            ("tactic ", "no applicable constructor", "is not an inductive datatype", "introN"),
        )
        and (
            " failed" in message
            or _contains_any(
                message,
                ("no applicable constructor", "is not an inductive datatype", "introN"),
            )
        )
    ):
        return "tactic_misapplied"
    return "other"


def _lean_messages(output: str) -> list[tuple[int | None, str, str]]:
    """``(line, severity, message)`` triples; a message runs to the next header."""
    msgs: list[tuple[int | None, str, list[str]]] = []
    for raw in output.splitlines():
        m = _LEAN_MSG.match(raw)
        if m:
            msgs.append((int(m.group("line")), m.group("sev"), [m.group("msg")]))
        elif msgs:
            msgs[-1][2].append(raw)
    return [(line, sev, "\n".join(body).strip()) for line, sev, body in msgs]


def _coq_messages(output: str) -> list[tuple[int | None, str, str]]:
    msgs: list[tuple[int | None, str, str]] = []
    lines = output.splitlines()
    pending_line: int | None = None
    i = 0
    while i < len(lines):
        loc = _COQ_LOC.match(lines[i])
        if loc:
            pending_line = int(loc.group("line"))
            i += 1
            continue
        if lines[i].startswith(("Error:", "Warning:")):
            sev = "error" if lines[i].startswith("Error:") else "warning"
            body = [lines[i].split(":", 1)[1].strip()]
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                body.append(lines[i].strip())
                i += 1
            msgs.append((pending_line, sev, "\n".join(body)))
            pending_line = None
            continue
        i += 1
    return msgs


def summarize(backend: str, output: str, *, timed_out: bool = False) -> dict | None:
    """A compact, deterministic summary of checker output, or ``None`` if empty.

    Keys: ``error_count``, ``classes`` (one per error, in :data:`ERROR_CLASSES`
    order — a multiset), ``first_error`` ({line, class, message}), ``unsolved_goal``
    (the first goal text Lean printed), ``sorry_warnings``, ``repairable``
    (``error_count <= 3``) and ``timed_out``.
    """
    if not output.strip() and not timed_out:
        return None
    msgs = _coq_messages(output) if backend == "coq" else _lean_messages(output)
    errors = [(line, msg) for line, sev, msg in msgs if sev == "error"]
    classes = [classify_error(msg) for _, msg in errors]
    if timed_out and "timeout" not in classes:
        classes.append("timeout")
    order = {c: i for i, c in enumerate(ERROR_CLASSES)}
    classes.sort(key=lambda c: order.get(c, len(ERROR_CLASSES)))
    first = min(
        (e for e in errors if e[0] is not None),
        key=lambda e: e[0] or 0,
        default=errors[0] if errors else None,
    )
    first_error = None
    if first is not None:
        first_error = {
            "line": first[0],
            "class": classify_error(first[1]),
            "message": first[1][:_MAX_MESSAGE],
        }
    goal = None
    for _, msg in errors:
        if msg.startswith("unsolved goals"):
            goal = msg[len("unsolved goals") :].strip()[:_MAX_GOAL]
            break
    sorry_warnings = sum(
        1 for _, sev, msg in msgs if sev == "warning" and "declaration uses 'sorry'" in msg
    )
    count = len(errors)
    return {
        "error_count": count,
        "classes": classes,
        "first_error": first_error,
        "unsolved_goal": goal,
        "sorry_warnings": sorry_warnings,
        "repairable": 0 < count <= REPAIRABLE_MAX_ERRORS,
        "timed_out": timed_out,
    }


def render(diagnostics: dict | None) -> str:
    """The model-facing text for a diagnostics summary (empty when there is none)."""
    if not diagnostics:
        return ""
    lines = []
    count = diagnostics.get("error_count", 0)
    classes = diagnostics.get("classes") or []
    if diagnostics.get("timed_out"):
        lines.append("Checker timed out (inconclusive).")
    if count:
        tally: dict[str, int] = {}
        for c in classes:
            tally[c] = tally.get(c, 0) + 1
        summary = ", ".join(f"{c}×{n}" if n > 1 else c for c, n in tally.items())
        lines.append(f"{count} error(s): {summary}.")
    first = diagnostics.get("first_error")
    if first:
        where = f"line {first['line']}" if first.get("line") is not None else "unknown line"
        lines.append(f"First error ({where}, {first['class']}):\n{first['message']}")
    goal = diagnostics.get("unsolved_goal")
    if goal:
        lines.append(f"Unsolved goal:\n{goal}")
    if diagnostics.get("sorry_warnings"):
        lines.append(f"{diagnostics['sorry_warnings']} declaration(s) use `sorry`.")
    if count:
        lines.append(
            "Repairable: fix the first error and resubmit."
            if diagnostics.get("repairable")
            else "Many errors: consider restructuring the proof rather than patching."
        )
    return "\n".join(lines)


__all__ = ["ERROR_CLASSES", "REPAIRABLE_MAX_ERRORS", "classify_error", "render", "summarize"]
