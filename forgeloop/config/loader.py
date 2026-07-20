from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from importlib import resources


@dataclass
class GuardrailsConfig:
    workspace_root: str = "."
    path_fencing: dict = field(default_factory=dict)
    default_decision: str = "RequireApproval"
    hitl: dict = field(default_factory=dict)
    done_post_check: dict = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_default() -> dict:
    with resources.files("forgeloop.config").joinpath("guardrails.default.yaml").open("r") as f:
        return yaml.safe_load(f) or {}


def _merge_rules(default_rules: list[dict], override_rules: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in default_rules}
    for r in override_rules:
        by_id[r["id"]] = r
    return list(by_id.values())


def load_config(overrides: list[Path] | None = None) -> GuardrailsConfig:
    data = _load_default()
    for ov in overrides or []:
        ov_data = _load_yaml(ov)
        if "rules" in ov_data:
            data["rules"] = _merge_rules(data.get("rules", []), ov_data.pop("rules"))
        for k, v in ov_data.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k] = {**data[k], **v}
            else:
                data[k] = v
    data.setdefault("path_fencing", {})
    data["path_fencing"]["writes"] = True
    return GuardrailsConfig(
        workspace_root=data.get("workspace_root", "."),
        path_fencing=data["path_fencing"],
        default_decision=data.get("default_decision", "RequireApproval"),
        hitl=data.get("hitl", {"approval_timeout_seconds": 86400, "auto_approve_on_timeout": False}),
        done_post_check=data.get("done_post_check", {"require_green_tests": False}),
        rules=data.get("rules", []),
    )
