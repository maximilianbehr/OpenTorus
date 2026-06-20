"""A tiny stub MCP server for tests.

Speaks the minimal stdio JSON-RPC subset OpenTorus uses: ``initialize``,
``tools/list`` (exposes an ``echo`` tool), and ``tools/call``. It runs as a
subprocess driven by the McpClient under test; no network involved.
"""

from __future__ import annotations

import json
import sys


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        req_id = request.get("id")
        if req_id is None:
            # A notification (e.g. notifications/initialized); nothing to answer.
            continue
        if method == "initialize":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}})
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo the provided text back.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            }
                        ]
                    },
                }
            )
        elif method == "tools/call":
            params = request.get("params", {})
            text = params.get("arguments", {}).get("text", "")
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"echoed: {text}"}]},
                }
            )
        else:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                }
            )


if __name__ == "__main__":
    main()
