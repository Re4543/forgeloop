# ForgeLoop CLI + WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CLI entrypoint and FastAPI WebUI for ForgeLoop, enabling `forgeloop run --task "..."` to start the agent loop and a local web server in a single process with HITL approval via DB polling.

**Architecture:** Single process, 3 threads (agent loop on main, uvicorn server on background thread, timeout sweeper on background thread). Shared state via SQLite in WAL mode. Per-thread DB connections. Vanilla HTML+JS frontend.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, argparse, SQLite (WAL mode), Pydantic, vanilla HTML+JS

## Global Constraints

- Python 3.12+ (use `py -3.13` for running tests — system python is 3.10)
- No agent SDK — self-implemented agent loop from Plan 1
- API key never in source/git/logs — keyring or env var only
- File writes fenced via path_fence from Plan 1
- Feedback parsing deterministic (no LLM self-check)
- TDD: write failing test first, then implement
- No comments in code
- DRY, YAGNI
- No new deps beyond fastapi, uvicorn (httpx, pyyaml, keyring already in Plan 1)
- All endpoints require `Authorization: Bearer <secret>` header
- Frontend not unit-tested (vanilla JS, manual)

---

## File Structure (new + modified files in Plan 2)

```
forgeloop/
  cli.py                      # NEW — argparse + startup sequence
  config/
    app_config.py              # NEW — AppConfig dataclass + load_app_config()
  server/
    __init__.py                # NEW — package marker
    app.py                     # NEW — FastAPI app, routes, create_app() factory
    auth.py                    # NEW — verify_token dependency
    schemas.py                 # NEW — Pydantic request/response models
    sweeper.py                 # NEW — timeout sweeper thread
  web/
    index.html                 # NEW — single-page frontend
  storage/
    db.py                      # MODIFY — add WAL mode option to connect()
    models.py                 # MODIFY — add query functions for WebUI reads
  agent/
    loop.py                    # MODIFY — rewrite _await_approval stub
pyproject.toml                 # MODIFY — add fastapi/uvicorn deps, console_scripts
tests/
  test_config_app_config.py    # NEW
  test_storage_queries.py      # NEW — query functions added in Task 2
  test_agent_loop_approval.py  # NEW — _await_approval polling tests
  test_server_sweeper.py       # NEW
  test_server_auth.py          # NEW
  test_server_app.py           # NEW — session/memory/credential endpoints
  test_server_approvals.py     # NEW — approval endpoints
  test_cli.py                  # NEW
  test_e2e_approval_flow.py    # NEW — full integration test
```

---

## Task 1: Dependencies + AppConfig

**Files:**
- Modify: `pyproject.toml`
- Create: `forgeloop/config/app_config.py`
- Test: `tests/test_config_app_config.py`

**Interfaces:**
- Consumes: `forgeloop.config.loader.load_config` (Plan 1), `forgeloop.llm.base.LLMConfig` (Plan 1)
- Produces: `AppConfig`, `LLMConfig` (re-exported), `ServerConfig`, `AgentConfig`, `load_app_config(config_path: Path | None, cli_overrides: dict) -> AppConfig`

- [ ] **Step 1: Update pyproject.toml — add deps + entry point**

```toml
[project]
name = "forgeloop"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "pyyaml>=6.0",
    "keyring>=24",
    "fastapi>=0.110",
    "uvicorn>=0.29",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "httpx>=0.27"]

[project.scripts]
forgeloop = "forgeloop.cli:main"
```

Note: `httpx` is already a core dep but also needed for FastAPI's `TestClient`. Move it to core deps (it's already there). Add `fastapi` and `uvicorn` to core deps (not optional — the spec says "No new deps beyond fastapi, uvicorn" and the project is a single install).

- [ ] **Step 2: Write the failing test for AppConfig + load_app_config**

```python
# tests/test_config_app_config.py
from pathlib import Path
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig, load_app_config


def test_load_app_config_defaults(tmp_path):
    cfg = load_app_config(None, {})
    assert cfg.workspace_root == "."
    assert cfg.llm.model == "deepseek-chat"
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8000
    assert cfg.server.secret != ""
    assert len(cfg.server.secret) == 64
    assert cfg.agent.max_rounds == 50
    assert cfg.agent.parse_fail_limit == 3
    assert cfg.agent.approval_timeout_seconds == 86400
    assert cfg.guardrails is not None


def test_load_app_config_from_yaml(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text(
        "workspace_root: /tmp/ws\n"
        "llm:\n"
        "  model: gpt-4o\n"
        "  base_url: https://api.openai.com/v1\n"
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 9000\n"
        "  secret: my-secret\n"
        "agent:\n"
        "  max_rounds: 10\n"
        "  parse_fail_limit: 5\n"
        "  approval_timeout_seconds: 3600\n"
        "guardrails:\n"
        "  default_decision: Allow\n"
    )
    cfg = load_app_config(yaml_path, {})
    assert cfg.workspace_root == "/tmp/ws"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.base_url == "https://api.openai.com/v1"
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 9000
    assert cfg.server.secret == "my-secret"
    assert cfg.agent.max_rounds == 10
    assert cfg.agent.parse_fail_limit == 5
    assert cfg.agent.approval_timeout_seconds == 3600
    assert cfg.guardrails.default_decision == "Allow"


def test_cli_overrides_yaml(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text(
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 9000\n"
        "agent:\n"
        "  max_rounds: 10\n"
    )
    cfg = load_app_config(yaml_path, {"host": "127.0.0.1", "port": 8080, "max_rounds": 20})
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8080
    assert cfg.agent.max_rounds == 20


def test_secret_generated_when_empty(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text("server:\n  secret: ''\n")
    cfg = load_app_config(yaml_path, {})
    assert len(cfg.server.secret) == 64


def test_secret_generated_when_missing(tmp_path):
    yaml_path = tmp_path / "forgeloop.yaml"
    yaml_path.write_text("llm:\n  model: x\n")
    cfg = load_app_config(yaml_path, {})
    assert len(cfg.server.secret) == 64
```

- [ ] **Step 3: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_config_app_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forgeloop.config.app_config'`

- [ ] **Step 4: Implement app_config.py**

```python
# forgeloop/config/app_config.py
from __future__ import annotations
import secrets as _secrets
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from forgeloop.config.loader import GuardrailsConfig, load_config
from forgeloop.llm.base import LLMConfig


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    secret: str = ""


@dataclass
class AgentConfig:
    max_rounds: int = 50
    parse_fail_limit: int = 3
    approval_timeout_seconds: int = 86400


@dataclass
class AppConfig:
    workspace_root: str = "."
    llm: LLMConfig = field(default_factory=lambda: LLMConfig(model="deepseek-chat"))
    server: ServerConfig = field(default_factory=ServerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)


def _gen_secret() -> str:
    return _secrets.token_urlsafe(48)[:64]


def load_app_config(config_path: Path | None = None, cli_overrides: dict | None = None) -> AppConfig:
    overrides = cli_overrides or {}
    data: dict = {}
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    llm_data = data.get("llm", {})
    server_data = data.get("server", {})
    agent_data = data.get("agent", {})
    guardrails_data = data.get("guardrails", {})
    workspace_root = data.get("workspace_root", ".")
    if "workspace" in overrides:
        workspace_root = overrides["workspace"]
    model = llm_data.get("model", "deepseek-chat")
    base_url = llm_data.get("base_url")
    llm = LLMConfig(model=model, base_url=base_url)
    host = overrides.get("host", server_data.get("host", "127.0.0.1"))
    port = overrides.get("port", server_data.get("port", 8000))
    secret = server_data.get("secret", "")
    if not secret:
        secret = _gen_secret()
    server = ServerConfig(host=host, port=port, secret=secret)
    max_rounds = overrides.get("max_rounds", agent_data.get("max_rounds", 50))
    parse_fail_limit = agent_data.get("parse_fail_limit", 3)
    approval_timeout_seconds = agent_data.get("approval_timeout_seconds", 86400)
    agent = AgentConfig(max_rounds=max_rounds, parse_fail_limit=parse_fail_limit, approval_timeout_seconds=approval_timeout_seconds)
    guardrails = load_config([config_path] if config_path else None)
    if "default_decision" in guardrails_data:
        guardrails.default_decision = guardrails_data["default_decision"]
    guardrails.workspace_root = workspace_root
    return AppConfig(
        workspace_root=workspace_root,
        llm=llm,
        server=server,
        agent=agent,
        guardrails=guardrails,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_config_app_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml forgeloop/config/app_config.py tests/test_config_app_config.py
git commit -m "feat(config): AppConfig dataclass + load_app_config with yaml+cli merge"
```

---

## Task 2: DB Layer Additions (WAL + Query Functions)

**Files:**
- Modify: `forgeloop/storage/db.py:80-84` (connect function)
- Modify: `forgeloop/storage/models.py` (append query functions)
- Test: `tests/test_storage_queries.py`

**Interfaces:**
- Consumes: `forgeloop.storage.db.connect`, `forgeloop.storage.models` dataclasses (Plan 1)
- Produces: `connect(db_path, wal=False)`, `list_sessions(conn)`, `get_turns_for_session(conn, sid)`, `get_actions_for_turn(conn, turn_id)`, `get_action(conn, aid)`, `get_approval_request(conn, arid)`, `list_memory(conn, workspace_root)`, `abort_session(conn, sid)`

- [ ] **Step 1: Write the failing test for query functions**

```python
# tests/test_storage_queries.py
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
    write_memory(conn, MemoryEntry(workspace_root="/ws", kind="note", content="hello world"))
    write_memory(conn, MemoryEntry(workspace_root="/ws", kind="note", content="second entry"))
    write_memory(conn, MemoryEntry(workspace_root="/other", kind="note", content="other ws"))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_storage_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_sessions'`

- [ ] **Step 3: Add WAL mode to connect()**

In `forgeloop/storage/db.py`, replace the `connect` function:

```python
def connect(db_path: Path, wal: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

- [ ] **Step 4: Add query functions to models.py**

Append to `forgeloop/storage/models.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_storage_queries.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `py -3.13 -m pytest -v`
Expected: All Plan 1 tests still pass + new tests pass

- [ ] **Step 7: Commit**

```bash
git add forgeloop/storage/db.py forgeloop/storage/models.py tests/test_storage_queries.py
git commit -m "feat(storage): WAL mode + query functions for WebUI reads"
```

---

## Task 3: _await_approval Rewrite

**Files:**
- Modify: `forgeloop/agent/loop.py:96-112` (RequireApproval branch) and `loop.py:163-164` (_await_approval stub)
- Test: `tests/test_agent_loop_approval.py`

**Interfaces:**
- Consumes: `forgeloop.storage.models.update_approval_request`, `forgeloop.storage.models.update_session_status` (Plan 1)
- Produces: `AgentLoop._await_approval(ar_id, poll_interval=2.0) -> str` — returns `"approved"`, `"denied"`, or `"timeout"`

- [ ] **Step 1: Write the failing test for _await_approval polling**

```python
# tests/test_agent_loop_approval.py
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
    conn = connect(tmp_workspace / "t.db")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_agent_loop_approval.py -v`
Expected: FAIL — `_await_approval` returns `None` (stub), not `"approved"`

- [ ] **Step 3: Rewrite _await_approval and update the RequireApproval branch**

In `forgeloop/agent/loop.py`, replace the `_await_approval` method (line 163-164):

```python
def _await_approval(self, ar_id: str, poll_interval: float = 2.0) -> str:
    import time
    while True:
        row = self._conn.execute("SELECT status FROM approval_requests WHERE id=?", (ar_id,)).fetchone()
        if not row:
            return "denied"
        status = row["status"]
        if status == "APPROVED":
            return "approved"
        if status == "DENIED":
            return "denied"
        if status == "TIMEOUT":
            return "timeout"
        time.sleep(poll_interval)
```

Then replace the RequireApproval branch (lines 96-114) with:

```python
elif decision.verdict == "RequireApproval":
    update_action(self._conn, action_row.id, status="PENDING_APPROVAL", guardrail_decision=json.dumps({"verdict": "RequireApproval", "rule_id": decision.rule_id, "reason": decision.reason}))
    ar = self._fsm.request(action_id=action_row.id, session_id=self._session_id)
    update_session_status(self._conn, self._session_id, "PENDING_APPROVAL")
    approval_result = self._await_approval(ar.id)
    if approval_result == "denied":
        update_action(self._conn, action_row.id, status="DENIED", finished_at=_now())
        self._consec_fail += 1
        self._history.append(Message(role="user", content="[DENIED] user denied your action."))
        self._last_feedback = None
        self._round += 1
        st = self._check_and_update()
        if st != "RUNNING":
            return st
        continue
    elif approval_result == "timeout":
        update_action(self._conn, action_row.id, status="TIMEOUT", finished_at=_now())
        update_session_status(self._conn, self._session_id, "STOPPED_APPROVAL_TIMEOUT", finished_at=_now())
        return "STOPPED_APPROVAL_TIMEOUT"
    update_action(self._conn, action_row.id, status="APPROVED")
    update_session_status(self._conn, self._session_id, "RUNNING")
    result = self._registry.dispatch(action, ctx={"workspace_root": self._workspace_root, "read_allowlist": self._config.path_fencing.get("read_allowlist", [])})
    self._finish_action(action_row, action, result, ahash)
```

Also remove the `_fsm_denied` method (lines 166-168) since it's no longer used.

- [ ] **Step 4: Update the old test that relied on the stub**

In `tests/test_agent_loop.py`, the test `test_loop_requireapproval_auto_proceeds` (line 101-120) relied on the no-op stub. Replace it with a version that auto-approves via a thread:

```python
def test_loop_requireapproval_auto_proceeds(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"x","tool":"write_file","args":{"path":"src/new.py","mode":"overwrite","content":"x"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="write then done")

    import threading, time
    from forgeloop.governance.approval import ApprovalFSM

    def _approver():
        for _ in range(100):
            row = conn.execute("SELECT id FROM approval_requests WHERE status='PENDING'").fetchone()
            if row:
                ApprovalFSM(conn).approve(row["id"])
                return
            time.sleep(0.05)

    t = threading.Thread(target=_approver)
    t.start()
    status = loop.run()
    t.join(timeout=5)
    assert status == "COMPLETED"
    ar = conn.execute("SELECT status FROM approval_requests").fetchall()
    assert len(ar) == 1
    assert ar[0]["status"] == "APPROVED"
    act = conn.execute("SELECT status FROM actions WHERE tool='write_file'").fetchone()
    assert act["status"] == "SUCCEEDED"
    assert (tmp_workspace / "src" / "new.py").read_text(encoding="utf-8") == "x"
    conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_agent_loop_approval.py tests/test_agent_loop.py -v`
Expected: PASS (all tests including updated old test)

- [ ] **Step 6: Run full test suite**

Run: `py -3.13 -m pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add forgeloop/agent/loop.py tests/test_agent_loop_approval.py tests/test_agent_loop.py
git commit -m "feat(agent): rewrite _await_approval with DB polling — approved/denied/timeout"
```

---

## Task 4: Timeout Sweeper

**Files:**
- Create: `forgeloop/server/__init__.py`
- Create: `forgeloop/server/sweeper.py`
- Test: `tests/test_server_sweeper.py`

**Interfaces:**
- Consumes: `forgeloop.storage.db.connect`, `forgeloop.storage.models` (Plan 1 + Task 2)
- Produces: `TimeoutSweeper` class with `start()`, `stop()` methods

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_sweeper.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_server_sweeper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forgeloop.server'`

- [ ] **Step 3: Create server package + sweeper**

```python
# forgeloop/server/__init__.py
```

```python
# forgeloop/server/sweeper.py
from __future__ import annotations
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from forgeloop.storage.db import connect
from forgeloop.storage.models import update_approval_request, update_session_status


class TimeoutSweeper:
    def __init__(self, db_path: Path, approval_timeout_seconds: int, poll_interval: float = 60.0):
        self._db_path = db_path
        self._timeout = approval_timeout_seconds
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._timeout > 0:
                self._sweep()
            self._stop_event.wait(self._poll_interval)

    def _sweep(self) -> None:
        conn = connect(self._db_path, wal=True)
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self._timeout)).isoformat()
            rows = conn.execute(
                "SELECT id, session_id FROM approval_requests WHERE status='PENDING' AND requested_at < ?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                update_approval_request(conn, row["id"], status="TIMEOUT", decided_at=datetime.now(timezone.utc).isoformat())
                update_session_status(conn, row["session_id"], "STOPPED_APPROVAL_TIMEOUT", finished_at=datetime.now(timezone.utc).isoformat())
        finally:
            conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_server_sweeper.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add forgeloop/server/__init__.py forgeloop/server/sweeper.py tests/test_server_sweeper.py
git commit -m "feat(server): timeout sweeper for stale approval requests"
```

---

## Task 5: FastAPI Auth + Schemas

**Files:**
- Create: `forgeloop/server/auth.py`
- Create: `forgeloop/server/schemas.py`
- Test: `tests/test_server_auth.py`

**Interfaces:**
- Consumes: `forgeloop.config.app_config.ServerConfig` (Task 1)
- Produces: `verify_token` (FastAPI dependency), `SessionCreateRequest`, `ApprovalDecisionRequest`, Pydantic response models

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_auth.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from forgeloop.server.auth import verify_token, create_auth_dependency
from forgeloop.config.app_config import ServerConfig


def _app(secret: str):
    app = FastAPI()
    dep = create_auth_dependency(secret)
    @app.get("/protected")
    async def protected(_=dep):
        return {"ok": True}
    return app


def test_no_token_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_wrong_token_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_correct_token_passes():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer my-secret"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_malformed_header_returns_401():
    app = _app("my-secret")
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "my-secret"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_server_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forgeloop.server.auth'`

- [ ] **Step 3: Implement auth.py**

```python
# forgeloop/server/auth.py
from __future__ import annotations
from fastapi import Request, HTTPException


def create_auth_dependency(secret: str):
    async def verify_token(request: Request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})
        token = auth[7:]
        if token != secret:
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})
        return token
    return verify_token
```

- [ ] **Step 4: Implement schemas.py**

```python
# forgeloop/server/schemas.py
from __future__ import annotations
from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    task: str
    workspace: str | None = None


class ApprovalDecisionRequest(BaseModel):
    verdict: str
    reason: str | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_server_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add forgeloop/server/auth.py forgeloop/server/schemas.py tests/test_server_auth.py
git commit -m "feat(server): bearer token auth + Pydantic request schemas"
```

---

## Task 6: FastAPI App + Endpoints

**Files:**
- Create: `forgeloop/server/app.py`
- Test: `tests/test_server_app.py`
- Test: `tests/test_server_approvals.py`

**Interfaces:**
- Consumes: `forgeloop.server.auth.create_auth_dependency` (Task 5), `forgeloop.server.schemas` (Task 5), `forgeloop.storage.db.connect` (Task 2), `forgeloop.storage.models` query functions (Task 2), `forgeloop.config.app_config.AppConfig` (Task 1), `forgeloop.credentials.redact.redact` (Plan 1), `forgeloop.credentials.store.status` (Plan 1)
- Produces: `create_app(config: AppConfig, db_path: Path) -> FastAPI`

- [ ] **Step 1: Write the failing test for session/memory/credential endpoints**

```python
# tests/test_server_app.py
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
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="hello world"))
    conn.close()
    resp = client.get("/memory", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "hello world"


def test_get_memory_with_keyword(tmp_path):
    client, db_path = _make_client(tmp_path)
    conn = connect(db_path, wal=True)
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="hello world", tags="greeting"))
    write_memory(conn, MemoryEntry(workspace_root=str(tmp_path), kind="note", content="goodbye world", tags="farewell"))
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
```

- [ ] **Step 2: Write the failing test for approval endpoints**

```python
# tests/test_server_approvals.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_server_app.py tests/test_server_approvals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forgeloop.server.app'`

- [ ] **Step 4: Implement app.py**

```python
# forgeloop/server/app.py
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from forgeloop.config.app_config import AppConfig
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import (
    list_sessions, get_session, get_turns_for_session, get_actions_for_turn,
    get_action, get_approval_request, list_memory, abort_session,
    update_approval_request, update_session_status,
)
from forgeloop.storage.memory import retrieve_memory
from forgeloop.credentials.store import status as cred_status
from forgeloop.credentials.redact import redact
from forgeloop.server.auth import create_auth_dependency
from forgeloop.server.schemas import SessionCreateRequest, ApprovalDecisionRequest


def create_app(config: AppConfig, db_path: Path) -> FastAPI:
    app = FastAPI(title="ForgeLoop WebUI")
    auth = create_auth_dependency(config.server.secret)

    def get_db():
        conn = connect(db_path, wal=True)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": redact(str(exc))})

    @app.get("/", response_class=HTMLResponse)
    async def root(_=Depends(auth)):
        html_path = Path(__file__).parent.parent / "web" / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        return HTMLResponse("<html><body><h1>ForgeLoop</h1><p>index.html not found</p></body></html>")

    @app.get("/sessions")
    async def list_sessions_endpoint(db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        sessions = list_sessions(db)
        return [
            {"id": s.id, "status": s.status, "task": s.task, "created_at": s.created_at}
            for s in sessions
        ]

    @app.post("/sessions")
    async def create_session_endpoint(req: SessionCreateRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        from forgeloop.storage.models import Session, create_session as _create
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        sid = f"web_{now.replace(':', '-').replace('.', '-')}"
        ws = req.workspace or config.workspace_root
        _create(db, Session(id=sid, task=req.task, workspace_root=ws, status="QUEUED", created_at=now, updated_at=now))
        return {"id": sid, "status": "QUEUED", "task": req.task}

    @app.get("/sessions/{sid}")
    async def get_session_endpoint(sid: str, db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        s = get_session(db, sid)
        if not s:
            raise HTTPException(status_code=404, detail={"error": "session not found"})
        turns = get_turns_for_session(db, sid)
        turn_list = []
        for t in turns:
            actions = get_actions_for_turn(db, t.id)
            turn_list.append({
                "id": t.id,
                "round": t.turn_index,
                "parse_status": t.parse_status,
                "actions": [
                    {
                        "id": a.id,
                        "tool": a.tool,
                        "args": json.loads(a.args) if a.args else None,
                        "thought": a.thought,
                        "status": a.status,
                        "result": json.loads(a.result) if a.result else None,
                        "feedback_signal": json.loads(a.feedback_signal) if a.feedback_signal else None,
                    }
                    for a in actions
                ],
            })
        return {
            "id": s.id,
            "status": s.status,
            "task": s.task,
            "created_at": s.created_at,
            "turns": turn_list,
        }

    @app.post("/sessions/{sid}/abort")
    async def abort_session_endpoint(sid: str, db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        s = get_session(db, sid)
        if not s:
            raise HTTPException(status_code=404, detail={"error": "session not found"})
        abort_session(db, sid)
        return {"ok": True, "status": "ABORTED"}

    @app.get("/approvals")
    async def list_approvals_endpoint(db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        from forgeloop.storage.models import list_pending_approvals
        pending = list_pending_approvals(db)
        result = []
        for ar in pending:
            action = get_action(db, ar.action_id)
            result.append({
                "id": ar.id,
                "session_id": ar.session_id,
                "action_id": ar.action_id,
                "action": {
                    "tool": action.tool if action else None,
                    "args": json.loads(action.args) if action and action.args else None,
                    "thought": action.thought if action else None,
                } if action else None,
                "requested_at": ar.requested_at,
            })
        return result

    @app.post("/approvals/{arid}/decision")
    async def approval_decision_endpoint(arid: str, req: ApprovalDecisionRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        ar = get_approval_request(db, arid)
        if not ar:
            raise HTTPException(status_code=404, detail={"error": "approval request not found"})
        if req.verdict == "approve":
            update_approval_request(db, arid, status="APPROVED", decided_at=_now(), decided_by="webui")
            update_session_status(db, ar.session_id, "RUNNING")
            return {"ok": True, "status": "APPROVED"}
        elif req.verdict == "deny":
            update_approval_request(db, arid, status="DENIED", decided_at=_now(), decided_by="webui", deny_reason=req.reason or "")
            update_session_status(db, ar.session_id, "RUNNING")
            return {"ok": True, "status": "DENIED"}
        else:
            raise HTTPException(status_code=400, detail={"error": f"invalid verdict: {req.verdict}"})

    @app.get("/memory")
    async def list_memory_endpoint(keyword: str | None = None, db: sqlite3.Connection = Depends(get_db), _=Depends(auth)):
        if keyword:
            entries = retrieve_memory(db, config.workspace_root, [keyword])
        else:
            entries = list_memory(db, config.workspace_root)
        return [
            {
                "id": e.id,
                "kind": e.kind,
                "content": e.content,
                "tags": e.tags,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in entries
        ]

    @app.get("/credentials")
    async def credentials_endpoint(_=Depends(auth)):
        st = cred_status("openai")
        return st

    return app


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_server_app.py tests/test_server_approvals.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run full test suite**

Run: `py -3.13 -m pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add forgeloop/server/app.py tests/test_server_app.py tests/test_server_approvals.py
git commit -m "feat(server): FastAPI app with 9 endpoints — sessions, approvals, memory, credentials"
```

---

## Task 7: CLI

**Files:**
- Create: `forgeloop/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `forgeloop.config.app_config.load_app_config` (Task 1), `forgeloop.storage.db.connect/init_schema` (Task 2), `forgeloop.server.app.create_app` (Task 6), `forgeloop.server.sweeper.TimeoutSweeper` (Task 4), `forgeloop.agent.loop.AgentLoop` (Plan 1 + Task 3), `forgeloop.llm.real.RealLLMProvider` (Plan 1), `forgeloop.llm.mock.MockLLMProvider` (Plan 1), `forgeloop.tools.base.ToolRegistry` (Plan 1), all 6 tools (Plan 1)
- Produces: `main()` function (console_scripts entry point), `parse_args(argv) -> Namespace`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock
from forgeloop.cli import parse_args


def test_parse_args_defaults():
    args = parse_args(["run", "--task", "fix tests"])
    assert args.task == "fix tests"
    assert args.workspace == "."
    assert args.config == "./forgeloop.yaml"
    assert args.host is None
    assert args.port is None
    assert args.max_rounds is None


def test_parse_args_all_flags():
    args = parse_args(["run", "--task", "fix tests", "--workspace", "/tmp/ws", "--config", "/etc/fl.yaml", "--host", "0.0.0.0", "--port", "9000", "--max-rounds", "10"])
    assert args.task == "fix tests"
    assert args.workspace == "/tmp/ws"
    assert args.config == "/etc/fl.yaml"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.max_rounds == 10


def test_parse_args_missing_task():
    import pytest
    with pytest.raises(SystemExit):
        parse_args(["run"])


def test_main_runs_agent_loop(tmp_path):
    from forgeloop.cli import main
    import sys

    config_path = tmp_path / "forgeloop.yaml"
    config_path.write_text(
        f"workspace_root: {tmp_path}\n"
        "llm:\n"
        "  model: mock\n"
        "server:\n"
        "  host: 127.0.0.1\n"
        "  port: 0\n"
        "  secret: test-secret\n"
        "agent:\n"
        "  max_rounds: 5\n"
        "  parse_fail_limit: 3\n"
        "  approval_timeout_seconds: 0\n"
        "guardrails:\n"
        "  default_decision: Allow\n"
    )
    argv = ["forgeloop", "run", "--task", "do stuff", "--config", str(config_path), "--workspace", str(tmp_path)]
    with patch.object(sys, "argv", argv):
        with patch("forgeloop.cli.RealLLMProvider") as MockLLM:
            from forgeloop.llm.mock import MockLLMProvider
            MockLLM.return_value = MockLLMProvider(responses=[
                '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
            ])
            exit_code = main()
    assert exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forgeloop.cli'`

- [ ] **Step 3: Implement cli.py**

```python
# forgeloop/cli.py
from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from pathlib import Path

from forgeloop.config.app_config import load_app_config
from forgeloop.storage.db import connect, init_schema
from forgeloop.storage.models import get_session
from forgeloop.agent.loop import AgentLoop
from forgeloop.agent.session import is_terminal
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.real import RealLLMProvider
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="forgeloop")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--task", required=True)
    run_p.add_argument("--workspace", default=".")
    run_p.add_argument("--config", default="./forgeloop.yaml")
    run_p.add_argument("--host", default=None)
    run_p.add_argument("--port", type=int, default=None)
    run_p.add_argument("--max-rounds", type=int, default=None)
    return parser.parse_args(argv)


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def _scan_pending_approvals(conn) -> None:
    rows = conn.execute(
        "SELECT id FROM sessions WHERE status='PENDING_APPROVAL'"
    ).fetchall()
    for row in rows:
        print(f"WARNING: Session {row['id']} has pending approval, check WebUI")


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.command != "run":
        print(f"Unknown command: {args.command}")
        return 1

    cli_overrides = {}
    if args.host:
        cli_overrides["host"] = args.host
    if args.port:
        cli_overrides["port"] = args.port
    if args.max_rounds:
        cli_overrides["max_rounds"] = args.max_rounds
    if args.workspace:
        cli_overrides["workspace"] = args.workspace

    config_path = Path(args.config)
    config = load_app_config(config_path if config_path.exists() else None, cli_overrides)

    db_path = Path(config.workspace_root) / "forgeloop.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)

    _scan_pending_approvals(conn)

    from forgeloop.server.app import create_app
    from forgeloop.server.sweeper import TimeoutSweeper
    import uvicorn

    app = create_app(config, db_path)
    server = uvicorn.Server(uvicorn.Config(app, host=config.server.host, port=config.server.port, log_level="warning"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    sweeper = TimeoutSweeper(db_path, config.agent.approval_timeout_seconds, poll_interval=60.0)
    sweeper.start()

    print(f"WebUI: http://{config.server.host}:{config.server.port}")
    print(f"Secret: {config.server.secret}")

    if config.llm.model == "mock":
        llm = MockLLMProvider(responses=['{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'])
    else:
        llm = RealLLMProvider()

    registry = _build_registry()
    loop = AgentLoop(
        llm=llm,
        llm_config=config.llm,
        config=config.guardrails,
        registry=registry,
        conn=conn,
        workspace_root=config.workspace_root,
        task=args.task,
        max_rounds=config.agent.max_rounds,
        parse_fail_limit=config.agent.parse_fail_limit,
    )

    status = loop.run()
    print(f"Final status: {status}")

    sweeper.stop()
    server.should_exit = True
    conn.close()
    return 0 if is_terminal(status) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite**

Run: `py -3.13 -m pytest -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add forgeloop/cli.py tests/test_cli.py
git commit -m "feat(cli): forgeloop run command with argparse + startup sequence"
```

---

## Task 8: Frontend HTML

**Files:**
- Create: `forgeloop/web/index.html`

**Interfaces:**
- Consumes: FastAPI endpoints from Task 6
- Produces: Single-page HTML+JS frontend served at `GET /`

- [ ] **Step 1: Create the frontend HTML**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ForgeLoop</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: monospace; background: #1a1a1a; color: #e0e0e0; padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header h1 { font-size: 1.5rem; }
.tabs { display: flex; gap: 10px; }
.tab { padding: 8px 16px; background: #2a2a2a; border: 1px solid #444; cursor: pointer; border-radius: 4px; }
.tab.active { background: #3a3a3a; border-color: #666; }
.content { background: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 16px; min-height: 400px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid #444; }
th { color: #888; font-size: 0.85rem; text-transform: uppercase; }
.btn { padding: 6px 12px; border: 1px solid #666; background: #333; color: #e0e0e0; cursor: pointer; border-radius: 4px; }
.btn:hover { background: #444; }
.btn-approve { border-color: #4a4; color: #4f4; }
.btn-deny { border-color: #a44; color: #f44; }
input, textarea { background: #1a1a1a; color: #e0e0e0; border: 1px solid #555; padding: 6px; border-radius: 4px; width: 100%; }
.turn { margin-bottom: 12px; padding: 8px; background: #222; border-radius: 4px; }
.turn-header { font-size: 0.85rem; color: #888; margin-bottom: 4px; }
.action { padding: 4px 8px; margin: 4px 0; background: #1a1a1a; border-radius: 4px; font-size: 0.9rem; }
.status-SUCCEEDED { color: #4f4; }
.status-FAILED { color: #f44; }
.status-PENDING_APPROVAL { color: #ff4; }
.status-BLOCKED_BY_GUARDRAIL { color: #f84; }
.status-APPROVED { color: #4f4; }
.status-DENIED { color: #f44; }
.status-EXECUTING { color: #4ff; }
.hidden { display: none; }
</style>
</head>
<body>
<div class="header">
<h1>ForgeLoop</h1>
<div class="tabs">
<div class="tab active" onclick="showTab('sessions')">Sessions</div>
<div class="tab" onclick="showTab('approvals')">Approvals</div>
<div class="tab" onclick="showTab('memory')">Memory</div>
</div>
</div>
<div class="content">
<div id="sessions-tab">
<div style="margin-bottom:12px;">
<input type="text" id="new-task" placeholder="Task description..." style="width:60%;">
<button class="btn" onclick="startSession()">Start</button>
</div>
<table>
<thead><tr><th>ID</th><th>Status</th><th>Task</th><th>Created</th><th></th></tr></thead>
<tbody id="sessions-list"></tbody>
</table>
<div id="session-detail" class="hidden"></div>
</div>
<div id="approvals-tab" class="hidden">
<div id="approvals-list"></div>
</div>
<div id="memory-tab" class="hidden">
<input type="text" id="mem-keyword" placeholder="Search keyword..." style="width:50%; margin-bottom:12px;" oninput="loadMemory()">
<div id="memory-list"></div>
</div>
</div>
<script>
let token = sessionStorage.getItem('forgeloop-secret') || '';
if (!token) { token = prompt('Enter secret:'); sessionStorage.setItem('forgeloop-secret', token); }
function headers() { return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}; }
function showTab(name) {
document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
event.target.classList.add('active');
document.querySelectorAll('[id$="-tab"]').forEach(t => t.classList.add('hidden'));
document.getElementById(name + '-tab').classList.remove('hidden');
}
async function loadSessions() {
const r = await fetch('/sessions', {headers: headers()});
const data = await r.json();
const tbody = document.getElementById('sessions-list');
tbody.innerHTML = data.map(s => `<tr><td>${s.id.slice(0,8)}</td><td class="status-${s.status}">${s.status}</td><td>${s.task}</td><td>${s.created_at}</td><td><button class="btn" onclick="loadSession('${s.id}')">View</button> <button class="btn btn-deny" onclick="abortSession('${s.id}')">Abort</button></td></tr>`).join('');
}
async function loadSession(id) {
const r = await fetch('/sessions/' + id, {headers: headers()});
const s = await r.json();
const detail = document.getElementById('session-detail');
detail.classList.remove('hidden');
detail.innerHTML = `<h3>Session ${s.id.slice(0,8)} — ${s.status}</h3><p>Task: ${s.task}</p>` + s.turns.map(t => `<div class="turn"><div class="turn-header">Turn ${t.round} — ${t.parse_status}</div>${(t.actions||[]).map(a => `<div class="action"><span class="status-${a.status}">${a.status}</span> <b>${a.tool}</b> ${JSON.stringify(a.args||{})}<br><span style="color:#888;">${a.thought||''}</span>${a.result?'<br><pre>'+JSON.stringify(a.result,null,2)+'</pre>':''}${a.feedback_signal?'<br><span style="color:#ff4;">[FEEDBACK]</span> '+JSON.stringify(a.feedback_signal):''}</div>`).join('')}</div>`).join('');
}
async function startSession() {
const task = document.getElementById('new-task').value;
if (!task) return;
const r = await fetch('/sessions', {method:'POST', headers: headers(), body: JSON.stringify({task})});
const data = await r.json();
loadSessions();
}
async function abortSession(id) {
await fetch('/sessions/'+id+'/abort', {method:'POST', headers: headers()});
loadSessions();
}
async function loadApprovals() {
const r = await fetch('/approvals', {headers: headers()});
const data = await r.json();
const list = document.getElementById('approvals-list');
list.innerHTML = data.map(a => `<div class="action"><b>${a.action?a.action.tool:'?'}</b> ${a.action?JSON.stringify(a.action.args||{}):''}<br><span style="color:#888;">${a.action?a.action.thought:''}</span><br><button class="btn btn-approve" onclick="decideApproval('${a.id}','approve')">Approve</button> <input type="text" id="deny-reason-${a.id}" placeholder="Reason..." style="width:40%;"><button class="btn btn-deny" onclick="decideApproval('${a.id}','deny')">Deny</button></div>`).join('') || '<p>No pending approvals</p>';
}
async function decideApproval(id, verdict) {
const reason = document.getElementById('deny-reason-'+id)?.value || null;
await fetch('/approvals/'+id+'/decision', {method:'POST', headers: headers(), body: JSON.stringify({verdict, reason})});
loadApprovals();
}
async function loadMemory() {
const kw = document.getElementById('mem-keyword').value;
const url = kw ? '/memory?keyword='+encodeURIComponent(kw) : '/memory';
const r = await fetch(url, {headers: headers()});
const data = await r.json();
const list = document.getElementById('memory-list');
list.innerHTML = data.map(m => `<div class="action"><b>[${m.kind}]</b> ${m.content}<br><span style="color:#888;">${m.tags||''} ${m.updated_at}</span></div>`).join('') || '<p>No memory entries</p>';
}
loadSessions();
loadApprovals();
setInterval(loadSessions, 3000);
setInterval(loadApprovals, 3000);
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the HTML is served correctly**

Run: `py -3.13 -m pytest tests/test_server_app.py::test_get_root_html -v`
Expected: PASS (already tested in Task 6)

- [ ] **Step 3: Commit**

```bash
git add forgeloop/web/index.html
git commit -m "feat(web): single-page HTML+JS frontend with sessions/approvals/memory tabs"
```

---

## Task 9: E2E Approval Flow Test

**Files:**
- Create: `tests/test_e2e_approval_flow.py`

**Interfaces:**
- Consumes: All components from Tasks 1-8
- Produces: Full integration test verifying the threading + DB polling + WebUI integration

- [ ] **Step 1: Write the E2E test**

```python
# tests/test_e2e_approval_flow.py
import json
import threading
import time
from pathlib import Path
from fastapi.testclient import TestClient
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.storage.db import connect, init_schema
from forgeloop.agent.loop import AgentLoop
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool
from forgeloop.server.app import create_app


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def test_e2e_approval_flow(tmp_workspace):
    db_path = tmp_workspace / "t.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)
    cfg = GuardrailsConfig(workspace_root=str(tmp_workspace))
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"write file","tool":"write_file","args":{"path":"src/new.py","mode":"overwrite","content":"x"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(
        llm=mock, llm_config=LLMConfig(model="mock"), config=cfg,
        registry=_registry(), conn=conn, workspace_root=str(tmp_workspace),
        task="write then done",
    )
    app_cfg = AppConfig(
        workspace_root=str(tmp_workspace),
        llm=LLMConfig(model="mock"),
        server=ServerConfig(host="127.0.0.1", port=8000, secret="e2e-secret"),
        agent=AgentConfig(),
        guardrails=cfg,
    )
    app = create_app(app_cfg, db_path)
    client = TestClient(app)
    status = [None]

    def _run_loop():
        status[0] = loop.run()

    t = threading.Thread(target=_run_loop)
    t.start()

    for _ in range(100):
        resp = client.get("/approvals", headers={"Authorization": "Bearer e2e-secret"})
        approvals = resp.json()
        if approvals:
            ar_id = approvals[0]["id"]
            client.post(
                f"/approvals/{ar_id}/decision",
                json={"verdict": "approve"},
                headers={"Authorization": "Bearer e2e-secret"},
            )
            break
        time.sleep(0.05)

    t.join(timeout=10)
    assert status[0] == "COMPLETED"
    ars = conn.execute("SELECT status FROM approval_requests").fetchall()
    assert ars[0]["status"] == "APPROVED"
    acts = conn.execute("SELECT status FROM actions WHERE tool='write_file'").fetchone()
    assert acts["status"] == "SUCCEEDED"
    assert (tmp_workspace / "src" / "new.py").read_text(encoding="utf-8") == "x"
    conn.close()


def test_e2e_deny_flow(tmp_workspace):
    db_path = tmp_workspace / "t.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)
    cfg = GuardrailsConfig(workspace_root=str(tmp_workspace))
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"write file","tool":"write_file","args":{"path":"src/new.py","mode":"overwrite","content":"x"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(
        llm=mock, llm_config=LLMConfig(model="mock"), config=cfg,
        registry=_registry(), conn=conn, workspace_root=str(tmp_workspace),
        task="write then done",
    )
    app_cfg = AppConfig(
        workspace_root=str(tmp_workspace),
        llm=LLMConfig(model="mock"),
        server=ServerConfig(host="127.0.0.1", port=8000, secret="e2e-secret"),
        agent=AgentConfig(),
        guardrails=cfg,
    )
    app = create_app(app_cfg, db_path)
    client = TestClient(app)
    status = [None]

    def _run_loop():
        status[0] = loop.run()

    t = threading.Thread(target=_run_loop)
    t.start()

    for _ in range(100):
        resp = client.get("/approvals", headers={"Authorization": "Bearer e2e-secret"})
        approvals = resp.json()
        if approvals:
            ar_id = approvals[0]["id"]
            client.post(
                f"/approvals/{ar_id}/decision",
                json={"verdict": "deny", "reason": "not allowed"},
                headers={"Authorization": "Bearer e2e-secret"},
            )
            break
        time.sleep(0.05)

    t.join(timeout=10)
    assert status[0] == "COMPLETED"
    ars = conn.execute("SELECT status FROM approval_requests").fetchall()
    assert ars[0]["status"] == "DENIED"
    acts = conn.execute("SELECT status FROM actions WHERE tool='write_file' AND status='DENIED'").fetchall()
    assert len(acts) == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_e2e_approval_flow.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Run full test suite**

Run: `py -3.13 -m pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_approval_flow.py
git commit -m "test(e2e): full approval flow — mock LLM + TestClient + agent loop threading"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Task |
|---|---|
| §2 Cross-Cutting Decisions | Task 1 (config), Task 6 (auth), Task 4 (sweeper) |
| §3 Process Architecture | Task 7 (CLI threads), Task 4 (sweeper thread) |
| §4 CLI | Task 7 |
| §5 Config File | Task 1 |
| §6.1 Auth | Task 5 |
| §6.2 Endpoints (9 total) | Task 6 |
| §6.3 Response Shapes | Task 6 |
| §6.4 Error Handling | Task 6 (global exception handler + redact) |
| §7 HITL Approval Flow | Task 3 (_await_approval rewrite) |
| §7.3 Crash Recovery | Task 7 (_scan_pending_approvals) |
| §7.4 SQLite WAL Mode | Task 2 |
| §8 Timeout Sweeper | Task 4 |
| §9 Frontend | Task 8 |
| §10 File Structure | All tasks match spec's file list |
| §11 Testing Strategy | All test files created |
| §12 Dependencies | Task 1 (pyproject.toml) |
| §13 Scope Boundaries | In-scope items all covered; out-of-scope items excluded |

### Placeholder Scan

No placeholders found. All steps contain complete code.

### Type Consistency

- `AppConfig` used consistently across Tasks 1, 6, 7, 9
- `ServerConfig.secret` used in Tasks 1, 5, 6, 7, 9
- `connect(db_path, wal=True)` used consistently in Tasks 2, 4, 6, 7, 9
- `_await_approval(ar_id, poll_interval)` signature consistent in Task 3
- `create_app(config, db_path)` used consistently in Tasks 6, 7, 9
- `TimeoutSweeper(db_path, approval_timeout_seconds, poll_interval)` consistent in Tasks 4, 7
