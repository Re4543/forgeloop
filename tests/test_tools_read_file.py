from forgeloop.tools.read_file import ReadFileTool


def test_read_existing(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "src/main.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "print('hi')" in r.result["content"]


def test_read_missing(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "nope.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "file_not_found"


def test_read_outside_workspace(tmp_workspace):
    t = ReadFileTool()
    r = t.execute({"path": "../etc/passwd"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"
