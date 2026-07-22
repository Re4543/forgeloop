import sqlite3
import threading
import time
from pathlib import Path
from forgeloop.agent.loop import AgentLoop
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.config.loader import load_config
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import Session, Turn, Action, ApprovalRequest, create_session, create_turn, create_action, create_approval_request
from forgeloop.governance.approval import ApprovalFSM


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def _make_loop(tmp_workspace):
    conn = connect(tmp_workspace / "t.db", check_same_thread=False)
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"x","tool":"write_file","args":{"path":"src/new.py","mode":"overwrite","content":"x"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="write then done")
    return loop, conn


def test_await_approval_approved(tmp_workspace):
    loop, conn = _make_loop(tmp_workspace)
    create_session(conn, Session(id=loop._session_id, task="x", workspace_root=str(tmp_workspace), status="RUNNING", created_at=_now(), updated_at=_now()))
    turn_id = "t1"
    create_turn(conn, Turn(id=turn_id, session_id=loop._session_id, turn_index=0, started_at=_now()))
    action_id = "a1"
    create_action(conn, Action(id=action_id, session_id=loop._session_id, turn_id=turn_id, tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    ar_id = "ar1"
    create_approval_request(conn, ApprovalRequest(id=ar_id, action_id=action_id, session_id=loop._session_id, status="PENDING", requested_at=_now()))
    fsm = ApprovalFSM(conn)
    result = [None]

    def _poll():
        result[0] = loop._await_approval(ar_id, poll_interval=0.05)

    t = threading.Thread(target=_poll)
    t.start()
    time.sleep(0.2)
    fsm.approve(ar_id)
    t.join(timeout=5)
    assert result[0] == "approved"
    conn.close()


def test_await_approval_denied(tmp_workspace):
    loop, conn = _make_loop(tmp_workspace)
    create_session(conn, Session(id=loop._session_id, task="x", workspace_root=str(tmp_workspace), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id=loop._session_id, turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id=loop._session_id, turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    ar_id = "ar1"
    create_approval_request(conn, ApprovalRequest(id=ar_id, action_id="a1", session_id=loop._session_id, status="PENDING", requested_at=_now()))
    fsm = ApprovalFSM(conn)
    result = [None]

    def _poll():
        result[0] = loop._await_approval(ar_id, poll_interval=0.05)

    t = threading.Thread(target=_poll)
    t.start()
    time.sleep(0.2)
    fsm.deny(ar_id, reason="no good")
    t.join(timeout=5)
    assert result[0] == "denied"
    conn.close()


def test_await_approval_timeout(tmp_workspace):
    loop, conn = _make_loop(tmp_workspace)
    create_session(conn, Session(id=loop._session_id, task="x", workspace_root=str(tmp_workspace), status="RUNNING", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id=loop._session_id, turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id=loop._session_id, turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now()))
    ar_id = "ar1"
    create_approval_request(conn, ApprovalRequest(id=ar_id, action_id="a1", session_id=loop._session_id, status="PENDING", requested_at=_now()))
    from forgeloop.storage.models import update_approval_request
    update_approval_request(conn, ar_id, status="TIMEOUT", decided_at=_now())
    result = loop._await_approval(ar_id, poll_interval=0.05)
    assert result == "timeout"
    conn.close()


def test_loop_requireapproval_with_thread_approval(tmp_workspace):
    loop, conn = _make_loop(tmp_workspace)

    def _approver():
        for _ in range(100):
            row = conn.execute("SELECT id FROM approval_requests WHERE status='PENDING'").fetchone()
            if row:
                fsm = ApprovalFSM(conn)
                fsm.approve(row["id"])
                return
            time.sleep(0.05)

    t = threading.Thread(target=_approver)
    t.start()
    status = loop.run()
    t.join(timeout=5)
    assert status == "COMPLETED"
    ar = conn.execute("SELECT status FROM approval_requests").fetchall()
    assert ar[0]["status"] == "APPROVED"
    act = conn.execute("SELECT status FROM actions WHERE tool='write_file'").fetchone()
    assert act["status"] == "SUCCEEDED"
    conn.close()
