from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.0
    base_url: str | None = None


@dataclass
class LLMCallMeta:
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class LLMResponse:
    content: str
    meta: LLMCallMeta


class LLMProvider(Protocol):
    def complete(self, messages: list[Message], config: LLMConfig) -> LLMResponse: ...
