from __future__ import annotations
import os
import time
import httpx
from forgeloop.llm.base import Message, LLMConfig, LLMResponse, LLMCallMeta
from forgeloop.credentials.store import get_key


class RealLLMProvider:
    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        api_key = get_key("openai") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("no api key configured: run `forgeloop credentials set` (Plan 2) or set OPENAI_API_KEY")
        base_url = config.base_url or "https://api.openai.com/v1"
        body = {
            "model": config.model,
            "temperature": config.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        start = time.perf_counter()
        with httpx.Client(timeout=120) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        latency = int((time.perf_counter() - start) * 1000)
        r.raise_for_status()
        data = r.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            meta=LLMCallMeta(
                model=config.model,
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                latency_ms=latency,
            ),
        )
