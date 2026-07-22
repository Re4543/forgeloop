from __future__ import annotations
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    config_path TEXT,
    status TEXT NOT NULL,
    round_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_identical INTEGER NOT NULL DEFAULT 0,
    last_action_hash TEXT,
    last_test_state TEXT,
    llm_config TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    llm_raw_output TEXT,
    parsed_action_id TEXT,
    parse_attempts INTEGER NOT NULL DEFAULT 0,
    parse_status TEXT,
    llm_call_meta TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_id TEXT NOT NULL REFERENCES turns(id),
    tool TEXT NOT NULL,
    args TEXT,
    thought TEXT,
    args_hash TEXT,
    status TEXT NOT NULL,
    guardrail_decision TEXT,
    result TEXT,
    feedback_signal TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    deny_reason TEXT
);

CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    workspace_root TEXT NOT NULL,
    kind TEXT NOT NULL,
    tags TEXT,
    key TEXT,
    content TEXT NOT NULL,
    source_turn_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path, wal: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
