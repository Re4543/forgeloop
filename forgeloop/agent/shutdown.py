from __future__ import annotations
from dataclasses import dataclass
from forgeloop.config.loader import GuardrailsConfig


@dataclass
class BreakerState:
    round_count: int
    consecutive_failures: int
    consecutive_identical: int
    last_action_hash: str | None
    last_test_state: dict | None


def check_shutdown(state: BreakerState, config: GuardrailsConfig, max_rounds: int, done_called: bool = False, done_success: bool = False) -> str:
    if done_called:
        if done_success and config.done_post_check.get("require_green_tests"):
            ts = state.last_test_state
            if ts and (ts.get("failed", 0) > 0 or not ts.get("passed", True)):
                return "RUNNING"
        return "COMPLETED" if done_success else "COMPLETED_WITH_FAILURE"
    if state.consecutive_failures >= 3:
        return "STOPPED_FAILURE_BREAKER"
    if state.consecutive_identical >= 3:
        return "STOPPED_LOOP"
    if state.round_count >= max_rounds:
        return "STOPPED_MAX_ROUNDS"
    return "RUNNING"
