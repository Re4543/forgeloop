from __future__ import annotations
from time import perf_counter_ns
from forgeloop.llm.base import Message, LLMConfig, LLMResponse, LLMCallMeta


class MockLLMProvider:
    def __init__(self, responses):
        if callable(responses):
            self._gen = responses
            self._seq = None
        else:
            self._gen = None
            self._seq = iter(responses)

    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        start = perf_counter_ns()
        if self._gen is not None:
            content = self._gen(messages, config)
        else:
            content = next(self._seq)
        latency = (perf_counter_ns() - start) // 1_000_000
        return LLMResponse(
            content=content,
            meta=LLMCallMeta(model=config.model, prompt_tokens=0, completion_tokens=0, latency_ms=latency),
        )
