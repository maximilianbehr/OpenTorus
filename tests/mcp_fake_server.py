"""A configurable fake stdio MCP server for the hardening tests.

Tools: ``pid`` (returns the server's pid), ``env`` (returns its environment as
JSON), ``sleep`` (sleeps ``seconds`` before answering), ``huge`` (answers with a
single >1 MiB line), and ``lookup`` (read-only annotated). Appends its pid to
``$FAKE_MCP_PIDFILE`` when set.
"""

from __future__ import annotations

import json
import os
import sys
import time

_TOOLS = [
    {"name": "pid", "description": "server pid", "inputSchema": {"type": "object"}},
    {"name": "env", "description": "server env", "inputSchema": {"type": "object"}},
    {"name": "sleep", "description": "sleep", "inputSchema": {"type": "object"}},
    {"name": "huge", "description": "huge reply", "inputSchema": {"type": "object"}},
    {
        "name": "lookup",
        "description": "read-only lookup",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    },
]


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _text(req_id: object, text: str) -> None:
    result = {"content": [{"type": "text", "text": text}]}
    _write({"jsonrpc": "2.0", "id": req_id, "result": result})


def main() -> None:
    pidfile = os.environ.get("FAKE_MCP_PIDFILE")
    if pidfile:
        with open(pidfile, "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n")
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            continue
        req_id = request.get("id")
        method = request.get("method")
        if req_id is None:
            continue
        if method == "initialize":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}})
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})
        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "pid":
                _text(req_id, str(os.getpid()))
            elif name == "env":
                _text(req_id, json.dumps(dict(os.environ)))
            elif name == "sleep":
                time.sleep(float(args.get("seconds", 10)))
                _text(req_id, "slept")
            elif name == "huge":
                _text(req_id, "x" * (2 << 20))
            else:
                _text(req_id, "looked up")


if __name__ == "__main__":
    main()
