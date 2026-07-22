from __future__ import annotations
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from forgeloop.llm.base import LLMProvider, LLMConfig, Message
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.tools.base import ToolRegistry
from forgeloop.feedback.classifier import FeedbackClassifier
from forgeloop.feedback.renderer import render
from forgeloop.governance.rule_engine import guardrail
from forgeloop.governance.approval import ApprovalFSM
from forgeloop.parser.parse import parse
from forgeloop.parser.types import Action, ParseError
from forgeloop.agent.context import build_context
from forgeloop.agent.shutdown import check_shutdown, BreakerState
from forgeloop.storage.models import Session, Turn, Action as ActionRow, create_session, create_turn, create_action, update_action, update_session_status
from forgeloop.storage.memory import retrieve_memory


def _now():
    return datetime.now(timezone.utc).isoformat()


def _args_hash(action: Action) -> str:
    return hashlib.sha1(json.dumps({"tool": action.tool, "args": action.args}, sort_keys=True).encode()).hexdigest()[:16]


class AgentLoop:
    def __init__(self, llm: LLMProvider, llm_config: LLMConfig, config: GuardrailsConfig, registry: ToolRegistry, conn: sqlite3.Connection, workspace_root: str, task: str, max_rounds: int = 50, parse_fail_limit: int = 3):
        self._llm = llm
        self._llm_config = llm_config
        self._config = config
        self._registry = registry
        self._conn = conn
        self._workspace_root = workspace_root
        self._task = task
        self._max_rounds = max_rounds
        self._parse_fail_limit = parse_fail_limit
        self._classifier = FeedbackClassifier()
        self._fsm = ApprovalFSM(conn)
        self._history: list[Message] = []
        self._round = 0
        self._consec_fail = 0
        self._consec_ident = 0
        self._last_hash: str | None = None
        self._last_test_state: dict | None = None
        self._last_feedback: str | None = None
        self._last_parse_err: str | None = None
        self._session_id = str(uuid.uuid4())
        self._turn_index = 0

    def run(self) -> str:
        s = Session(id=self._session_id, task=self._task, workspace_root=self._workspace_root, status="RUNNING", created_at=_now(), updated_at=_now(), llm_config=json.dumps({"model": self._llm_config.model}))
        create_session(self._conn, s)
        while True:
            mem = retrieve_memory(self._conn, self._workspace_root, self._task.split()[:3])
            mem_texts = [f"[{m.kind}] {m.content}" for m in mem]
            msgs = build_context(self._task, self._history, mem_texts, self._last_feedback, self._last_parse_err)
            turn_id = str(uuid.uuid4())
            parse_attempts = 0
            action: Action | None = None
            resp = None
            while parse_attempts < self._parse_fail_limit:
                resp = self._llm.complete(msgs, self._llm_config)
                parsed = parse(resp.content)
                if isinstance(parsed, Action):
                    action = parsed
                    break
                parse_attempts += 1
                self._last_parse_err = parsed.message
                msgs = build_context(self._task, self._history, mem_texts, self._last_feedback, self._last_parse_err)
            if action is None:
                create_turn(self._conn, Turn(id=turn_id, session_id=self._session_id, turn_index=self._turn_index, started_at=_now(), finished_at=_now(), parse_status="PARSE_FAILED", parse_attempts=parse_attempts, llm_raw_output=resp.content if resp else ""))
                update_session_status(self._conn, self._session_id, "FAILED_PARSE")
                return "FAILED_PARSE"
            create_turn(self._conn, Turn(id=turn_id, session_id=self._session_id, turn_index=self._turn_index, started_at=_now(), finished_at=_now(), parse_status="OK", parse_attempts=parse_attempts, llm_raw_output=resp.content))
            self._turn_index += 1
            self._history.append(Message(role="assistant", content=resp.content))
            self._last_parse_err = None
            ahash = _args_hash(action)
            action_row = ActionRow(id=str(uuid.uuid4()), session_id=self._session_id, turn_id=turn_id, tool=action.tool, args=json.dumps(action.args), thought=action.thought, args_hash=ahash, status="EXECUTING", created_at=_now())
            create_action(self._conn, action_row)
            decision = guardrail(action, self._config)
            if decision.verdict == "Deny":
                update_action(self._conn, action_row.id, status="BLOCKED_BY_GUARDRAIL", guardrail_decision=json.dumps({"verdict": "Deny", "rule_id": decision.rule_id, "reason": decision.reason}), finished_at=_now())
                self._consec_fail += 1
                self._history.append(Message(role="user", content=f"[BLOCKED] action denied by guardrail: {decision.reason} (rule: {decision.rule_id})"))
                self._last_feedback = None
                self._round += 1
                st = self._check_and_update()
                if st != "RUNNING":
                    return st
                continue
            elif decision.verdict == "RequireApproval":
                update_action(self._conn, action_row.id, status="PENDING_APPROVAL", guardrail_decision=json.dumps({"verdict": "RequireApproval", "rule_id": decision.rule_id, "reason": decision.reason}))
                ar = self._fsm.request(action_id=action_row.id, session_id=self._session_id)
                update_session_status(self._conn, self._session_id, "PENDING_APPROVAL")
                approval_result = self._await_approval(ar.id)
                if approval_result == "denied":
                    update_action(self._conn, action_row.id, status="DENIED", finished_at=_now())
                    self._consec_fail += 1
                    self._history.append(Message(role="user", content="[DENIED] user denied your action."))
                    self._last_feedback = None
                    self._round += 1
                    st = self._check_and_update()
                    if st != "RUNNING":
                        return st
                    continue
                elif approval_result == "timeout":
                    update_action(self._conn, action_row.id, status="TIMEOUT", finished_at=_now())
                    update_session_status(self._conn, self._session_id, "STOPPED_APPROVAL_TIMEOUT", finished_at=_now())
                    return "STOPPED_APPROVAL_TIMEOUT"
                update_action(self._conn, action_row.id, status="APPROVED")
                update_session_status(self._conn, self._session_id, "RUNNING")
                result = self._registry.dispatch(action, ctx={"workspace_root": self._workspace_root, "read_allowlist": self._config.path_fencing.get("read_allowlist", [])})
                self._finish_action(action_row, action, result, ahash)
            else:
                result = self._registry.dispatch(action, ctx={"workspace_root": self._workspace_root, "read_allowlist": self._config.path_fencing.get("read_allowlist", [])})
                self._finish_action(action_row, action, result, ahash)
            self._round += 1
            done_called = action.tool == "done" and result.ok
            done_success = done_called and result.result.get("success", False) if result.result else False
            st = self._check_and_update(done_called=done_called, done_success=done_success)
            if done_called and st == "RUNNING":
                self._history.append(Message(role="user", content="[BLOCKED] done rejected: tests are failing, fix them before calling done"))
            if st != "RUNNING":
                return st

    def _finish_action(self, action_row, action: Action, result, ahash: str) -> None:
        update_action(self._conn, action_row.id, status="SUCCEEDED" if result.ok else "FAILED", result=json.dumps({"ok": result.ok, "result": result.result, "error": result.error, "truncated": result.truncated}), finished_at=_now())
        if result.ok:
            self._consec_fail = 0
        else:
            self._consec_fail += 1
        if ahash == self._last_hash:
            self._consec_ident += 1
        else:
            self._consec_ident = 1
        self._last_hash = ahash
        feedback_text = None
        if result.ok and result.result:
            if action.tool == "run_tests":
                sig = self._classifier.classify("run_tests", "", result.result.get("stdout", ""), result.result.get("exit_code", 0), action_row.id)
                self._last_test_state = {"passed": sig.passed, "failed": sig.stats.get("failed", 0) if sig.stats else 0}
                feedback_text = render(sig)
                update_action(self._conn, action_row.id, feedback_signal=json.dumps({"kind": sig.kind, "passed": sig.passed, "summary": sig.summary}))
            elif action.tool == "run_shell":
                cmd = action.args.get("command", "")
                sig = self._classifier.classify("run_shell", cmd, result.result.get("stdout", ""), result.result.get("exit_code", 0), action_row.id)
                if sig.kind in ("test", "lint"):
                    feedback_text = render(sig)
                    update_action(self._conn, action_row.id, feedback_signal=json.dumps({"kind": sig.kind, "passed": sig.passed, "summary": sig.summary}))
        if feedback_text is None and result.result is not None:
            feedback_text = json.dumps({"ok": result.ok, "result": result.result, "error": result.error, "truncated": result.truncated})
        self._history.append(Message(role="user", content=feedback_text or ""))
        self._last_feedback = feedback_text

    def _check_and_update(self, done_called: bool = False, done_success: bool = False) -> str:
        state = BreakerState(round_count=self._round, consecutive_failures=self._consec_fail, consecutive_identical=self._consec_ident, last_action_hash=self._last_hash, last_test_state=self._last_test_state)
        st = check_shutdown(state, self._config, self._max_rounds, done_called=done_called, done_success=done_success)
        if st != "RUNNING":
            update_session_status(self._conn, self._session_id, st, finished_at=_now() if st.startswith("COMPLETED") else None)
        return st

    def _await_approval(self, ar_id: str, poll_interval: float = 2.0) -> str:
        import time
        while True:
            row = self._conn.execute("SELECT status FROM approval_requests WHERE id=?", (ar_id,)).fetchone()
            if not row:
                return "denied"
            status = row["status"]
            if status == "APPROVED":
                return "approved"
            if status == "DENIED":
                return "denied"
            if status == "TIMEOUT":
                return "timeout"
            time.sleep(poll_interval)
