from __future__ import annotations
from forgeloop.feedback.types import FeedbackSignal


def render(signal: FeedbackSignal) -> str:
    if signal.passed:
        return f"[FEEDBACK] {signal.source_tool} (action {signal.source_action_id}) -> PASSED ({signal.summary}). Task may be complete; consider calling done."
    lines = [f"[FEEDBACK] {signal.source_tool} (action {signal.source_action_id}) -> FAILED", f"Summary: {signal.summary}", "Failures:"]
    for i, f in enumerate(signal.failures, 1):
        loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or f.id)
        lines.append(f"{i}. {f.id} ({loc}) [{f.classification}]")
        if f.message:
            lines.append(f"   {f.message}")
    lines.append("Next: address the failures above. Read the failing tests and the code under test before editing.")
    return "\n".join(lines)
