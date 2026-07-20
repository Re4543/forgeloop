from __future__ import annotations
import sqlite3
import uuid
from dataclasses import dataclass


@dataclass
class MemoryEntry:
    workspace_root: str
    kind: str
    content: str
    created_at: str
    updated_at: str
    id: str | None = None
    session_id: str | None = None
    tags: str | None = None
    key: str | None = None
    source_turn_id: str | None = None


def write_memory(conn: sqlite3.Connection, entry: MemoryEntry) -> str:
    if not entry.id:
        entry.id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO memory (id,session_id,workspace_root,kind,tags,key,content,source_turn_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (entry.id, entry.session_id, entry.workspace_root, entry.kind, entry.tags, entry.key, entry.content, entry.source_turn_id, entry.created_at, entry.updated_at),
    )
    conn.commit()
    return entry.id


def retrieve_memory(conn: sqlite3.Connection, workspace_root: str, keywords: list[str], k: int = 5) -> list[MemoryEntry]:
    if not keywords:
        return []
    clauses = []
    params: list = [workspace_root]
    for kw in keywords:
        clauses.append("(content LIKE ? OR tags LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    where = " OR ".join(clauses)
    sql = f"SELECT * FROM memory WHERE workspace_root=? AND ({where}) ORDER BY updated_at DESC LIMIT ?"
    params.append(k)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(MemoryEntry(
            id=r["id"], session_id=r["session_id"], workspace_root=r["workspace_root"],
            kind=r["kind"], tags=r["tags"], key=r["key"], content=r["content"],
            source_turn_id=r["source_turn_id"], created_at=r["created_at"], updated_at=r["updated_at"],
        ))
    return out
