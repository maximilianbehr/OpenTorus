"""Injectable clocks: the only place the campaign layer reads the time.

Every timestamp in a campaign event comes from a :class:`Clock` handed to the
store and the engine, never from ``datetime.now`` inline. That is what makes two
mock runs in fresh workspaces produce byte-identical event logs (``StepClock``)
and what keeps the reducer pure (it copies event timestamps; it never asks a clock).
``SystemClock`` is the production clock and the sole ``datetime.now`` call in this
package — a structural test greps for others.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that answers ``now()`` with a timezone-aware UTC datetime."""

    def now(self) -> datetime: ...


class SystemClock:
    """The wall clock, in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Always the same instant — for tests that want identical timestamps."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        self._at = at

    def now(self) -> datetime:
        return self._at


class StepClock:
    """A clock that advances by a fixed step on every call.

    Deterministic *and* strictly increasing, so ordering-by-timestamp behaves like
    the real thing while two runs still agree to the microsecond.
    """

    def __init__(self, start: datetime | None = None, step_seconds: float = 1.0) -> None:
        if start is None:
            start = datetime(2026, 1, 1, tzinfo=UTC)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        self._next = start
        self._step = timedelta(seconds=step_seconds)
        self.calls = 0

    def now(self) -> datetime:
        current = self._next
        self._next = current + self._step
        self.calls += 1
        return current

    def peek(self) -> datetime:
        """The instant the next ``now()`` will return (does not advance)."""
        return self._next
