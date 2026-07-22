from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
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
from forgeloop.server.auth import create_auth_dependency, register_auth_handler
from forgeloop.server.schemas import SessionCreateRequest, ApprovalDecisionRequest


def create_app(config: AppConfig, db_path: Path) -> FastAPI:
    app = FastAPI(title="ForgeLoop WebUI")
    register_auth_handler(app)
    auth = create_auth_dependency(config.server.secret)

    def get_db():
        conn = connect(db_path, wal=True, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": redact(str(exc))})

    @app.exception_handler(FastAPIHTTPException)
    async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail["error"]})
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    @app.get("/", response_class=HTMLResponse)
    async def root(_=auth):
        html_path = Path(__file__).parent.parent / "web" / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        return HTMLResponse("<html><body><h1>ForgeLoop</h1><p>index.html not found</p></body></html>")

    @app.get("/sessions")
    async def list_sessions_endpoint(db: sqlite3.Connection = Depends(get_db), _=auth):
        sessions = list_sessions(db)
        return [
            {"id": s.id, "status": s.status, "task": s.task, "created_at": s.created_at}
            for s in sessions
        ]

    @app.post("/sessions")
    async def create_session_endpoint(req: SessionCreateRequest, db: sqlite3.Connection = Depends(get_db), _=auth):
        from forgeloop.storage.models import Session, create_session as _create
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        sid = f"web_{now.replace(':', '-').replace('.', '-')}"
        ws = req.workspace or config.workspace_root
        _create(db, Session(id=sid, task=req.task, workspace_root=ws, status="QUEUED", created_at=now, updated_at=now))
        return {"id": sid, "status": "QUEUED", "task": req.task}

    @app.get("/sessions/{sid}")
    async def get_session_endpoint(sid: str, db: sqlite3.Connection = Depends(get_db), _=auth):
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
    async def abort_session_endpoint(sid: str, db: sqlite3.Connection = Depends(get_db), _=auth):
        s = get_session(db, sid)
        if not s:
            raise HTTPException(status_code=404, detail={"error": "session not found"})
        abort_session(db, sid)
        return {"ok": True, "status": "ABORTED"}

    @app.get("/approvals")
    async def list_approvals_endpoint(db: sqlite3.Connection = Depends(get_db), _=auth):
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
    async def approval_decision_endpoint(arid: str, req: ApprovalDecisionRequest, db: sqlite3.Connection = Depends(get_db), _=auth):
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
    async def list_memory_endpoint(keyword: str | None = None, db: sqlite3.Connection = Depends(get_db), _=auth):
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
    async def credentials_endpoint(_=auth):
        st = cred_status("openai")
        return st

    return app


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
