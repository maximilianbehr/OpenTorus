"""Minimal JSON examples appended to agent tool descriptions."""

from __future__ import annotations

import json


def ex(**kwargs: object) -> str:
    """Return a compact ``Example: {...}`` suffix for tool descriptions."""
    return f" Example: {json.dumps(kwargs, ensure_ascii=False)}."
