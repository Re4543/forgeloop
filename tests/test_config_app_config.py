from pathlib import Path
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig, load_app_config


def test_load_app_config_defaults(tmp_path):
    cfg = load_app_config(None, {})
    assert cfg.workspace_root == "."
    assert cfg.llm.model == "deepseek-chat"
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8000
    assert cfg.server.secret != ""
    assert len(cfg.server.secret) == 64
    assert cfg.agent.max_rounds == 50
    assert cfg.agent.parse_fail_limit == 3
    assert cfg.agent.approval_timeout_seconds == 86400
    assert cfg.guardrails is not None


def test_load_app_config_from_yaml(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text(
        "workspace_root: /tmp/ws\n"
        "llm:\n"
        "  model: gpt-4o\n"
        "  base_url: https://api.openai.com/v1\n"
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 9000\n"
        "  secret: my-secret\n"
        "agent:\n"
        "  max_rounds: 10\n"
        "  parse_fail_limit: 5\n"
        "  approval_timeout_seconds: 3600\n"
        "guardrails:\n"
        "  default_decision: Allow\n"
    )
    cfg = load_app_config(yaml_path, {})
    assert cfg.workspace_root == "/tmp/ws"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.base_url == "https://api.openai.com/v1"
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 9000
    assert cfg.server.secret == "my-secret"
    assert cfg.agent.max_rounds == 10
    assert cfg.agent.parse_fail_limit == 5
    assert cfg.agent.approval_timeout_seconds == 3600
    assert cfg.guardrails.default_decision == "Allow"


def test_cli_overrides_yaml(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text(
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 9000\n"
        "agent:\n"
        "  max_rounds: 10\n"
    )
    cfg = load_app_config(yaml_path, {"host": "127.0.0.1", "port": 8080, "max_rounds": 20})
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8080
    assert cfg.agent.max_rounds == 20


def test_secret_generated_when_empty(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text("server:\n  secret: ''\n")
    cfg = load_app_config(yaml_path, {})
    assert len(cfg.server.secret) == 64


def test_secret_generated_when_missing(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text("llm:\n  model: x\n")
    cfg = load_app_config(yaml_path, {})
    assert len(cfg.server.secret) == 64
