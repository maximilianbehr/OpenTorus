"""A generic phase machine over an explicit transition table.

Nothing here knows about campaigns: it takes any ``Enum`` and a mapping from each
phase to the phases it may move to, and answers "may I?" or raises. Keeping it
generic lets the campaign phases, a worker's own sub-phases and tests share one
implementation, and keeps the transition table — the actual policy — visible as
data instead of scattered ``if`` chains.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Generic, TypeVar

from opentorus.errors import OpenTorusError

P = TypeVar("P", bound=Enum)


class InvalidTransition(OpenTorusError):
    """A transition the table does not allow was requested."""

    def __init__(self, source: Enum, target: Enum, allowed: Iterable[Enum]) -> None:
        names = ", ".join(sorted(str(a.value) for a in allowed)) or "none"
        super().__init__(
            f"Invalid transition {source.value} -> {target.value} (allowed from "
            f"{source.value}: {names})."
        )
        self.source = source
        self.target = target


class PhaseMachine(Generic[P]):
    """Answers transition questions from a ``{phase: frozenset(next phases)}`` table.

    A phase absent from the table is terminal: nothing leads out of it. The table is
    copied and frozen at construction so a machine cannot drift after it is built.
    """

    def __init__(self, transitions: Mapping[P, frozenset[P] | set[P]]) -> None:
        self._transitions: dict[P, frozenset[P]] = {
            phase: frozenset(targets) for phase, targets in transitions.items()
        }

    @property
    def transitions(self) -> Mapping[P, frozenset[P]]:
        return dict(self._transitions)

    def allowed(self, source: P) -> frozenset[P]:
        """The phases reachable in one step from ``source`` (empty when terminal)."""
        return self._transitions.get(source, frozenset())

    def is_terminal(self, phase: P) -> bool:
        return not self.allowed(phase)

    def can_transition(self, source: P, target: P) -> bool:
        return target in self.allowed(source)

    def assert_transition(self, source: P, target: P) -> None:
        """Raise :class:`InvalidTransition` unless ``source -> target`` is in the table."""
        if not self.can_transition(source, target):
            raise InvalidTransition(source, target, self.allowed(source))
