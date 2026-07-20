from forgeloop.llm.base import Message, LLMConfig
from forgeloop.llm.mock import MockLLMProvider


def test_mock_returns_sequence():
    provider = MockLLMProvider(responses=['{"thought":"x","tool":"done","args":{}}'])
    resp = provider.complete([Message(role="user", content="hi")], LLMConfig(model="mock"))
    assert resp.content == '{"thought":"x","tool":"done","args":{}}'
    assert resp.meta.model == "mock"


def test_mock_callable_branching():
    def gen(messages, config):
        return f"echo:{messages[-1].content}"
    provider = MockLLMProvider(responses=gen)
    resp = provider.complete([Message(role="user", content="ping")], LLMConfig(model="mock"))
    assert resp.content == "echo:ping"


def test_mock_exhausts_sequence_raises():
    import pytest
    provider = MockLLMProvider(responses=["only-one"])
    provider.complete([Message(role="user", content="x")], LLMConfig(model="mock"))
    with pytest.raises(StopIteration):
        provider.complete([Message(role="user", content="x")], LLMConfig(model="mock"))
