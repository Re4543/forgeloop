from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Failure:
    id: str
    file: str | None = None
    line: int | None = None
    col: int | None = None
    type: str | None = None
    message: str | None = None
    classification: str = "other"
    code: str | None = None


@dataclass
class FeedbackSignal:
    kind: str
    source_tool: str
    source_action_id: str
    passed: bool
    summary: str
    failures: list[Failure] = field(default_factory=list)
    stats: dict | None = None
    raw_excerpt: str = ""
