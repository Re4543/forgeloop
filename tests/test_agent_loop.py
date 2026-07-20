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
