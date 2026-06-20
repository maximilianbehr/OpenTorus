"""OpenTorus exception hierarchy.

All recoverable, user-facing failures inherit from :class:`OpenTorusError` so the
CLI can render them as helpful, actionable messages instead of raw tracebacks.
"""

from __future__ import annotations


class OpenTorusError(Exception):
    """Base class for all OpenTorus errors."""


class PathTraversalError(OpenTorusError):
    """Raised when a path would escape the workspace root."""


class WorkspaceError(OpenTorusError):
    """Raised for workspace initialization or discovery problems."""


class ConfigError(OpenTorusError):
    """Raised when configuration cannot be loaded or is invalid."""


class PermissionDeniedError(OpenTorusError):
    """Raised when an action is denied by the permission policy."""


class ProviderError(OpenTorusError):
    """Raised when a model provider is misconfigured or unavailable."""


def is_recoverable_tool_parse_error(exc: Exception) -> bool:
    """True when the provider failed because model tool-call JSON was invalid."""
    msg = str(exc).lower()
    needles = (
        "error parsing tool call",
        "failed to parse json",
        "unexpected end of json input",
        "parse tool call",
        "invalid character",
    )
    return isinstance(exc, ProviderError) and any(n in msg for n in needles)
