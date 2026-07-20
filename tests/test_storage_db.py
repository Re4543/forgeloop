from pathlib import Path
from forgeloop.storage.db import connect, init_schema


def test_init_schema_creates_tables(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert {"sessions", "turns", "actions", "approval_requests", "memory"} <= names
    conn.close()


def test_init_schema_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    init_schema(conn)
    conn.close()
