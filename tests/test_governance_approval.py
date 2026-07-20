from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.governance.approval import ApprovalFSM
from forgeloop.storage.models import Session, Turn, Action, create_session, create_turn, create_action


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_request_then_approve(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, parse_status="OK", started_at=_now(), finished_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    ar = fsm.request(action_id="a1", session_id="s1")
    assert ar.status == "PENDING"
    assert len(fsm.pending()) == 1
    fsm.approve(ar.id, decided_by="webui")
    assert len(fsm.pending()) == 0
    conn.close()


def test_deny_with_reason(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, parse_status="OK", started_at=_now(), finished_at=_now()))
    create_action(conn, Action(id="a2", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    ar = fsm.request(action_id="a2", session_id="s1")
    fsm.deny(ar.id, decided_by="webui", reason="too risky")
    assert len(fsm.pending()) == 0
    conn.close()


def test_persistence_after_reconnect(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="s1", task="x", workspace_root=str(tmp_path), status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, parse_status="OK", started_at=_now(), finished_at=_now()))
    create_action(conn, Action(id="a3", session_id="s1", turn_id="t1", tool="write_file", thought="x", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    fsm = ApprovalFSM(conn)
    fsm.request(action_id="a3", session_id="s1")
    conn.close()
    conn2 = connect(tmp_path / "t.db")
    fsm2 = ApprovalFSM(conn2)
    assert len(fsm2.pending()) == 1
    conn2.close()
