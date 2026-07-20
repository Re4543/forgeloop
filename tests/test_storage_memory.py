from datetime import datetime, timezone
from pathlib import Path
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.memory import write_memory, retrieve_memory, MemoryEntry
from forgeloop.storage.models import Session, create_session


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_write_and_retrieve(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    write_memory(conn, MemoryEntry(id="m1", workspace_root=str(tmp_path), kind="convention", tags='["python","style"]', content="use 4 spaces for indent", created_at=_now(), updated_at=_now()))
    write_memory(conn, MemoryEntry(id="m2", workspace_root=str(tmp_path), kind="decision", tags='["arch"]', content="use sqlite not postgres", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["sqlite"])
    assert len(results) == 1
    assert "sqlite" in results[0].content


def test_cross_session_same_workspace(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    create_session(conn, Session(id="sA", task="t", workspace_root=str(tmp_path), status="RUNNING", created_at=_now(), updated_at=_now()))
    write_memory(conn, MemoryEntry(id="m1", session_id="sA", workspace_root=str(tmp_path), kind="lesson", tags='[]', content="always run tests", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["tests"])
    assert len(results) == 1
    assert results[0].session_id == "sA"
    conn.close()


def test_top_k_limit(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    for i in range(10):
        write_memory(conn, MemoryEntry(id=f"m{i}", workspace_root=str(tmp_path), kind="fact", tags='[]', content=f"fact number {i}", created_at=_now(), updated_at=_now()))
    results = retrieve_memory(conn, str(tmp_path), ["fact"], k=3)
    assert len(results) == 3
