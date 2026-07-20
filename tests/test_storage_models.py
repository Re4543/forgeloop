from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import (
    Session, Turn, Action, ApprovalRequest,
    create_session, get_session, update_session_status,
    create_turn, create_action, update_action,
    create_approval_request, update_approval_request, list_pending_approvals,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_session_roundtrip(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    s = Session(id="s1", task="do thing", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now(), llm_config='{"model":"gpt-4o"}')
    create_session(conn, s)
    got = get_session(conn, "s1")
    assert got.status == "RUNNING"
    assert got.llm_config == '{"model":"gpt-4o"}'
    assert "api_key" not in got.llm_config
    conn.close()


def test_update_session_status(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    s = Session(id="s2", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now())
    create_session(conn, s)
    update_session_status(conn, "s2", "COMPLETED", round_count=5)
    assert get_session(conn, "s2").status == "COMPLETED"
    assert get_session(conn, "s2").round_count == 5
    conn.close()


def test_action_and_approval(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    now = _now()
    create_session(conn, Session(id="s3", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=now, updated_at=now))
    create_turn(conn, Turn(id="t1", session_id="s3", turn_index=0, parse_status="OK", started_at=now, finished_at=now))
    create_action(conn, Action(id="a1", session_id="s3", turn_id="t1", tool="run_shell", args='{"command":"ls"}', thought="x", args_hash="h1", status="PENDING_APPROVAL", created_at=now))
    create_approval_request(conn, ApprovalRequest(id="ap1", action_id="a1", session_id="s3", status="PENDING", requested_at=now))
    pending = list_pending_approvals(conn)
    assert len(pending) == 1
    assert pending[0].action_id == "a1"
    update_approval_request(conn, "ap1", status="APPROVED", decided_at=now, decided_by="webui")
    assert len(list_pending_approvals(conn)) == 0
    update_action(conn, "a1", status="SUCCEEDED", result='{"ok":true}')
    conn.close()
