# tests/test_e2e_approval_flow.py
import json
import threading
import time
from pathlib import Path
from fastapi.testclient import TestClient
from forgeloop.config.app_config import AppConfig, ServerConfig, AgentConfig
from forgeloop.config.loader import GuardrailsConfig, load_config
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
    conn = connect(db_path, wal=True, check_same_thread=False)
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
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
    conn = connect(db_path, wal=True, check_same_thread=False)
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
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
