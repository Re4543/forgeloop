from forgeloop.config.loader import load_config
from forgeloop.governance.rule_engine import guardrail
from forgeloop.parser.types import Action


def _cfg():
    return load_config([])


def test_deny_rm_rf():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "rm -rf /"}), _cfg())
    assert d.verdict == "Deny"
    assert d.rule_id == "deny_rm_rf_root"


def test_allow_git_status():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "git status"}), _cfg())
    assert d.verdict == "Allow"
    assert d.rule_id == "allow_git_readonly"


def test_approve_write(tmp_path):
    cfg = _cfg()
    cfg.workspace_root = str(tmp_path)
    d = guardrail(Action(thought="x", tool="write_file", args={"path": str(tmp_path / "a.py"), "mode": "overwrite", "content": "x"}), cfg)
    assert d.verdict == "RequireApproval"
    assert d.rule_id == "approve_all_writes"


def test_deny_write_outside_workspace():
    d = guardrail(Action(thought="x", tool="write_file", args={"path": "/etc/evil", "mode": "overwrite", "content": "x"}), _cfg())
    assert d.verdict == "Deny"


def test_default_require_approval():
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "python foo.py"}), _cfg())
    assert d.verdict == "RequireApproval"
    assert d.rule_id == "approve_shell_default"


def test_allow_done():
    d = guardrail(Action(thought="x", tool="done", args={"summary": "ok", "success": True}), _cfg())
    assert d.verdict == "Allow"


def test_override_replaces_rule(tmp_path):
    override = tmp_path / "ov.yaml"
    override.write_text("rules:\n  - id: deny_sudo\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n", encoding="utf-8")
    cfg = load_config([override])
    d = guardrail(Action(thought="x", tool="run_shell", args={"command": "sudo ls"}), cfg)
    assert d.verdict == "Allow"
