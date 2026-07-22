# ForgeLoop CLI + WebUI — Design Spec (Plan 2 of 3)

> **Status**: Approved (all 7 sections reviewed by user on 2026-07-22)
> **Depends on**: Plan 1 core library (`docs/superpowers/specs/2026-07-19-forgeloop-design.md`)

## 1. Goal

Build the CLI entrypoint and FastAPI WebUI for ForgeLoop. The user runs `forgeloop run --task "..."` which starts the agent loop and a local web server in a single process. The WebUI provides session trajectory viewing, HITL approval queue, memory browser, and credential status. This is Plan 2 of 3 (Plan 3 = Docker + PyPI packaging).

## 2. Cross-Cutting Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Process model | Single process, 3 threads (agent loop, uvicorn, timeout sweeper) | Simplest; agent loop stays synchronous from Plan 1; no IPC |
| CLI scope | `run` only | Session/approval/abort/credentials/memory all via WebUI |
| Config | Single `forgeloop.yaml` | One file for workspace, LLM, server, agent, guardrails |
| Approval blocking | DB polling every 2s | Works across restarts; no extra plumbing; ≤2s latency |
| Frontend | Vanilla HTML+JS, no framework | Course project; no build step; single `index.html` |
| Auth | Bearer token (shared secret in config) | Single-user; all endpoints require `Authorization: Bearer <secret>` |

## 3. Process Architecture

```
┌─ forgeloop run --task "..." ──────────────────────────────┐
│                                                            │
│  Main thread                Background thread 1            │
│  ┌──────────────┐          ┌──────────────────┐           │
│  │ AgentLoop    │          │ uvicorn server  │           │
│  │ .run()       │◄──shared──│ (FastAPI app)   │           │
│  │              │  SQLite   │                  │           │
│  │ _await_      │  DB (WAL)│ POST /approvals/ │           │
│  │ approval()   │◄────────│ {id}/decision    │           │
│  │ polls DB     │          │                  │           │
│  │ every 2s     │          │ GET /sessions    │           │
│  └──────────────┘          └──────────────────┘           │
│                                                            │
│  Background thread 2                                      │
│  ┌──────────────────┐                                     │
│  │ Timeout sweeper  │  checks every 60s                   │
│  │ (approval 24h)   │  for timed-out approvals            │
│  └──────────────────┘                                     │
└────────────────────────────────────────────────────────────┘
```

- **Main thread**: runs `AgentLoop.run()` (synchronous, from Plan 1). Blocks until terminal status.
- **Background thread 1**: uvicorn server running the FastAPI app. Handles all HTTP requests.
- **Background thread 2**: timeout sweeper. Every 60s, queries for PENDING approvals older than `approval_timeout_seconds`. If found, marks them TIMEOUT and sets session status to `STOPPED_APPROVAL_TIMEOUT`.
- **Shared state**: SQLite DB in WAL mode (`PRAGMA journal_mode=WAL`). Agent loop writes turns/actions; WebUI reads them; WebUI writes approval decisions; agent loop reads them.
- **Thread safety**: SQLite WAL mode allows concurrent readers + one writer. All DB connections are per-thread (not shared across threads). The `connect()` function from Plan 1 is called independently by each thread.

## 4. CLI

```
forgeloop run --task "fix the failing tests" [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--task` | (required) | Task description for the agent |
| `--workspace` | `.` | Workspace root path (fenced) |
| `--config` | `./forgeloop.yaml` | Config file path |
| `--host` | `127.0.0.1` | WebUI bind host |
| `--port` | `8000` | WebUI bind port |
| `--max-rounds` | from config | Override max rounds |

**Startup sequence:**
1. Parse args with `argparse`.
2. Load `forgeloop.yaml` (CLI flags override config values).
3. Init SQLite DB (`forgeloop.db` in workspace root) with `init_schema()`.
4. Set `PRAGMA journal_mode=WAL` on the DB connection.
5. Start uvicorn in background thread (FastAPI app, bound to host:port).
6. Start timeout sweeper in background thread.
7. Print WebUI URL + shared secret to terminal.
8. Create Session row in DB (status=RUNNING).
9. Run `AgentLoop.run()` in main thread (blocks until terminal status).
10. Print final status, exit.

**No other subcommands.** Session listing, approval, abort, credentials, memory — all via WebUI.

## 5. Config File (`forgeloop.yaml`)

```yaml
# forgeloop.yaml — single config file for everything

workspace_root: .

llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com/v1
  # API key from keyring (never in this file)
  # Set via: forgeloop credentials set  (Plan 3)
  # Or fallback: OPENAI_API_KEY env var

server:
  host: 127.0.0.1
  port: 8000
  secret: <random-64-char-string>  # bearer token for WebUI

agent:
  max_rounds: 50
  parse_fail_limit: 3
  approval_timeout_seconds: 86400  # 24h; 0 = never

# Guardrails override (merges with built-in default by rule id)
guardrails:
  default_decision: RequireApproval
  rules:
    - id: approve_all_writes   # override built-in: auto-approve writes
      tool: write_file
      match: { any: true }
      decision: Allow
  hitl:
    approval_timeout_seconds: 86400
    auto_approve_on_timeout: false
  done_post_check:
    require_green_tests: false
```

**Loading priority** (latter overrides former):
1. Built-in `forgeloop/config/guardrails.default.yaml` (Plan 1)
2. `forgeloop.yaml` (this file)
3. CLI flags (`--max-rounds`, `--host`, etc.)

**Secret generation**: if `server.secret` is empty or missing, generate a random 64-char token, print it to terminal at startup, and use it for the session. Not persisted to the file — user must add it to yaml for persistence.

**Config dataclass** (`forgeloop/config/app_config.py`):
```python
@dataclass
class AppConfig:
    workspace_root: str
    llm: LLMConfig          # model, base_url
    server: ServerConfig     # host, port, secret
    agent: AgentConfig       # max_rounds, parse_fail_limit, approval_timeout_seconds
    guardrails: GuardrailsConfig  # from Plan 1
```

## 6. FastAPI WebUI

### 6.1 Auth

Bearer token middleware. All endpoints require `Authorization: Bearer <secret>`. Missing or wrong token → 401 `{"error": "unauthorized"}`.

Implementation: FastAPI dependency that reads the `Authorization` header, compares against `config.server.secret`. Injected via `Depends(verify_token)`.

### 6.2 Endpoints

| Method | Path | Description | Request body |
|---|---|---|---|
| `GET` | `/` | HTML frontend (single page) | — |
| `GET` | `/sessions` | List all sessions (id, status, task, created_at) | — |
| `POST` | `/sessions` | Start session | `{task: str, workspace?: str}` |
| `GET` | `/sessions/{id}` | Session detail: turns + actions + feedback | — |
| `POST` | `/sessions/{id}/abort` | Abort session → status=ABORTED | — |
| `GET` | `/approvals` | Pending approval queue | — |
| `POST` | `/approvals/{id}/decision` | Approve/deny | `{verdict: "approve"\|"deny", reason?: str}` |
| `GET` | `/memory` | Memory entries (optional `?keyword=foo`) | — |
| `GET` | `/credentials` | Credential status | — |

### 6.3 Response Shapes

**`GET /sessions`**:
```json
[{"id": "s1", "status": "RUNNING", "task": "fix tests", "created_at": "2026-07-22T14:32:00"}]
```

**`GET /sessions/{id}`**:
```json
{
  "id": "s1",
  "status": "RUNNING",
  "task": "fix tests",
  "created_at": "2026-07-22T14:32:00",
  "turns": [
    {
      "id": "t1",
      "round": 1,
      "actions": [
        {
          "id": "a1",
          "tool": "read_file",
          "args": {"path": "src/main.py"},
          "status": "SUCCEEDED",
          "result": "...",
          "feedback_text": null
        }
      ]
    }
  ]
}
```

**`GET /approvals`**:
```json
[
  {
    "id": "ap1",
    "session_id": "s1",
    "action_id": "a3",
    "action": {"tool": "write_file", "args": {"path": "src/new.py", "mode": "overwrite", "content": "..."}},
    "requested_at": "2026-07-22T14:35:00"
  }
]
```

**`POST /approvals/{id}/decision`**:
```json
// Request
{"verdict": "approve", "reason": null}
// Response
{"ok": true, "status": "APPROVED"}
```

**`GET /credentials`**:
```json
{"configured": true, "last_four": "abcd"}
```

### 6.4 Error Handling

All endpoints return `{"error": "msg"}` with appropriate HTTP status (400, 404, 500). No raw exceptions leaked — the `redact` module from Plan 1 scrubs any API keys from error messages. Global exception handler catches `Exception`, redacts, returns 500.

## 7. HITL Approval Flow

### 7.1 `_await_approval` Rewrite

Replaces Plan 1's no-op stub in `forgeloop/agent/loop.py`:

```
guardrail → RequireApproval
  → create ApprovalRequest(status=PENDING, action_id, requested_at)
  → Session.status = PENDING_APPROVAL
  → update session status in DB
  → poll loop (every 2s):
      SELECT status, deny_reason FROM approval_requests WHERE id=?
      ├ PENDING  → sleep 2s, poll again
      ├ APPROVED → Session.status=RUNNING, return "approved"
      └ DENIED   → Session.status=RUNNING, return "denied"
  → timeout sweeper (bg thread, 60s interval):
      SELECT * FROM approval_requests
      WHERE status='PENDING'
        AND requested_at < now() - approval_timeout_seconds
      → update status=TIMEOUT
      → Session.status=STOPPED_APPROVAL_TIMEOUT
```

### 7.2 Agent Loop Integration

- `_await_approval` returns `"approved"` / `"denied"` / `"timeout"`
- `"approved"` → execute the action, continue loop
- `"denied"` → feed back "用户拒绝：{reason}", continue loop
- `"timeout"` → `check_shutdown` returns `STOPPED_APPROVAL_TIMEOUT`, loop exits

### 7.3 Crash Recovery

On `forgeloop run` startup, scan for sessions with `status=PENDING_APPROVAL`. If found, print warning: "Session {id} has pending approval, check WebUI". The agent loop does not auto-resume crashed sessions — the user starts a new session. The WebUI shows the pending approval from the old session; user can decide (the DB row persists). A future `forgeloop resume` command (Plan 3) could pick it up.

### 7.4 SQLite WAL Mode

`PRAGMA journal_mode=WAL` enables concurrent reads (WebUI) and writes (agent loop) without blocking. Set once on the DB connection during initialization. Each thread opens its own connection via `connect()`.

## 8. Timeout Sweeper

Background thread started at CLI startup. Runs every 60 seconds.

**Logic:**
1. Query: `SELECT id, session_id FROM approval_requests WHERE status='PENDING' AND requested_at < datetime('now', '-approval_timeout_seconds seconds')`
2. For each timed-out approval:
   - Update `approval_requests.status = 'TIMEOUT'`
   - Update `sessions.status = 'STOPPED_APPROVAL_TIMEOUT'`
3. The agent loop's poll will see the session status change and exit.

**Edge case**: if `approval_timeout_seconds = 0`, the sweeper skips (never times out).

## 9. Frontend (HTML+JS, no framework)

Single HTML page served at `GET /`. Vanilla JS `fetch` calls with `Authorization: Bearer <secret>` header.

### 9.1 Layout

```
┌─────────────────────────────────────────────────────┐
│  ForgeLoop          [Sessions] [Approvals] [Memory] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Sessions tab:                                      │
│  ┌────────────────────────────────────────────┐     │
│  │ ID    Status    Task           Created     │     │
│  │ s1    RUNNING   fix tests      14:32       │     │
│  │ s2    COMPLETED refactor parser 13:01      │     │
│  └────────────────────────────────────────────┘     │
│  [Start new session: task input] [Abort]            │
│                                                     │
│  Click session → trajectory view:                   │
│  Turn 1: thought="read file" → read_file(src/a.py)  │
│         → SUCCEEDED, content="..."                  │
│  Turn 2: thought="run tests" → run_tests()           │
│         → FAILED, [FEEDBACK] 2 failed...            │
│                                                     │
│  Approvals tab:                                     │
│  ┌────────────────────────────────────────────┐     │
│  │ Pending: write_file(src/new.py)            │     │
│  │ [Approve]  [Deny: reason input]           │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  Memory tab:                                       │
│  [keyword search] → list of memory entries          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 9.2 Behavior

- **Auto-refresh**: Sessions and Approvals tabs poll every 3s via `setInterval`.
- **Trajectory**: expandable per-turn, shows thought/action/result/feedback.
- **No build step**: single `index.html` with inline CSS+JS, served by FastAPI's `HTMLResponse`.
- **Secret**: user enters secret in a prompt on first load, stored in `sessionStorage`, sent as `Authorization: Bearer <secret>` header on every fetch.

## 10. File Structure (new files in Plan 2)

```
forgeloop/
  cli.py                 # argparse + startup sequence
  config/
    app_config.py         # AppConfig dataclass + load_app_config()
  server/
    __init__.py
    app.py               # FastAPI app, routes, auth dependency
    auth.py              # verify_token dependency
    schemas.py           # Pydantic request/response models
    sweeper.py           # timeout sweeper thread
  web/
    index.html           # single-page frontend
tests/
  test_cli.py
  test_server_app.py
  test_server_auth.py
  test_server_approvals.py
  test_server_sweeper.py
  test_e2e_approval_flow.py
```

## 11. Testing Strategy

**Hard constraint #5**: every mechanism must have a deterministic unit test with mock LLM / no network.

| Test area | Approach | Key tests |
|---|---|---|
| CLI arg parsing | `argparse` unit test, no subprocess | flags override config |
| Config loading | `forgeloop.yaml` parse + merge with defaults | priority order, secret generation |
| FastAPI endpoints | `TestClient` (Starlette), in-memory SQLite | all 9 endpoints, auth 401 |
| Approval flow | `TestClient` + mock DB with pre-set statuses | approved/denied/timeout paths |
| Timeout sweeper | Fast-forward timestamps in DB | triggers STOPPED_APPROVAL_TIMEOUT |
| Frontend | Not unit-tested (vanilla JS, manual) | — |
| End-to-end | MockLLMProvider + TestClient + real loop | start → approval → done |

**Key test**: `test_e2e_approval_flow` — mock LLM emits write_file (RequireApproval) → TestClient POSTs approve → agent loop resumes → mock LLM emits done → COMPLETED. Verifies the full threading + DB polling + WebUI integration.

**No new deps**: FastAPI + uvicorn + httpx (already in Plan 1 deps). TestClient comes with Starlette/FastAPI.

## 12. Dependencies

| Package | Purpose | Already in Plan 1? |
|---|---|---|
| `fastapi` | WebUI framework | No (Plan 1 listed it as future dep) |
| `uvicorn` | ASGI server | No |
| `httpx` | LLM calls + TestClient | Yes |
| `pyyaml` | Config loading | Yes |
| `keyring` | Credential storage | Yes |
| `pytest` | Testing | Yes |

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
server = ["fastapi", "uvicorn"]
```

## 13. Scope Boundaries

**In scope (Plan 2):**
- CLI `run` command
- FastAPI WebUI with 9 endpoints
- HITL approval flow (DB polling)
- Timeout sweeper
- Vanilla HTML+JS frontend
- Config file loading (`forgeloop.yaml`)
- SQLite WAL mode

**Out of scope (deferred to Plan 3):**
- PyPI packaging (`pip install forgeloop`)
- Docker image
- `forgeloop credentials set/show` CLI commands
- `forgeloop resume <id>` CLI command
- `forgeloop serve` (WebUI-only mode)
- Multi-session concurrent execution
- WebSocket live updates (polling is sufficient)
