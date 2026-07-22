import json
from pathlib import Path
from fastapi.testclient import TestClient
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.llm.base import LLMConfig
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import Session, create_session
from forgeloop.storage.memory import MemoryEntry, write_memory
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


def test_get_sessions_empty(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.get("/sessions", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_sessions_returns_list(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    create_session(conn, Session(id="s1", task="fix tests", workspace_root=".", status="COMPLETED", created_at=_now(), updated_at=_now()))
    conn.close()
    resp = client.get("/sessions", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "s1"
    assert data[0]["status"] == "COMPLETED"
    assert data[0]["task"] == "fix tests"


def test_get_session_detail(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    create_session(conn, Session(id="s1", task="fix tests", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    from forgeloop.storage.models import Turn, Action, create_turn, create_action
    create_turn(conn, Turn(id="t1", session_id="s1", turn_index=0, started_at=_now()))
    create_action(conn, Action(id="a1", session_id="s1", turn_id="t1", tool="read_file", thought="r", args_hash="h", status="SUCCEEDED", created_at=_now(), args=json.dumps({"path": "src/main.py"}), result=json.dumps({"ok": True})))
    conn.close()
    resp = client.get("/sessions/s1", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "s1"
    assert len(data["turns"]) == 1
    assert data["turns"][0]["actions"][0]["tool"] == "read_file"


def test_abort_session(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    create_session(conn, Session(id="s1", task="x", workspace_root=".", status="RUNNING", created_at=_now(), updated_at=_now()))
    conn.close()
    resp = client.post("/sessions/s1/abort", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    conn = connect(db_path, wal=True)
    from forgeloop.storage.models import get_session
    s = get_session(conn, "s1")
    assert s.status == "ABORTED"
    conn.close()


def test_get_session_404(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.get("/sessions/nonexistent", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 404


def test_get_memory(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="hello world", created_at=_now(), updated_at=_now()))
    conn.close()
    resp = client.get("/memory", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "hello world"


def test_get_memory_with_keyword(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="hello world", tags="greeting", created_at=_now(), updated_at=_now()))
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="goodbye world", tags="farewell", created_at=_now(), updated_at=_now()))
    conn.close()
    resp = client.get("/memory?keyword=hello", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "hello world"


def test_get_credentials(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.get("/credentials", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data


def test_unauthorized_no_token(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.get("/sessions")
    assert resp.status_code == 401


def test_get_root_html(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.get("/", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
