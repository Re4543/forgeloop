from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class FenceResult:
    allowed: bool
    resolved: str
    reason: str = ""


def _resolve(path: str, workspace_root: str) -> str:
    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(workspace_root, path))


def _is_within(resolved: str, workspace_root: str) -> bool:
    ws_real = os.path.realpath(workspace_root)
    try:
        return os.path.commonpath([resolved, ws_real]) == ws_real
    except ValueError:
        return False


def fence_path(path: str, workspace_root: str, mode: str, read_allowlist: list[str] | None = None) -> FenceResult:
    resolved = _resolve(path, workspace_root)
    if mode == "write":
        if not _is_within(resolved, workspace_root):
            return FenceResult(allowed=False, resolved=resolved, reason=f"path {path} outside workspace")
        return FenceResult(allowed=True, resolved=resolved)
    if mode == "read":
        if _is_within(resolved, workspace_root):
            return FenceResult(allowed=True, resolved=resolved)
        for allowed in read_allowlist or []:
            allowed_exp = os.path.realpath(os.path.expanduser(allowed))
            try:
                if os.path.commonpath([resolved, allowed_exp]) == allowed_exp:
                    return FenceResult(allowed=True, resolved=resolved)
            except ValueError:
                continue
        return FenceResult(allowed=False, resolved=resolved, reason=f"path {path} outside workspace and not in allowlist")
    return FenceResult(allowed=False, resolved=resolved, reason=f"unknown mode {mode}")
