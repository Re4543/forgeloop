from __future__ import annotations
from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    task: str
    workspace: str | None = None


class ApprovalDecisionRequest(BaseModel):
    verdict: str
    reason: str | None = None
