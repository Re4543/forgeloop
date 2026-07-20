from __future__ import annotations
import re
from forgeloop.parser.types import Action
from forgeloop.governance.types import Decision
from forgeloop.governance.path_fence import fence_path
from forgeloop.config.loader import GuardrailsConfig


def _match(action: Action, rule: dict) -> bool:
    tools = rule.get("tool", [])
    if tools and action.tool not in tools:
        return False
    match = rule.get("match", {})
    if match.get("any"):
        return True
    if "command_regex" in match and action.tool == "run_shell":
        if not re.search(match["command_regex"], action.args.get("command", "")):
            return False
    if "path_regex" in match and action.tool in ("read_file", "write_file", "list_dir"):
        if not re.search(match["path_regex"], action.args.get("path", "")):
            return False
    if "args_match" in match:
        for k, v in match["args_match"].items():
            if action.args.get(k) != v:
                return False
    return True


def guardrail(action: Action, config: GuardrailsConfig) -> Decision:
    if action.tool in ("write_file", "read_file", "list_dir"):
        mode = "write" if action.tool == "write_file" else "read"
        fence = fence_path(action.args.get("path", ""), config.workspace_root, mode=mode, read_allowlist=config.path_fencing.get("read_allowlist", []))
        if not fence.allowed:
            return Decision(verdict="Deny", rule_id="path_fence", reason=fence.reason)
    for rule in config.rules:
        if _match(action, rule):
            return Decision(verdict=rule["decision"], rule_id=rule["id"], reason=rule.get("reason", ""))
    return Decision(verdict=config.default_decision, rule_id="default", reason="no rule matched")
