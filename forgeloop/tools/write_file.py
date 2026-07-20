from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path


class WriteFileTool:
    name = "write_file"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", "")
        mode = args.get("mode", "overwrite")
        fence = fence_path(path, ws, mode="write")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        try:
            if mode == "overwrite":
                content = args.get("content", "")
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(content)
                return ToolResult(ok=True, result={"path": path, "bytes_written": len(content.encode("utf-8")), "mode": "overwrite"}, error=None, truncated=False)
            if mode == "edit":
                old = args.get("old_string")
                new = args.get("new_string")
                if old is None or new is None:
                    return ToolResult(ok=False, result=None, error={"code": "missing_field", "message": "edit requires old_string and new_string"}, truncated=False)
                if not os.path.isfile(full):
                    return ToolResult(ok=False, result=None, error={"code": "file_not_found", "message": f"{path} not found"}, truncated=False)
                with open(full, "r", encoding="utf-8") as f:
                    text = f.read()
                count = text.count(old)
                if count == 0:
                    return ToolResult(ok=False, result=None, error={"code": "old_string_not_found", "message": "old_string not in file"}, truncated=False)
                if count > 1:
                    return ToolResult(ok=False, result=None, error={"code": "old_string_ambiguous", "message": f"old_string matches {count} times"}, truncated=False)
                new_text = text.replace(old, new, 1)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(new_text)
                return ToolResult(ok=True, result={"path": path, "bytes_written": len(new_text.encode("utf-8")), "mode": "edit"}, error=None, truncated=False)
            return ToolResult(ok=False, result=None, error={"code": "bad_mode", "message": f"unknown mode {mode!r}"}, truncated=False)
        except OSError as e:
            return ToolResult(ok=False, result=None, error={"code": "write_error", "message": str(e)}, truncated=False)
