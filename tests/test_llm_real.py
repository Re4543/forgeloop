import pytest
from unittest.mock import MagicMock
from forgeloop.llm.base import Message, LLMConfig
from forgeloop.llm.real import RealLLMProvider


def test_real_uses_key_from_get_key(monkeypatch):
    monkeypatch.setattr("forgeloop.llm.real.get_key", lambda p: "sk-test-key")
    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        def raise_for_status(self):
            pass

    def fake_post(url, headers, json):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        captured["body"] = json
        return FakeResp()

    fake_client = MagicMock()
    fake_client.post = fake_post
    fake_client.__enter__ = lambda self: self
    fake_client.__exit__ = lambda self, *a: None
    monkeypatch.setattr("forgeloop.llm.real.httpx.Client", lambda **kw: fake_client)

    provider = RealLLMProvider()
    resp = provider.complete([Message(role="user", content="hi")], LLMConfig(model="gpt-4o"))
    assert resp.content == "hello"
    assert resp.meta.prompt_tokens == 5
    assert captured["auth"] == "Bearer sk-test-key"
    assert "api_key" not in str(captured["body"])


def test_real_raises_when_no_key(monkeypatch):
    monkeypatch.setattr("forgeloop.llm.real.get_key", lambda p: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = RealLLMProvider()
    with pytest.raises(RuntimeError, match="no api key"):
        provider.complete([Message(role="user", content="x")], LLMConfig(model="gpt-4o"))
