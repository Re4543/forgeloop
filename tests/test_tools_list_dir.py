from forgeloop.tools.list_dir import ListDirTool


def test_list_flat(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": "src"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    names = [e["name"] for e in r.result["entries"]]
    assert "main.py" in names


def test_list_outside(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": ".."}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"


def test_list_not_a_dir(tmp_workspace):
    t = ListDirTool()
    r = t.execute({"path": "src/main.py"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "not_a_dir"
