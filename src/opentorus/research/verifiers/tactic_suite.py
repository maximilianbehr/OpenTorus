"""Automatic tactic-suite pass for Lean candidates whose only gaps are ``sorry``s.

A model often writes a correct proof skeleton and leaves the easy leaves as ``sorry``.
Before spending another model turn, try a fixed list of closing tactics on each one
(the open-math-harness ``complete`` step, ``program-files/lean/src/completion.rs``):

1. the candidate must elaborate with no error other than its ``sorry`` warnings
   (under ``set_option maxHeartbeats 100000``);
2. for each ``sorry``, its syntactic position is decided by splicing ``by sorry``
   there (a parse error means tactic position, else term position);
3. each tactic of :data:`SUITE` is spliced at that one ``sorry`` — ``tac`` in tactic
   position, ``(by tac)`` in term position — and the whole file re-elaborated; the
   first splice with no error closes it (an ``exact?`` closer is replaced by its
   ``Try this:`` suggestion);
4. when every ``sorry`` closes, all closers are spliced at once and the result is
   returned. The caller re-verifies it through the **full gate** (``sorry``/axiom/
   statement checks) — this module never accepts anything itself.

:func:`hollow_sorries` flags a ``have`` that merely restates the theorem's goal and is
closed by ``sorry``: the whole proof is hiding in that one gap.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opentorus.research.verifiers import lean_rules

if TYPE_CHECKING:
    from opentorus.research.verifiers.backends import Lean4Backend

SUITE: tuple[str, ...] = (
    "rfl",
    "simp",
    "omega",
    "norm_num",
    "linarith",
    "nlinarith",
    "positivity",
    "decide",
    "aesop",
    "exact?",
)
HEARTBEATS = 100000
MAX_SORRIES = 6
WALL_SECONDS = 900.0


@dataclass
class SuiteResult:
    attempted: bool
    reason: str = ""
    sorries: int = 0
    closers: dict[int, str] = field(default_factory=dict)
    spliced: str | None = None
    hollow: list[int] = field(default_factory=list)

    @property
    def all_closed(self) -> bool:
        return self.spliced is not None


def sorry_spans(source: str) -> list[tuple[int, int]]:
    """Offsets of each ``sorry`` token in code (comments/strings excluded)."""
    try:
        code = lean_rules.lean_code(source)
    except lean_rules.LeanSourceError:
        return []
    spans = []
    for m in re.finditer(r"sorry", code):
        before = code[m.start() - 1] if m.start() > 0 else " "
        after = code[m.end()] if m.end() < len(code) else " "
        if not lean_rules.is_id_rest(before) and not lean_rules.is_id_rest(after):
            spans.append((m.start(), m.end()))
    return spans


def splice(source: str, spans: dict[tuple[int, int], str]) -> str:
    out = source
    for (start, end), text in sorted(spans.items(), reverse=True):
        out = out[:start] + text + out[end:]
    return out


def with_heartbeats(source: str, heartbeats: int = HEARTBEATS) -> str:
    """``source`` with ``set_option maxHeartbeats N`` after its import header."""
    lines = source.split("\n")
    last_import = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import "):
            last_import = i
        elif stripped and not stripped.startswith("--"):
            break
    lines.insert(last_import + 1, f"set_option maxHeartbeats {heartbeats}")
    return "\n".join(lines)


_TRY_THIS = re.compile(r"Try this:\s*(.+)")


def run_suite(
    backend: Lean4Backend,
    source: str,
    *,
    max_sorries: int = MAX_SORRIES,
    wall_seconds: float = WALL_SECONDS,
) -> SuiteResult:
    """Try to close every ``sorry`` of ``source``; see the module docstring."""
    bad = lean_rules.forbidden_token(source, allow_sorry=True)
    if bad:
        return SuiteResult(attempted=False, reason=f"forbidden token {bad!r}")
    spans = sorry_spans(source)
    result = SuiteResult(attempted=False, sorries=len(spans), hollow=hollow_sorries(source))
    if not spans:
        result.reason = "no sorry to close"
        return result
    if len(spans) > max_sorries:
        result.reason = f"{len(spans)} sorries exceed the suite's cap of {max_sorries}"
        return result
    baseline = backend.check_partial(with_heartbeats(source))
    if not baseline.ran:
        result.reason = f"partial check did not run ({baseline.refused})"
        return result
    if baseline.errors:
        result.reason = "the candidate has errors besides its sorries"
        return result
    result.attempted = True
    deadline = time.monotonic() + wall_seconds
    for index, span in enumerate(spans):
        if time.monotonic() > deadline:
            result.reason = "wall-clock budget exhausted"
            break
        probe = backend.check_partial(with_heartbeats(splice(source, {span: "by sorry"})))
        tactic_position = probe.ran and "syntax" in (probe.classes or [])
        for tac in SUITE:
            if time.monotonic() > deadline:
                break
            text = tac if tactic_position else f"(by {tac})"
            check = backend.check_partial(with_heartbeats(splice(source, {span: text})))
            if not check.ran or check.errors:
                continue
            if tac == "exact?":
                suggestion = _TRY_THIS.search(check.output)
                if suggestion is None:
                    continue
                exact = suggestion.group(1).strip()
                text = exact if tactic_position else f"(by {exact})"
                recheck = backend.check_partial(with_heartbeats(splice(source, {span: text})))
                if not recheck.ran or recheck.errors:
                    continue
            result.closers[index] = text
            break
    if len(result.closers) == len(spans):
        result.spliced = splice(source, {spans[i]: t for i, t in result.closers.items()})
        result.reason = "every sorry closed"
    elif not result.reason:
        result.reason = f"closed {len(result.closers)} of {len(spans)} sorries"
    return result


def _conclusion(signature: str) -> str | None:
    """The type after the last top-level ``:`` of a theorem signature."""
    depth = 0
    last = -1
    for i, ch in enumerate(signature):
        if ch in "([{⦃⟨":
            depth += 1
        elif ch in ")]}⦄⟩":
            depth -= 1
        elif ch == ":" and depth == 0 and signature[i + 1 : i + 2] != "=":
            last = i
    return signature[last + 1 :].strip() if last >= 0 else None


def hollow_sorries(source: str) -> list[int]:
    """Indices (into :func:`sorry_spans`) of ``have … : <goal> := sorry`` restatements.

    Mechanical and conservative: the ``have`` type must equal, whitespace-normalized,
    the conclusion of the enclosing theorem's signature (binders are not matched).
    """
    try:
        code = lean_rules.lean_code(source)
    except lean_rules.LeanSourceError:
        return []
    spans = sorry_spans(source)
    hollow: list[int] = []
    decls = list(re.finditer(r"(?m)(?:theorem|lemma)\s+\S+(.*?):=", code, re.S))
    for idx, (start, _end) in enumerate(spans):
        owner = None
        for d in decls:
            if d.start() < start:
                owner = d
        if owner is None:
            continue
        goal = _conclusion(owner.group(1))
        if not goal:
            continue
        window = code[max(owner.end(), code.rfind("have", 0, start)) : start]
        m = re.search(r"have\s+(?:\S+\s*)?:\s*(.*?):=\s*(?:by\s*)?$", window, re.S)
        if m and " ".join(m.group(1).split()) == " ".join(goal.split()):
            hollow.append(idx)
    return hollow


__all__ = [
    "HEARTBEATS",
    "SUITE",
    "SuiteResult",
    "hollow_sorries",
    "run_suite",
    "sorry_spans",
    "splice",
    "with_heartbeats",
]
