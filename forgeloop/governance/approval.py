from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from forgeloop.storage.models import ApprovalRequest, create_approval_request, update_approval_request, list_pending_approvals


def _now():
    return datetime.now(timezone.utc).isoformat()


class ApprovalFSM:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def request(self, action_id: str, session_id: str) -> ApprovalRequest:
        ar = ApprovalRequest(id=str(uuid.uuid4()), action_id=action_id, session_id=session_id, status="PENDING", requested_at=_now())
        create_approval_request(self._conn, ar)
        return ar

    def approve(self, ar_id: str, decided_by: str = "webui") -> None:
        update_approval_request(self._conn, ar_id, status="APPROVED", decided_at=_now(), decided_by=decided_by)

    def deny(self, ar_id: str, decided_by: str = "webui", reason: str = "") -> None:
        update_approval_request(self._conn, ar_id, status="DENIED", decided_at=_now(), decided_by=decided_by, deny_reason=reason)

    def pending(self) -> list[ApprovalRequest]:
        return list_pending_approvals(self._conn)
