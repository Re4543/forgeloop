from pathlib import Path
from forgeloop.feedback.test_parser import TestParser
from forgeloop.feedback.lint_parser import LintParser

FIX = Path(__file__).parent / "fixtures"


def test_parse_2_failed():
    stdout = (FIX / "pytest_output" / "2_failed.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "test"
    assert sig.passed is False
    assert sig.stats["failed"] == 2
    assert sig.stats["passed"] == 10
    assert len(sig.failures) == 2
    assert sig.failures[0].classification == "assertion_failure"
    assert sig.failures[1].classification == "import_error"
    assert sig.failures[0].file == "tests/test_foo.py"


def test_parse_all_passed():
    stdout = (FIX / "pytest_output" / "all_passed.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=0, action_id="a1")
    assert sig.passed is True
    assert sig.stats["passed"] == 12
    assert sig.failures == []


def test_parse_garbage_degrades_to_raw():
    stdout = (FIX / "pytest_output" / "garbage.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "raw"
    assert "random text" in sig.raw_excerpt


def test_parse_collection_error():
    stdout = (FIX / "pytest_output" / "collection_error.txt").read_text(encoding="utf-8")
    sig = TestParser().parse(stdout, exit_code=2, action_id="a1")
    assert sig.passed is False
    assert sig.kind in ("raw", "test")


def test_lint_parse_basic():
    stdout = (FIX / "ruff_output" / "basic.txt").read_text(encoding="utf-8")
    sig = LintParser().parse(stdout, exit_code=1, action_id="a1")
    assert sig.kind == "lint"
    assert sig.passed is False
    assert len(sig.failures) == 2
    assert sig.failures[0].file == "src/a.py"
    assert sig.failures[0].line == 3
    assert sig.failures[0].col == 5
    assert sig.failures[0].code == "F841"
