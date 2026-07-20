from forgeloop.tools.run_shell import RunShellTool


def test_echo(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "echo hi"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert r.result["exit_code"] == 0
    assert "hi" in r.result["stdout"]


def test_env_filters_keys(tmp_workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    t = RunShellTool()
    r = t.execute({"command": "echo %OPENAI_API_KEY%"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "sk-secret" not in r.result["stdout"]


def test_timeout(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "ping -n 10 127.0.0.1", "timeout": 1}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "timeout"


def test_cwd_outside(tmp_workspace):
    t = RunShellTool()
    r = t.execute({"command": "echo hi", "cwd": ".."}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "cwd_outside_workspace"
