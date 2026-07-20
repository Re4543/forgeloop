from __future__ import annotations
import os
import re
import subprocess
import sys
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_OUTPUT = 10240
_SENSITIVE_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


def _filtered_env() -> dict:
    return {k: v for k, v in os.environ.items() if not _SENSITIVE_RE.search(k)}


class RunShellTool:
    name = "run_shell"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        command = args.get("command", "")
        cwd = args.get("cwd", ".")
        timeout = args.get("timeout", 60)
        fence = fence_path(cwd, ws, mode="read")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "cwd_outside_workspace", "message": fence.reason}, truncated=False)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=fence.resolved,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_filtered_env(),
                executable=(os.environ.get("COMSPEC") or "cmd.exe") if sys.platform == "win32" else "/bin/sh",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, result=None, error={"code": "timeout", "message": f"timed out after {timeout}s"}, truncated=False)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        truncated = False
        if len(stdout) > MAX_OUTPUT:
            stdout = stdout[:MAX_OUTPUT]
            truncated = True
        if len(stderr) > MAX_OUTPUT:
            stderr = stderr[:MAX_OUTPUT]
            truncated = True
        return ToolResult(
            ok=True,
            result={"command": command, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr, "duration_ms": 0, "timed_out": False},
            error=None,
            truncated=truncated,
        )
