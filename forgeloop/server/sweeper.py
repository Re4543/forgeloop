from __future__ import annotations
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from forgeloop.storage.db import connect
from forgeloop.storage.models import update_approval_request, update_session_status


class TimeoutSweeper:
    def __init__(self, db_path: Path, approval_timeout_seconds: int, poll_interval: float = 60.0):
        self._db_path = db_path
        self._timeout = approval_timeout_seconds
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._timeout > 0:
                self._sweep()
            self._stop_event.wait(self._poll_interval)

    def _sweep(self) -> None:
        conn = connect(self._db_path, wal=True)
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self._timeout)).isoformat()
            rows = conn.execute(
                "SELECT id, session_id FROM approval_requests WHERE status='PENDING' AND requested_at < ?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                update_approval_request(conn, row["id"], status="TIMEOUT", decided_at=datetime.now(timezone.utc).isoformat())
                update_session_status(conn, row["session_id"], "STOPPED_APPROVAL_TIMEOUT", finished_at=datetime.now(timezone.utc).isoformat())
        finally:
            conn.close()
