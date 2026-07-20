from __future__ import annotations
import subprocess
import sys
import time
from forgeloop.tools.base import ToolResult
from forgeloop.governance.path_fence import fence_path

MAX_OUTPUT = 10240


class RunTestsTool:
    name = "run_tests"

    def execute(self, args: dict, ctx: dict) -> ToolResult:
        ws = ctx["workspace_root"]
        target = args.get("target", "tests")
        extra = args.get("args", [])
        fence = fence_path(target, ws, mode="read")
        if not fence.allowed:
            return ToolResult(ok=False, result=None, error={"code": "target_outside_workspace", "message": fence.reason}, truncated=False)
        cmd = [sys.executable, "-m", "pytest", fence.resolved, "--tb=short", "-ra", "-q"] + list(extra)
        start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ws)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, result=None, error={"code": "timeout", "message": "pytest timed out"}, truncated=False)
        except FileNotFoundError:
            return ToolResult(ok=False, result=None, error={"code": "pytest_not_installed", "message": "pytest not found"}, truncated=False)
        duration = int((time.perf_counter() - start) * 1000)
        stdout = proc.stdout or ""
        truncated = len(stdout) > MAX_OUTPUT
        if truncated:
            stdout = stdout[:MAX_OUTPUT]
        return ToolResult(
            ok=True,
            result={"command": " ".join(cmd), "exit_code": proc.returncode, "stdout": stdout, "duration_ms": duration},
            error=None,
            truncated=truncated,
        )
