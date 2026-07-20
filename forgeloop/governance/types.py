from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["Allow", "Deny", "RequireApproval"]


@dataclass
class Decision:
    verdict: Verdict
    rule_id: str
    reason: str = ""
