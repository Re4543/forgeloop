from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from forgeloop.parser.types import Action


@dataclass
class ToolResult:
    ok: bool
    result: dict | None
    error: dict | None
    truncated: bool = False


class Tool(Protocol):
    name: str
    def execute(self, args: dict, ctx: dict) -> ToolResult: ...


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def dispatch(self, action: Action, ctx: dict) -> ToolResult:
        tool = self._tools.get(action.tool)
        if tool is None:
            return ToolResult(ok=False, result=None, error={"code": "unknown_tool", "message": f"no tool named {action.tool!r}"}, truncated=False)
        return tool.execute(action.args, ctx)
