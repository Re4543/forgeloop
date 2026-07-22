import json
from pathlib import Path
from fastapi.testclient import TestClient
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.llm.base import LLMConfig
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import Session, Turn, Action, ApprovalRequest, create_session, create_turn, create_action, create_approval_request
from forgeloop.server.app import create_app


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _make_client(tmp_path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)
    conn.close()
    cfg = AppConfig(
        workspace_root=str(tmp_path),
        llm=LLMConfig(model="mock"),
        server=ServerConfig(host="127.0.0.1", port=8000, secret="test-secret"),
        agent=AgentConfig(),
        guardrails=GuardrailsConfig(workspace_root=str(tmp_path)),
    )
    app = create_app(cfg, db_path)
    return TestClient(app), db_path


def _seed_approval(tmp_path, db_path, status="PENDING"):
    conn = connect(db_path, wal=True)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="PENDING_APPROVAL", created_at=_now(), updated_at=_now()))
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="write_file", thought="w", args_hash="h", status="PENDING_APPROVAL", created_at=_now(), args=json.dumps({"path": "src/new.py", "mode": "overwrite", "content": "x"})))
    create_approval_request(conn, ApprovalRequest(id="ar1", action_id="a1", session_id="s1", status=status, requested_at=_now()))
    conn.close()


def test_get_pending_approvals(tmp_path):
    client, db_path = _make_client(tmp_path)
    _seed_approval(tmp_path, db_path)
    resp = client.get("/approvals", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "ar1"
    assert data[0]["action"]["tool"] == "write_file"


def test_approve_endpoint(tmp_path):
    client, db_path = _make_client(tmp_path)
    _seed_approval(tmp_path, db_path)
    resp = client.post("/approvals/ar1/decision", json={"verdict": "approve"}, headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"
    conn = connect(db_path, wal=True)
    from forgeloop.storage.models import get_approval_request
    ar = get_approval_request(conn, "ar1")
    assert ar.status == "APPROVED"
    conn.close()


def test_deny_endpoint(tmp_path):
    client, db_path = _make_client(tmp_path)
    _seed_approval(tmp_path, db_path)
    resp = client.post("/approvals/ar1/decision", json={"verdict": "deny", "reason": "no good"}, headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "DENIED"
    conn = connect(db_path, wal=True)
    from forgeloop.storage.models import get_approval_request
    ar = get_approval_request(conn, "ar1")
    assert ar.status == "DENIED"
    assert ar.deny_reason == "no good"
    conn.close()


def test_approve_404(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.post("/approvals/nonexistent/decision", json={"verdict": "approve"}, headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 404


def test_invalid_verdict_400(tmp_path):
    client, db_path = _make_client(tmp_path)
    _seed_approval(tmp_path, db_path)
    resp = client.post("/approvals/ar1/decision", json={"verdict": "maybe"}, headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 400
