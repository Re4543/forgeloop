"""
ForgeLoop 机制演示脚本 — mock LLM 下确定性复现三场景

场景 1: 护栏拦截危险动作
  mock 依次产出 run_shell("rm -rf /") 与越界写入，断言 Deny/拦截、动作未执行、事件已记录

场景 2: 注入失败后反馈回灌改变下一步动作
  第 1 轮产出致测试失败的 write_file，校验器解析失败并回灌，
  断言第 2 轮上下文含该失败信息、修复后转绿并正常停机

场景 3: HITL 状态机确定性流转
  RequireApproval 动作进 PENDING，批准则执行、拒绝则丢弃且循环收到拒绝反馈

运行: py -3.13 demo/mechanism_demo.py
零网络、每次结果一致。
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from forgeloop.agent.loop import AgentLoop
from forgeloop.agent.session import is_terminal
from forgeloop.config.loader import load_config
from forgeloop.credentials.redact import redact
from forgeloop.governance.approval import ApprovalFSM
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.storage.db import connect, init_schema
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.done import DoneTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.write_file import WriteFileTool


def _registry():
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def _make_workspace(tmpdir: str) -> str:
    ws = os.path.join(tmpdir, "workspace")
    os.makedirs(os.path.join(ws, "src"), exist_ok=True)
    with open(os.path.join(ws, "src", "main.py"), "w") as f:
        f.write("print('hi')\n")
    return ws


def _make_loop(tmpdir: str, responses, max_rounds=20, auto_approve_writes=False):
    ws = _make_workspace(tmpdir)
    db_path = Path(ws) / "forgeloop.db"
    conn = connect(db_path, wal=True, check_same_thread=False)
    init_schema(conn)
    cfg = load_config([])
    cfg.workspace_root = ws
    cfg.done_post_check["require_green_tests"] = False
    if auto_approve_writes:
        for rule in cfg.rules:
            if rule["id"] in ("approve_all_writes", "approve_shell_default"):
                rule["decision"] = "Allow"
    mock = MockLLMProvider(responses=responses)
    loop = AgentLoop(
        llm=mock, llm_config=LLMConfig(model="mock"), config=cfg,
        registry=_registry(), conn=conn, workspace_root=ws,
        task="demo", max_rounds=max_rounds,
    )
    return loop, conn, ws


def scenario_1_guardrail():
    print("=" * 60)
    print("场景 1: 护栏拦截危险动作")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        responses = [
            json.dumps({"thought": "delete root", "tool": "run_shell", "args": {"command": "rm -rf /"}}),
            json.dumps({"thought": "write outside", "tool": "write_file", "args": {"path": "../../etc/passwd", "mode": "overwrite", "content": "hacked"}}),
            json.dumps({"thought": "done", "tool": "done", "args": {"summary": "demo", "success": True}}),
        ]
        loop, conn, ws = _make_loop(tmpdir, responses, auto_approve_writes=True)
        status = loop.run()

        actions = conn.execute("SELECT tool, status, guardrail_decision FROM actions ORDER BY created_at").fetchall()

        print(f"  最终状态: {status}")
        print(f"  动作记录:")
        for a in actions:
            print(f"    {a['tool']:15s} status={a['status']:25s} decision={a['guardrail_decision']}")

        assert status == "COMPLETED", f"预期 COMPLETED, 实际 {status}"
        assert actions[0]["status"] == "BLOCKED_BY_GUARDRAIL", "rm -rf / 应被拦截"
        assert actions[1]["status"] == "BLOCKED_BY_GUARDRAIL", "越界写入应被拦截"
        assert not Path("../../etc/passwd").exists(), "越界文件不应被创建"
        print("  ✓ 危险动作被拦截，未执行，事件已记录")
        conn.close()

    print()


def scenario_2_feedback_loop():
    print("=" * 60)
    print("场景 2: 注入失败后反馈回灌改变下一步动作")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        responses = [
            json.dumps({"thought": "write failing test", "tool": "write_file", "args": {"path": "tests/test_demo.py", "mode": "overwrite", "content": "def test_fail():\n    assert False\n"}}),
            json.dumps({"thought": "run tests", "tool": "run_tests", "args": {"target": "tests"}}),
            json.dumps({"thought": "fix the test", "tool": "write_file", "args": {"path": "tests/test_demo.py", "mode": "overwrite", "content": "def test_pass():\n    assert True\n"}}),
            json.dumps({"thought": "run tests again", "tool": "run_tests", "args": {"target": "tests"}}),
            json.dumps({"thought": "done", "tool": "done", "args": {"summary": "fixed", "success": True}}),
        ]
        loop, conn, ws = _make_loop(tmpdir, responses, auto_approve_writes=True)
        status = loop.run()

        actions = conn.execute("SELECT tool, status, feedback_signal FROM actions ORDER BY created_at").fetchall()

        print(f"  最终状态: {status}")
        print(f"  动作记录:")
        for a in actions:
            fb = json.loads(a["feedback_signal"]) if a["feedback_signal"] else None
            print(f"    {a['tool']:15s} status={a['status']:12s} feedback={'有' if fb else '无'}")

        assert status == "COMPLETED", f"预期 COMPLETED, 实际 {status}"

        test_action = actions[1]
        assert test_action["tool"] == "run_tests", "第 2 个动作应为 run_tests"
        assert test_action["status"] == "SUCCEEDED", "run_tests 工具本身成功（退出码非零但工具执行成功）"
        fb = json.loads(test_action["feedback_signal"])
        assert fb["passed"] == False, "第 1 次 run_tests 应检测到失败"
        print(f"  ✓ 第 1 次 run_tests 检测到失败: {fb['summary']}")

        fix_action = actions[2]
        assert fix_action["tool"] == "write_file", "第 3 个动作应为 write_file（修复）"
        assert fix_action["status"] == "SUCCEEDED", "修复写入应成功"
        print("  ✓ 反馈回灌后 agent 修复了测试")

        retest_action = actions[3]
        assert retest_action["tool"] == "run_tests", "第 4 个动作应为 run_tests（重跑）"
        fb2 = json.loads(retest_action["feedback_signal"])
        assert fb2["passed"] == True, "第 2 次 run_tests 应通过"
        print(f"  ✓ 修复后测试转绿: {fb2['summary']}")

        history_has_feedback = any("failed" in m.content.lower() or "FAIL" in m.content for m in loop._history if m.role == "user")
        assert history_has_feedback, "历史中应包含失败反馈"
        print("  ✓ 失败反馈已注入上下文历史")
        conn.close()

    print()


def scenario_3_hitl_state_machine():
    print("=" * 60)
    print("场景 3: HITL 状态机确定性流转")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        responses = [
            json.dumps({"thought": "write file 1", "tool": "write_file", "args": {"path": "src/new1.py", "mode": "overwrite", "content": "x = 1\n"}}),
            json.dumps({"thought": "write file 2", "tool": "write_file", "args": {"path": "src/new2.py", "mode": "overwrite", "content": "y = 2\n"}}),
            json.dumps({"thought": "done", "tool": "done", "args": {"summary": "demo", "success": True}}),
        ]
        loop, conn, ws = _make_loop(tmpdir, responses)
        db_path = Path(ws) / "forgeloop.db"
        status = [None]

        def _run():
            status[0] = loop.run()

        t = threading.Thread(target=_run)
        t.start()

        decisions = []
        for _ in range(600):
            if status[0] is not None:
                break
            approver_conn = connect(db_path, wal=True)
            try:
                row = approver_conn.execute("SELECT id FROM approval_requests WHERE status='PENDING'").fetchone()
                if row:
                    ar_id = row["id"]
                    if len(decisions) == 0:
                        ApprovalFSM(approver_conn).approve(ar_id)
                        decisions.append(("approve", ar_id))
                        print(f"  批准第 1 个审批: {ar_id[:8]}...")
                    elif len(decisions) == 1:
                        ApprovalFSM(approver_conn).deny(ar_id, reason="second file not needed")
                        decisions.append(("deny", ar_id))
                        print(f"  拒绝第 2 个审批: {ar_id[:8]}... (reason: not needed)")
            finally:
                approver_conn.close()
            time.sleep(0.1)

        t.join(timeout=30)

        actions = conn.execute("SELECT tool, status FROM actions ORDER BY created_at").fetchall()
        approvals = conn.execute("SELECT status, deny_reason FROM approval_requests ORDER BY requested_at").fetchall()

        print(f"  最终状态: {status[0]}")
        print(f"  动作记录:")
        for a in actions:
            print(f"    {a['tool']:15s} status={a['status']}")
        print(f"  审批记录:")
        for ar in approvals:
            print(f"    status={ar['status']:12s} reason={ar['deny_reason'] or '-'}")

        assert status[0] == "COMPLETED", f"预期 COMPLETED, 实际 {status[0]}"
        assert len(approvals) == 2, "应有 2 个审批请求"
        assert approvals[0]["status"] == "APPROVED", "第 1 个审批应被批准"
        assert approvals[1]["status"] == "DENIED", "第 2 个审批应被拒绝"

        write_actions = [a for a in actions if a["tool"] == "write_file"]
        assert write_actions[0]["status"] == "SUCCEEDED", "被批准的写入应执行"
        assert write_actions[1]["status"] == "DENIED", "被拒绝的写入应标记为 DENIED"

        assert Path(ws, "src", "new1.py").exists(), "被批准的文件应存在"
        assert not Path(ws, "src", "new2.py").exists(), "被拒绝的文件不应存在"

        history_has_denied = any("DENIED" in m.content for m in loop._history if m.role == "user")
        assert history_has_denied, "拒绝反馈应注入上下文"
        print("  ✓ 批准路径: 动作执行，文件创建")
        print("  ✓ 拒绝路径: 动作丢弃，反馈注入，文件未创建")
        print("  ✓ 状态机全路径断言通过")
        conn.close()

    print()


def main():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       ForgeLoop 机制演示 — mock LLM, 零网络            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    scenario_1_guardrail()
    scenario_2_feedback_loop()
    scenario_3_hitl_state_machine()

    print("=" * 60)
    print("全部三场景通过 ✓")
    print("=" * 60)
    print()
    print("场景 1: 护栏拦截 rm -rf / 和越界写入 → Deny, 未执行, 已记录")
    print("场景 2: 写入失败测试 → 反馈回灌 → 修复 → 测试转绿 → COMPLETED")
    print("场景 3: RequireApproval → 批准执行 / 拒绝丢弃 → COMPLETED")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
