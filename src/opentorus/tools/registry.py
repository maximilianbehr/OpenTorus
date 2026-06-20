"""A small tool registry.

The registry decouples tool discovery from the agent loop and is the seam where
future plugins register additional tools.
"""

from __future__ import annotations

from opentorus.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict]:
        """Return provider-neutral tool specs for all registered tools."""
        return [tool.to_spec() for tool in self._tools.values()]
