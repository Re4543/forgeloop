from __future__ import annotations
from forgeloop.tools.base import ToolResult


class DoneTool:
    name = "done"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        summary = args.get("summary", "")
        success = bool(args.get("success", False))
        return ToolResult(ok=True, result={"terminal": True, "summary": summary, "success": success}, error=None, truncated=False)
