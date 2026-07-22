import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import Session, Turn, Action, ApprovalRequest, create_session, create_turn, create_action, create_approval_request
from forgeloop.server.sweeper import TimeoutSweeper


def _now():
    return datetime.now(timezone.utc).isoformat()


def _setup_db(tmp_path):
    conn = connect(tmp_path / "t.db", wal=True)
    init_schema(conn)
    return conn


def test_sweeper_times_out_pending_approval(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    create_approval_request(conn, ApprovalRequest(id="ar1", action_id="a1", session_id="s1", status="PENDING", requested_at=old_time))
    sweeper = TimeoutSweeper(db_path=tmp_path / "t.db", approval_timeout_seconds=86400, poll_interval=0.05)
    sweeper.start()
    time.sleep(0.3)
    sweeper.stop()
    from forgeloop.storage.models import get_approval_request, get_session
    ar = get_approval_request(conn, "ar1")
    assert ar.status == "TIMEOUT"
    s = get_session(conn, "s1")
    assert s.status == "STOPPED_APPROVAL_TIMEOUT"
    conn.close()


def test_sweeper_skips_recent_pending(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    create_approval_request(conn, ApprovalRequest(id="ar1", action_id="a1", session_id="s1", status="PENDING", requested_at=_now()))
    sweeper = TimeoutSweeper(db_path=tmp_path / "t.db", approval_timeout_seconds=86400, poll_interval=0.05)
    sweeper.start()
    time.sleep(0.2)
    sweeper.stop()
    from forgeloop.storage.models import get_approval_request
    ar = get_approval_request(conn, "ar1")
    assert ar.status == "PENDING"
    conn.close()


def test_sweeper_timeout_zero_never_times_out(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    create_approval_request(conn, ApprovalRequest(id="ar1", action_id="a1", session_id="s1", status="PENDING", requested_at=old_time))
    sweeper = TimeoutSweeper(db_path=tmp_path / "t.db", approval_timeout_seconds=0, poll_interval=0.05)
    sweeper.start()
    time.sleep(0.2)
    sweeper.stop()
    from forgeloop.storage.models import get_approval_request
    ar = get_approval_request(conn, "ar1")
    assert ar.status == "PENDING"
    conn.close()
