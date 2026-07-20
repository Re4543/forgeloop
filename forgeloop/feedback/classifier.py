from __future__ import annotations
import re
from forgeloop.feedback.types import FeedbackSignal
from forgeloop.feedback.test_parser import TestParser
from forgeloop.feedback.lint_parser import LintParser


class FeedbackClassifier:
    def classify(self, tool_name: str, command: str, stdout: str, exit_code: int, action_id: str) -> FeedbackSignal:
        if tool_name == "run_tests":
            return TestParser().parse(stdout, exit_code, action_id)
        if tool_name == "run_shell" and re.match(r"^(ruff|flake8)\b", command):
            return LintParser().parse(stdout, exit_code, action_id)
        return FeedbackSignal(
            kind="raw", source_tool=tool_name, source_action_id=action_id,
            passed=(exit_code == 0), summary=f"exit_code={exit_code}",
            failures=[], stats=None, raw_excerpt=stdout[:2000],
        )
