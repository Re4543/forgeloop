from __future__ import annotations
import secrets as _secrets
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from forgeloop.config.loader import GuardrailsConfig, load_config
from forgeloop.llm.base import LLMConfig


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    secret: str = ""


@dataclass
class AgentConfig:
    max_rounds: int = 50
    parse_fail_limit: int = 3
    approval_timeout_seconds: int = 86400


@dataclass
class AppConfig:
    workspace_root: str = "."
    llm: LLMConfig = field(default_factory=lambda: LLMConfig(model="deepseek-chat"))
    server: ServerConfig = field(default_factory=ServerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)


def _gen_secret() -> str:
    return _secrets.token_urlsafe(48)[:64]


def load_app_config(config_path: Path | None = None, cli_overrides: dict | None = None) -> AppConfig:
    overrides = cli_overrides or {}
    data: dict = {}
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    llm_data = data.get("llm", {})
    server_data = data.get("server", {})
    agent_data = data.get("agent", {})
    guardrails_data = data.get("guardrails", {})
    workspace_root = data.get("workspace_root", ".")
    if "workspace" in overrides:
        workspace_root = overrides["workspace"]
    model = llm_data.get("model", "deepseek-chat")
    base_url = llm_data.get("base_url")
    llm = LLMConfig(model=model, base_url=base_url)
    host = overrides.get("host", server_data.get("host", "127.0.0.1"))
    port = overrides.get("port", server_data.get("port", 8000))
    secret = server_data.get("secret", "")
    if not secret:
        secret = _gen_secret()
    server = ServerConfig(host=host, port=port, secret=secret)
    max_rounds = overrides.get("max_rounds", agent_data.get("max_rounds", 50))
    parse_fail_limit = agent_data.get("parse_fail_limit", 3)
    approval_timeout_seconds = agent_data.get("approval_timeout_seconds", 86400)
    agent = AgentConfig(max_rounds=max_rounds, parse_fail_limit=parse_fail_limit, approval_timeout_seconds=approval_timeout_seconds)
    guardrails = load_config([config_path] if config_path else None)
    if "default_decision" in guardrails_data:
        guardrails.default_decision = guardrails_data["default_decision"]
    guardrails.workspace_root = workspace_root
    return AppConfig(
        workspace_root=workspace_root,
        llm=llm,
        server=server,
        agent=agent,
        guardrails=guardrails,
    )
