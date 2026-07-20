from forgeloop.tools.done import DoneTool


def test_done_returns_terminal(tmp_workspace):
    t = DoneTool()
    r = t.execute({"summary": "all done", "success": True}, ctx={"workspace_root": str(tmp_workspace)})
    assert r.ok is True
    assert r.result["terminal"] is True
    assert r.result["summary"] == "all done"
    assert r.result["success"] is True
