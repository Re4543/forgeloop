from forgeloop.tools.write_file import WriteFileTool


def test_overwrite_new(tmp_workspace):
    t = WriteFileTool()
    r = t.execute({"path": "src/new.py", "mode": "overwrite", "content": "x = 1\n"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert (tmp_workspace / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


def test_edit_unique_match(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "return 1", "new_string": "return 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert "return 2" in (tmp_workspace / "src" / "main.py").read_text(encoding="utf-8")


def test_edit_ambiguous(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "x = 1", "new_string": "x = 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "old_string_ambiguous"


def test_edit_not_found(tmp_workspace):
    (tmp_workspace / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    t = WriteFileTool()
    r = t.execute({"path": "src/main.py", "mode": "edit", "old_string": "nope", "new_string": "x = 2"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "old_string_not_found"


def test_write_outside_workspace(tmp_workspace):
    import os
    t = WriteFileTool()
    r = t.execute({"path": "../evil.py", "mode": "overwrite", "content": "x"}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is False
    assert r.error["code"] == "path_outside_workspace"
    assert not os.path.exists(os.path.join(os.path.dirname(str(tmp_workspace)), "evil.py"))
