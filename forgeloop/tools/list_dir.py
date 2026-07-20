from __future__ import annotations
import os
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_ENTRIES = 500


class ListDirTool:
    name = "list_dir"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        path = args.get("path", ".")
        recursive = args.get("recursive", False)
        fence = fence_path(path, ws, mode="read", read_allowlist=ctx.get("read_allowlist", []))
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "path_outside_workspace", "message": fence.reason}, truncated=False)
        full = fence.resolved
        if not os.path.exists(full):
            return ToolResult(ok=False, result=None, error={"code": "not_found", "message": f"{path} not found"}, truncated=False)
        if not os.path.isdir(full):
            return ToolResult(ok=False, result=None, error={"code": "not_a_dir", "message": f"{path} not a dir"}, truncated=False)
        entries = []
        truncated = False
        if recursive:
            for root, dirs, files in os.walk(full):
                for name in sorted(dirs + files):
                    p = os.path.join(root, name)
                    entries.append({"name": os.path.relpath(p, full), "type": "dir" if os.path.isdir(p) else "file", "size": os.path.getsize(p) if os.path.isfile(p) else 0})
                    if len(entries) >= MAX_ENTRIES:
                        truncated = True
                        break
                if truncated:
                    break
        else:
            for name in sorted(os.listdir(full)):
                p = os.path.join(full, name)
                entries.append({"name": name, "type": "dir" if os.path.isdir(p) else "file", "size": os.path.getsize(p) if os.path.isfile(p) else 0})
                if len(entries) >= MAX_ENTRIES:
                    truncated = True
                    break
        return ToolResult(ok=True, result={"path": path, "entries": entries, "truncated": truncated}, error=None, truncated=truncated)
