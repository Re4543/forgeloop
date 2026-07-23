import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock
from forgeloop.cli import parse_args


def test_parse_args_defaults():
    args = parse_args(["run", "--task", "fix tests"])
    assert args.task == "fix tests"
    assert args.workspace is None
    assert args.config == "./forgeloop.yaml"
    assert args.host is None
    assert args.port is None
    assert args.max_rounds is None


def test_parse_args_all_flags():
    args = parse_args(["run", "--task", "fix tests", "--workspace", "/tmp/ws", "--config", "/etc/fl.yaml", "--host", "0.0.0.0", "--port", "9000", "--max-rounds", "10"])
    assert args.task == "fix tests"
    assert args.workspace == "/tmp/ws"
    assert args.config == "/etc/fl.yaml"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.max_rounds == 10


def test_parse_args_missing_task():
    import pytest
    with pytest.raises(SystemExit):
        parse_args(["run"])


def test_main_runs_agent_loop(tmp_path):
    from forgeloop.cli import main
    import sys

    config_path = tmp_path / "forgeloop.yaml"
    config_path.write_text(
        f"workspace_root: {tmp_path}\n"
        "llm:\n"
        "  model: mock\n"
        "server:\n"
        "  host: 127.0.0.1\n"
        "  port: 0\n"
        "  secret: test-secret\n"
        "agent:\n"
        "  max_rounds: 5\n"
        "  parse_fail_limit: 3\n"
        "  approval_timeout_seconds: 0\n"
        "guardrails:\n"
        "  default_decision: Allow\n"
    )
    argv = ["forgeloop", "run", "--task", "do stuff", "--config", str(config_path), "--workspace", str(tmp_path)]
    with patch.object(sys, "argv", argv):
        with patch("forgeloop.cli.RealLLMProvider") as MockLLM:
            from forgeloop.llm.mock import MockLLMProvider
            MockLLM.return_value = MockLLMProvider(responses=[
                '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
            ])
            exit_code = main()
    assert exit_code == 0
