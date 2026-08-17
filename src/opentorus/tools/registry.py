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

    def resolve(self, name: str) -> tuple[Tool | None, str]:
        """Look up a tool, tolerating whitespace a model dropped inside the name.

        Returns the tool and the name it was found under. No registered tool contains
        whitespace — not the builtins and not the ``mcp__server__tool`` form — so
        ``"read_ file"`` can only mean ``read_file``, and answering "unknown tool" to it
        is a true statement about a name the model never meant to write. Observed 39
        times across four runs (``read_ file``, ``paper_ fetch``, ``list_ files``,
        ``write_ file``, ``glob_ files``, ``exp_ new``, ``exp_ run``), one run spending
        25 of its 76 actions on it while the reply listed every available tool.
        """
        tool = self._tools.get(name)
        if tool is not None:
            return tool, name
        compact = "".join(name.split())
        if compact != name:
            recovered = self._tools.get(compact)
            if recovered is not None:
                return recovered, compact
        return None, name

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict]:
        """Return provider-neutral tool specs for all registered tools."""
        return [tool.to_spec() for tool in self._tools.values()]
