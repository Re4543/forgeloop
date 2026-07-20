import os
import pytest
from forgeloop.governance.path_fence import fence_path


def test_dotdot_traversal_denied(tmp_workspace):
    r = fence_path("../etc/passwd", str(tmp_workspace), mode="write")
    assert r.allowed is False


def test_dotdot_within_workspace_allowed(tmp_workspace):
    (tmp_workspace / "sub").mkdir()
    (tmp_workspace / "sub" / "a.py").write_text("x", encoding="utf-8")
    r = fence_path("sub/../a.py", str(tmp_workspace), mode="write")
    assert r.allowed is True


def test_symlink_escape_denied(tmp_workspace):
    link = tmp_workspace / "link"
    try:
        os.symlink(os.path.dirname(str(tmp_workspace)), link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform/user")
    r = fence_path("link/x", str(tmp_workspace), mode="write")
    assert r.allowed is False


def test_read_allowlist(tmp_workspace):
    allowlisted = tmp_workspace.parent / "allowlisted"
    allowlisted.mkdir()
    target = str(allowlisted / "foo")
    r = fence_path(target, str(tmp_workspace), mode="read", read_allowlist=[str(allowlisted)])
    assert r.allowed is True


def test_write_always_fenced():
    r = fence_path("/etc/passwd", "/tmp/ws", mode="write")
    assert r.allowed is False
