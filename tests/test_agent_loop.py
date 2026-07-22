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


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def test_loop_completes_with_done(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=[
        '{"thought":"read","tool":"read_file","args":{"path":"src/main.py"}}',
        '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="read the file then done")
    status = loop.run()
    assert status == "COMPLETED"
    conn.close()


def test_loop_parse_failure_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=["garbage", "more garbage", "still garbage"])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "FAILED_PARSE"
    conn.close()


def test_loop_hard_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=[
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
        '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "STOPPED_FAILURE_BREAKER"
    conn.close()


def test_loop_loop_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=[
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
        '{"thought":"r","tool":"list_dir","args":{"path":"."}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "STOPPED_LOOP"
    conn.close()


def test_loop_guardrail_deny_breaker(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    mock = MockLLMProvider(responses=[
        '{"thought":"x","tool":"run_shell","args":{"command":"rm -rf /"}}',
        '{"thought":"x","tool":"run_shell","args":{"command":"rm -rf /"}}',
        '{"thought":"x","tool":"run_shell","args":{"command":"rm -rf /"}}',
    ])
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "STOPPED_FAILURE_BREAKER"
    rows = conn.execute("SELECT status FROM actions WHERE tool='run_shell'").fetchall()
    assert len(rows) == 3
    assert all(r["status"] == "BLOCKED_BY_GUARDRAIL" for r in rows)
    conn.close()


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


class _HardBreakerResetMock:
    def __init__(self):
        self.count = 0

    def __call__(self, messages, config):
        self.count += 1
        if self.count == 1:
            return '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}'
        if self.count == 2:
            return '{"thought":"r","tool":"read_file","args":{"path":"src/main.py"}}'
        if self.count == 3:
            return '{"thought":"r","tool":"read_file","args":{"path":"missing.py"}}'
        return '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'


def test_hard_breaker_resets_on_success(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=_HardBreakerResetMock())
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x", max_rounds=10)
    status = loop.run()
    assert status != "STOPPED_FAILURE_BREAKER"
    conn.close()


class _ParseRetryMock:
    def __init__(self):
        self.count = 0

    def __call__(self, messages, config):
        self.count += 1
        if self.count == 1:
            return "this is garbage not json"
        if self.count == 2:
            return '{"thought":"list","tool":"list_dir","args":{"path":"."}}'
        return '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'


def test_parse_retry_within_turn(tmp_workspace):
    conn = connect(tmp_workspace / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_workspace)
    cfg.done_post_check["require_green_tests"] = False
    mock = MockLLMProvider(responses=_ParseRetryMock())
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_workspace), task="x")
    status = loop.run()
    assert status == "COMPLETED"
    conn.close()
