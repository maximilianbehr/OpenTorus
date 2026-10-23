"""Failure classes and bounded, class-aware retries for provider calls.

A failed model call is worth repeating only when another attempt may not meet the
same failure. The classes, after the harness reference (``chat-agent`` ``retry.rs``):

* ``ANSWERED_TRANSIENT`` — the provider answered 408/409/425/429/5xx: it is up but
  busy or briefly broken. Retried with a *long* backoff (Retry-After honoured).
* ``UNREACHABLE`` — no answer at all (connection refused/reset before a response).
  Retried with a *short* backoff: a restarting local server is back in seconds.
* ``CONTEXT_LENGTH`` — the request does not fit the model's context window. Never
  retried as is: the caller compacts once and asks again (``ContextLengthExceededError``).
* ``TIMEOUT`` — the configured wait for one request ran out; another attempt would
  only extend it, so it is not retried.
* ``PERMANENT`` — any other 4xx (auth, validation, unknown model): it will not change.

Backoff is deterministic (no jitter) so runs stay reproducible. Every attempt is a
complete, fresh request; nothing of a failed attempt enters the history.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

from opentorus.errors import ProviderError

_logger = logging.getLogger("opentorus.providers")

T = TypeVar("T")


class FailureClass(StrEnum):
    ANSWERED_TRANSIENT = "answered_transient"
    UNREACHABLE = "unreachable"
    CONTEXT_LENGTH = "context_length"
    TIMEOUT = "timeout"
    PERMANENT = "permanent"


RETRYABLE = frozenset({FailureClass.ANSWERED_TRANSIENT, FailureClass.UNREACHABLE})
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429})

# Long backoff for a provider that answered "not now"; short for one that did not answer.
ANSWERED_BASE_SECONDS = 2.0
ANSWERED_MAX_SECONDS = 60.0
UNREACHABLE_BASE_SECONDS = 0.5
UNREACHABLE_MAX_SECONDS = 8.0
RETRY_AFTER_MAX_SECONDS = 120.0

# The wordings providers use for "the prompt does not fit": OpenAI
# (context_length_exceeded / "maximum context length is"), vLLM ("This model's maximum
# context length is 262144 tokens. However, you requested …", "longer than the maximum
# model length"), Anthropic ("prompt is too long"), llama.cpp ("exceeds the available
# context size"), Ollama/others ("context length exceeded", "context window").
_CONTEXT_LENGTH = re.compile(
    r"context[_ ]length[_ ]exceeded|maximum context length|max(?:imum)?[_ ]model[_ ]len"
    r"|longer than the maximum model length|prompt is too long|exceeds? the (?:available )?"
    r"context|context window (?:is )?(?:full|exceeded)|too many tokens in (?:the )?prompt",
    re.IGNORECASE,
)


class ContextLengthExceededError(ProviderError):
    """The request did not fit the model's context window.

    The agent loop answers it by compacting the session once and asking again; a
    second one in the same run is reported, not retried.
    """


def is_context_length_message(text: str) -> bool:
    return bool(_CONTEXT_LENGTH.search(text or ""))


def classify_status(status: int | None, body: str = "") -> FailureClass:
    """Failure class of an HTTP answer (``status`` None = no answer at all)."""
    if status is None:
        return FailureClass.UNREACHABLE
    if is_context_length_message(body) and 400 <= status < 500:
        return FailureClass.CONTEXT_LENGTH
    if status in _TRANSIENT_STATUS or status >= 500:
        return FailureClass.ANSWERED_TRANSIENT
    return FailureClass.PERMANENT


def backoff_seconds(failure: FailureClass, attempt: int, retry_after: float | None = None) -> float:
    """Wait before retry number ``attempt`` (0-based) for a failure of this class."""
    if failure is FailureClass.ANSWERED_TRANSIENT:
        if retry_after is not None and retry_after >= 0:
            return min(RETRY_AFTER_MAX_SECONDS, float(retry_after))
        return min(ANSWERED_MAX_SECONDS, ANSWERED_BASE_SECONDS * (2**attempt))
    return min(UNREACHABLE_MAX_SECONDS, UNREACHABLE_BASE_SECONDS * (2**attempt))


def parse_retry_after(value: object) -> float | None:
    """Seconds from a ``Retry-After`` header value (delta-seconds form only)."""
    if value is None:
        return None
    try:
        return max(0.0, float(str(value).strip()))
    except ValueError:
        return None


# Indirection so the test suite can make backoff instantaneous (tests/conftest.py).
_sleep: Callable[[float], None] = time.sleep


class RetryableFailure(Exception):
    """Raised by an attempt to say: this failed with ``failure``; maybe retry.

    ``error`` is what the caller raises once retries are spent (or immediately for a
    non-retryable class).
    """

    def __init__(
        self, failure: FailureClass, error: BaseException, retry_after: float | None = None
    ) -> None:
        super().__init__(str(error))
        self.failure = failure
        self.error = error
        self.retry_after = retry_after


def call_with_retries(
    attempt: Callable[[], T],
    *,
    max_retries: int,
    label: str = "provider",
) -> T:
    """Run ``attempt`` until it returns, retrying only retryable failure classes.

    ``attempt`` signals a classified failure by raising :class:`RetryableFailure`;
    anything else propagates unchanged. At most ``max_retries`` further attempts.
    """
    tries = 0
    while True:
        try:
            return attempt()
        except RetryableFailure as failed:
            if failed.failure not in RETRYABLE or tries >= max(0, int(max_retries)):
                raise failed.error from failed.error.__cause__
            wait = backoff_seconds(failed.failure, tries, failed.retry_after)
            tries += 1
            _logger.info(
                "%s call failed (%s: %s); retry %d of %d in %.1fs",
                label,
                failed.failure.value,
                str(failed.error)[:200],
                tries,
                max_retries,
                wait,
            )
            _sleep(wait)


__all__ = [
    "ContextLengthExceededError",
    "FailureClass",
    "RetryableFailure",
    "backoff_seconds",
    "call_with_retries",
    "classify_status",
    "is_context_length_message",
    "parse_retry_after",
]
