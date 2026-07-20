from forgeloop.agent.session import SessionStatus, is_terminal
from forgeloop.agent.shutdown import check_shutdown, BreakerState
from forgeloop.config.loader import load_config


def test_terminal_states():
    assert is_terminal("COMPLETED")
    assert is_terminal("FAILED_PARSE")
    assert is_terminal("STOPPED_MAX_ROUNDS")
    assert not is_terminal("RUNNING")
    assert not is_terminal("PENDING_APPROVAL")


def test_max_rounds():
    cfg = load_config([])
    state = BreakerState(round_count=51, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_MAX_ROUNDS"


def test_hard_breaker():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=3, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_FAILURE_BREAKER"


def test_loop_breaker():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=3, last_action_hash="abc", last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "STOPPED_LOOP"


def test_no_shutdown_when_running():
    cfg = load_config([])
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state=None)
    assert check_shutdown(state, cfg, max_rounds=50) == "RUNNING"


def test_done_post_check_blocks_success_when_tests_failed():
    cfg = load_config([])
    cfg.done_post_check["require_green_tests"] = True
    state = BreakerState(round_count=5, consecutive_failures=0, consecutive_identical=0, last_action_hash=None, last_test_state={"passed": False, "failed": 2})
    result = check_shutdown(state, cfg, max_rounds=50, done_called=True, done_success=True)
    assert result == "RUNNING"
