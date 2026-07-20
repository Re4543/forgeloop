from forgeloop.agent.loop import AgentLoop
from forgeloop.llm.base import LLMConfig, Message
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


def test_feedback_injected_after_failed_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert 1 == 2\n", encoding="utf-8")
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = str(tmp_path)
    cfg.done_post_check["require_green_tests"] = False
    captured_contexts: list[list[Message]] = []

    def gen(messages, config):
        captured_contexts.append(list(messages))
        if len(captured_contexts) == 1:
            return '{"thought":"run tests","tool":"run_tests","args":{"target":"tests"}}'
        return '{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'

    mock = MockLLMProvider(responses=gen)
    loop = AgentLoop(llm=mock, llm_config=LLMConfig(model="mock"), config=cfg, registry=_registry(), conn=conn, workspace_root=str(tmp_path), task="run tests then done")
    status = loop.run()
    assert status == "COMPLETED"
    assert len(captured_contexts) >= 2
    second_context_text = " ".join(m.content for m in captured_contexts[1])
    assert "[FEEDBACK]" in second_context_text
    assert "FAILED" in second_context_text or "assertion_failure" in second_context_text
    conn.close()
