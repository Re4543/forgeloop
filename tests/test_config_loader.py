from pathlib import Path
from forgeloop.config.loader import load_config


def test_load_default_has_rules():
    cfg = load_config([])
    assert cfg.default_decision == "RequireApproval"
    ids = [r["id"] for r in cfg.rules]
    assert "deny_rm_rf_root" in ids
    assert "allow_done" in ids
    assert cfg.path_fencing["writes"] is True


def test_override_replaces_by_id(tmp_path: Path):
    override = tmp_path / "override.yaml"
    override.write_text(
        "rules:\n  - id: deny_sudo\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n",
        encoding="utf-8",
    )
    cfg = load_config([override])
    sudo_rule = next(r for r in cfg.rules if r["id"] == "deny_sudo")
    assert sudo_rule["decision"] == "Allow"


def test_override_appends_new_id(tmp_path: Path):
    override = tmp_path / "add.yaml"
    override.write_text(
        "rules:\n  - id: my_custom_rule\n    tool: [run_shell]\n    match: {any: true}\n    decision: Allow\n",
        encoding="utf-8",
    )
    cfg = load_config([override])
    assert any(r["id"] == "my_custom_rule" for r in cfg.rules)


def test_writes_fencing_forced_true(tmp_path: Path):
    override = tmp_path / "bad.yaml"
    override.write_text("path_fencing: {writes: false}\n", encoding="utf-8")
    cfg = load_config([override])
    assert cfg.path_fencing["writes"] is True
