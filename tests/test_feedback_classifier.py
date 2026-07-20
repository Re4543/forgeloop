from forgeloop.feedback.classifier import FeedbackClassifier
from forgeloop.feedback.renderer import render
from forgeloop.feedback.types import FeedbackSignal, Failure


def test_classifier_routes_run_tests():
    stdout = "2 failed, 10 passed in 3.2s\nFAILED tests/test_foo.py::test_foo - AssertionError: assert 1 == 2\n"
    sig = FeedbackClassifier().classify("run_tests", "", stdout, 1, "a1")
    assert sig.kind == "test"
    assert sig.stats["failed"] == 2


def test_classifier_routes_ruff():
    sig = FeedbackClassifier().classify("run_shell", "ruff check .", "src/a.py:3:5: F841 unused x", 1, "a1")
    assert sig.kind == "lint"
    assert sig.failures[0].code == "F841"


def test_classifier_raw_passthrough():
    sig = FeedbackClassifier().classify("run_shell", "echo hi", "hi\n", 0, "a1")
    assert sig.kind == "raw"


def test_render_failed():
    sig = FeedbackSignal(kind="test", source_tool="run_tests", source_action_id="a1", passed=False, summary="10 passed, 2 failed", failures=[
        Failure(id="tests/test_foo.py::test_foo", file="tests/test_foo.py", line=12, type="AssertionError", message="assert 1==2", classification="assertion_failure"),
    ])
    out = render(sig)
    assert "[FEEDBACK]" in out
    assert "FAILED" in out
    assert "test_foo" in out
    assert "[assertion_failure]" in out


def test_render_passed():
    sig = FeedbackSignal(kind="test", source_tool="run_tests", source_action_id="a1", passed=True, summary="12 passed in 1.5s", failures=[])
    out = render(sig)
    assert "PASSED" in out
    assert "consider calling done" in out
