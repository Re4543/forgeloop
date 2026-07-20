from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal, Failure
from forgeloop.feedback.classify_failure import classify_failure

_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERRORS_RE = re.compile(r"(\d+)\s+errors?")
_SKIPPED_RE = re.compile(r"(\d+)\s+skipped")
_FAIL_LINE_RE = re.compile(r"^FAILED\s+(\S+?)\s*-\s*(.+)")


class TestParser:
    def parse(self, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        pm = _PASSED_RE.search(stdout)
        if not pm:
            return FeedbackSignal(
                kind="raw", source_tool="run_tests", source_action_id=action_id,
                passed=(exit_code == 0), summary="unparseable", failures=[],
                stats=None, raw_excerpt=stdout[:2000],
            )
        passed = int(pm.group(1))
        failed = int(m.group(1)) if (m := _FAILED_RE.search(stdout)) else 0
        errors = int(m.group(1)) if (m := _ERRORS_RE.search(stdout)) else 0
        skipped = int(m.group(1)) if (m := _SKIPPED_RE.search(stdout)) else 0
        failures: list[Failure] = []
        for line in stdout.splitlines():
            fm = _FAIL_LINE_RE.match(line)
            if fm:
                fid = fm.group(1)
                rest = fm.group(2)
                type_str = rest.split(":")[0] if ":" in rest else rest
                file_part = fid.split("::")[0] if "::" in fid else fid
                cls = classify_failure(type_str, exit_code, True)
                failures.append(Failure(id=fid, file=file_part, type=type_str, message=rest, classification=cls))
        return FeedbackSignal(
            kind="test", source_tool="run_tests", source_action_id=action_id,
            passed=(failed == 0 and errors == 0 and exit_code == 0),
            summary=f"{passed} passed, {failed} failed, {errors} errors, {skipped} skipped",
            failures=failures,
            stats={"passed": passed, "failed": failed, "errors": errors, "skipped": skipped},
            raw_excerpt=stdout[:2000],
        )
