from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path


class ReadFileTool:
    name = "read_file"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", "")
        offset = args.get("offset", 0)
        limit = args.get("limit", 2000)
        fence = fence_path(path, ws, mode="read", read_allowlist=ctx.get("read_allowlist", []))
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        if not os.path.isfile(full):
            return ToolResult(ok=False, result=None, error={"code": "file_not_found", "message": f"{path} not found"}, truncated=False)
        try:
            with open(full, "rb") as f:
                data = f.read()
            if b"\x00" in data:
                return ToolResult(ok=False, result=None, error={"code": "binary_file", "message": "binary content"}, truncated=False)
            text = data.decode("utf-8", errors="replace")
        except OSError as e:
            return ToolResult(ok=False, result=None, error={"code": "read_error", "message": str(e)}, truncated=False)
        lines = text.splitlines()
        sel = lines[offset:offset + limit]
        content = "\n".join(sel)
        truncated = len(lines) > offset + limit
        return ToolResult(ok=True, result={"path": path, "content": content, "lines": len(sel), "truncated": truncated}, error=None, truncated=truncated)
