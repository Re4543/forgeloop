from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal, Failure
from forgeloop.feedback.classify_failure import classify_failure

_LINE_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(\w+)\s+(.+)$")


class LintParser:
    def parse(self, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        failures: list[Failure] = []
        for line in stdout.splitlines():
            m = _LINE_RE.match(line)
            if m:
                failures.append(Failure(
                    id=f"{m.group(1)}:{m.group(2)}:{m.group(3)}",
                    file=m.group(1), line=int(m.group(2)), col=int(m.group(3)),
                    code=m.group(4), message=m.group(5),
                    classification=classify_failure(m.group(4), exit_code, True),
                ))
        return FeedbackSignal(
            kind="lint", source_tool="run_shell", source_action_id=action_id,
            passed=(len(failures) == 0),
            summary=f"{len(failures)} lint violations",
            failures=failures, stats=None, raw_excerpt=stdout[:2000],
        )
