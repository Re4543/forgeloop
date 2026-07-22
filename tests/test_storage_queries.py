import sqlite3
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import (
    Session, Turn, Action, ApprovalRequest,
    create_session, create_turn, create_action, create_approval_request,
    list_sessions, get_turns_for_session, get_actions_for_turn,
    get_action, get_approval_request, list_memory, abort_session,
)
from forgeloop.storage.memory import MemoryEntry, write_memory


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _setup_db(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    return conn


def test_list_sessions(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="a", workspace_root=".", status="COMPLETED", created_at=_now(), updated_at=_now()))
    create_session(conn, Session(id="s2", task="b", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    sessions = list_sessions(conn)
    assert len(sessions) == 2
    assert all(isinstance(s, Session) for s in sessions)
    conn.close()


def test_get_turns_for_session(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_turn(conn, Turn(id="t2", session_id="s1", turn_index=1, started_at=_now()))
    turns = get_turns_for_session(conn, "s1")
    assert len(turns) == 2
    assert turns[0].turn_index == 0
    assert turns[1].turn_index == 1
    conn.close()


def test_get_actions_for_turn(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="read_file", thought="r", args_hash="h", status="SUCCEEDED", created_at=_now()))
    create_action(conn, Action(id="a2", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h2", status="SUCCEEDED", created_at=_now()))
    actions = get_actions_for_turn(conn, "t1")
    assert len(actions) == 2
    assert all(isinstance(a, Action) for a in actions)
    conn.close()


def test_get_action(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="read_file", thought="r", args_hash="h", status="SUCCEEDED", created_at=_now()))
    a = get_action(conn, "a1")
    assert a is not None
    assert a.tool == "read_file"
    assert get_action(conn, "nonexistent") is None
    conn.close()


def test_get_approval_request(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    create_approval_request(conn, ApprovalRequest(id="ar1", action_id="a1", session_id="s1", status="PENDING", requested_at=_now()))
    ar = get_approval_request(conn, "ar1")
    assert ar is not None
    assert ar.status == "PENDING"
    assert get_approval_request(conn, "nonexistent") is None
    conn.close()


def test_list_memory(tmp_path):
    conn = _setup_db(tmp_path)
    now = _now()
    write_memory(conn, MemoryEntry(workspace_root="/ws", kind="note", content="hello world", created_at=now, updated_at=now))
    write_memory(conn, MemoryEntry(workspace_root="/ws", kind="note", content="second entry", created_at=now, updated_at=now))
    write_memory(conn, MemoryEntry(workspace_root="/other", kind="note", content="other ws", created_at=now, updated_at=now))
    entries = list_memory(conn, "/ws")
    assert len(entries) == 2
    assert all(e.workspace_root == "/ws" for e in entries)
    conn.close()


def test_abort_session(tmp_path):
    conn = _setup_db(tmp_path)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    abort_session(conn, "s1")
    from forgeloop.storage.models import get_session
    s = get_session(conn, "s1")
    assert s.status == "ABORTED"
    assert s.finished_at is not None
    conn.close()


def test_connect_wal_mode(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db, wal=True)
    mode = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode[0].lower() == "wal"
    conn.close()
