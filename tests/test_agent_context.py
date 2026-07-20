from forgeloop.agent.context import build_context
from forgeloop.llm.base import Message


def test_context_has_system_user_memory_feedback():
    msgs = build_context(task="add a foo function", history=[], memory_entries=["convention: use 4 spaces"], feedback_text=None, parse_error_text=None)
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "add a foo function" in msgs[1].content
    assert any("[MEMORY]" in m.content for m in msgs)


def test_context_includes_feedback():
    msgs = build_context(task="x", history=[], memory_entries=[], feedback_text="[FEEDBACK] FAILED", parse_error_text=None)
    assert any("[FEEDBACK]" in m.content for m in msgs)


def test_context_includes_parse_error():
    msgs = build_context(task="x", history=[], memory_entries=[], feedback_text=None, parse_error_text="missing field thought")
    assert any("无法解析" in m.content for m in msgs)


def test_history_truncation():
    hist = [Message(role="assistant", content=f'{{"thought":"t{i}","tool":"done","args":{{}}}}') for i in range(30)]
    msgs = build_context(task="x", history=hist, memory_entries=[], feedback_text=None, parse_error_text=None, max_history_turns=20)
    assistant_count = sum(1 for m in msgs if m.role == "assistant")
    assert assistant_count <= 20
