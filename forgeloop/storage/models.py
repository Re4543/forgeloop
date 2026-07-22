from __future__ import annotations
import sqlite3
from dataclasses import dataclass


@dataclass
class Session:
    id: str
    task: str
    workspace_root: str
    status: str
    created_at: str
    updated_at: str
    config_path: str | None = None
    round_count: int = 0
    consecutive_failures: int = 0
    consecutive_identical: int = 0
    last_action_hash: str | None = None
    last_test_state: str | None = None
    llm_config: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class Turn:
    id: str
    session_id: str
    turn_index: int
    started_at: str
    parse_status: str = "OK"
    finished_at: str | None = None
    llm_raw_output: str | None = None
    parsed_action_id: str | None = None
    parse_attempts: int = 0
    llm_call_meta: str | None = None


@dataclass
class Action:
    id: str
    session_id: str
    turn_id: str
    tool: str
    thought: str
    args_hash: str
    status: str
    created_at: str
    args: str | None = None
    guardrail_decision: str | None = None
    result: str | None = None
    feedback_signal: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class ApprovalRequest:
    id: str
    action_id: str
    session_id: str
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    deny_reason: str | None = None


def _row_to(cls, row: sqlite3.Row):
    return cls(**{c: row[c] for c in row.keys() if c in cls.__dataclass_fields__})


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def create_session(conn: sqlite3.Connection, s: Session) -> None:
    conn.execute(
        "INSERT INTO sessions (id,task,workspace_root,config_path,status,round_count,consecutive_failures,consecutive_identical,last_action_hash,last_test_state,llm_config,created_at,started_at,finished_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.id, s.task, s.workspace_root, s.config_path, s.status, s.round_count, s.consecutive_failures, s.consecutive_identical, s.last_action_hash, s.last_test_state, s.llm_config, s.created_at, s.started_at, s.finished_at, s.updated_at),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, sid: str) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    return _row_to(Session, row) if row else None


def update_session_status(conn: sqlite3.Connection, sid: str, status: str, **fields) -> None:
    sets = ["status=?", "updated_at=?"]
    vals = [status, fields.get("updated_at") or _now()]
    for k, v in fields.items():
        if k in Session.__dataclass_fields__ and k not in ("status", "updated_at"):
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(sid)
    conn.execute(f"UPDATE sessions SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def create_turn(conn: sqlite3.Connection, t: Turn) -> None:
    conn.execute(
        "INSERT INTO turns (id,session_id,turn_index,llm_raw_output,parsed_action_id,parse_attempts,parse_status,llm_call_meta,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (t.id, t.session_id, t.turn_index, t.llm_raw_output, t.parsed_action_id, t.parse_attempts, t.parse_status, t.llm_call_meta, t.started_at, t.finished_at),
    )
    conn.commit()


def create_action(conn: sqlite3.Connection, a: Action) -> None:
    conn.execute(
        "INSERT INTO actions (id,session_id,turn_id,tool,args,thought,args_hash,status,guardrail_decision,result,feedback_signal,created_at,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a.id, a.session_id, a.turn_id, a.tool, a.args, a.thought, a.args_hash, a.status, a.guardrail_decision, a.result, a.feedback_signal, a.created_at, a.started_at, a.finished_at),
    )
    conn.commit()


def update_action(conn: sqlite3.Connection, aid: str, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k in Action.__dataclass_fields__:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(aid)
    conn.execute(f"UPDATE actions SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def create_approval_request(conn: sqlite3.Connection, ar: ApprovalRequest) -> None:
    conn.execute(
        "INSERT INTO approval_requests (id,action_id,session_id,status,requested_at,decided_at,decided_by,deny_reason) VALUES (?,?,?,?,?,?,?,?)",
        (ar.id, ar.action_id, ar.session_id, ar.status, ar.requested_at, ar.decided_at, ar.decided_by, ar.deny_reason),
    )
    conn.commit()


def update_approval_request(conn: sqlite3.Connection, arid: str, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k in ApprovalRequest.__dataclass_fields__:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(arid)
    conn.execute(f"UPDATE approval_requests SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()


def list_pending_approvals(conn: sqlite3.Connection) -> list[ApprovalRequest]:
    rows = conn.execute("SELECT * FROM approval_requests WHERE status='PENDING'").fetchall()
    return [_row_to(ApprovalRequest, r) for r in rows]


def list_sessions(conn: sqlite3.Connection) -> list[Session]:
    rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    return [_row_to(Session, r) for r in rows]


def get_turns_for_session(conn: sqlite3.Connection, sid: str) -> list[Turn]:
    rows = conn.execute("SELECT * FROM turns WHERE session_id=? ORDER BY turn_index", (sid,)).fetchall()
    return [_row_to(Turn, r) for r in rows]


def get_actions_for_turn(conn: sqlite3.Connection, turn_id: str) -> list[Action]:
    rows = conn.execute("SELECT * FROM actions WHERE turn_id=? ORDER BY created_at", (turn_id,)).fetchall()
    return [_row_to(Action, r) for r in rows]


def get_actions_for_session(conn: sqlite3.Connection, sid: str) -> list[Action]:
    rows = conn.execute("SELECT * FROM actions WHERE session_id=? ORDER BY created_at", (sid,)).fetchall()
    return [_row_to(Action, r) for r in rows]


def get_action(conn: sqlite3.Connection, aid: str) -> Action | None:
    row = conn.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
    return _row_to(Action, row) if row else None


def get_approval_request(conn: sqlite3.Connection, arid: str) -> ApprovalRequest | None:
    row = conn.execute("SELECT * FROM approval_requests WHERE id=?", (arid,)).fetchone()
    return _row_to(ApprovalRequest, row) if row else None


def list_memory(conn: sqlite3.Connection, workspace_root: str) -> list:
    from forgeloop.storage.memory import MemoryEntry
    rows = conn.execute("SELECT * FROM memory WHERE workspace_root=? ORDER BY updated_at DESC", (workspace_root,)).fetchall()
    return [_row_to(MemoryEntry, r) for r in rows]


def abort_session(conn: sqlite3.Connection, sid: str) -> None:
    update_session_status(conn, sid, "ABORTED", finished_at=_now())
