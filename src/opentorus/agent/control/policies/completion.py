"""Completion policies: "may this run end now?" as an object, not a bare callable."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class CompletionPolicy(Protocol):
    def is_complete(self) -> bool: ...


class CallableCompletion:
    """Adapts a plain ``() -> bool`` (the loop's ``deliverable_complete`` callback)."""

    def __init__(self, fn: Callable[[], bool]) -> None:
        self.fn = fn

    def is_complete(self) -> bool:
        return bool(self.fn())


class NeverComplete:
    """A run that only ends by budget, stall or cancellation (e.g. open exploration)."""

    def is_complete(self) -> bool:
        return False
