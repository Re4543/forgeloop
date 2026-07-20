from forgeloop.tools.run_tests import RunTestsTool


def test_run_tests_returns_raw_stdout(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    t = RunTestsTool()
    r = t.execute({"target": "tests"}, ctx={"workspace_root": str(tmp_path)})
    assert r.ok is True
    assert "passed" in r.result["stdout"]
    assert r.result["exit_code"] == 0


def test_run_tests_failing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert 1 == 2\n", encoding="utf-8")
    t = RunTestsTool()
    r = t.execute({"target": "tests"}, ctx={"workspace_root": str(tmp_path)})
    assert r.ok is True
    assert r.result["exit_code"] == 1
    assert "failed" in r.result["stdout"]
