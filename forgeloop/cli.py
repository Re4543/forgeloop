from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from pathlib import Path

from forgeloop.config.app_config import load_app_config
from forgeloop.storage.db import connect, init_schema
from forgeloop.agent.loop import AgentLoop
from forgeloop.agent.session import is_terminal
from forgeloop.config.loader import GuardrailsConfig
from forgeloop.llm.base import LLMConfig
from forgeloop.llm.real import RealLLMProvider
from forgeloop.llm.mock import MockLLMProvider
from forgeloop.tools.base import ToolRegistry
from forgeloop.tools.read_file import ReadFileTool
from forgeloop.tools.write_file import WriteFileTool
from forgeloop.tools.run_shell import RunShellTool
from forgeloop.tools.run_tests import RunTestsTool
from forgeloop.tools.list_dir import ListDirTool
from forgeloop.tools.done import DoneTool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="forgeloop")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--task", required=True)
    run_p.add_argument("--workspace", default=None)
    run_p.add_argument("--config", default="./forgeloop.yaml")
    run_p.add_argument("--host", default=None)
    run_p.add_argument("--port", type=int, default=None)
    run_p.add_argument("--max-rounds", type=int, default=None)
    return parser.parse_args(argv)


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), RunShellTool(), RunTestsTool(), ListDirTool(), DoneTool()]:
        reg.register(t)
    return reg


def _scan_pending_approvals(conn) -> None:
    rows = conn.execute(
        "SELECT id FROM sessions WHERE status='PENDING_APPROVAL'"
    ).fetchall()
    for row in rows:
        print(f"WARNING: Session {row['id']} has pending approval, check WebUI")


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.command != "run":
        print(f"Unknown command: {args.command}")
        return 1

    cli_overrides = {}
    if args.workspace is not None:
        cli_overrides["workspace"] = args.workspace
    if args.host is not None:
        cli_overrides["host"] = args.host
    if args.port is not None:
        cli_overrides["port"] = args.port
    if args.max_rounds is not None:
        cli_overrides["max_rounds"] = args.max_rounds

    config_path = Path(args.config)
    config = load_app_config(config_path if config_path.exists() else None, cli_overrides)

    db_path = Path(config.workspace_root) / "forgeloop.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)

    _scan_pending_approvals(conn)

    from forgeloop.server.app import create_app
    from forgeloop.server.sweeper import TimeoutSweeper
    import uvicorn

    app = create_app(config, db_path)
    server = uvicorn.Server(uvicorn.Config(app, host=config.server.host, port=config.server.port, log_level="warning"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    sweeper = TimeoutSweeper(db_path, config.agent.approval_timeout_seconds, poll_interval=60.0)
    sweeper.start()

    print(f"WebUI: http://{config.server.host}:{config.server.port}")
    print(f"Secret: {config.server.secret}")

    if config.llm.model == "mock":
        llm = MockLLMProvider(responses=['{"thought":"done","tool":"done","args":{"summary":"ok","success":true}}'])
    else:
        llm = RealLLMProvider()

    registry = _build_registry()
    loop = AgentLoop(
        llm=llm,
        llm_config=config.llm,
        config=config.guardrails,
        registry=registry,
        conn=conn,
        workspace_root=config.workspace_root,
        task=args.task,
        max_rounds=config.agent.max_rounds,
        parse_fail_limit=config.agent.parse_fail_limit,
    )

    status = loop.run()
    print(f"Final status: {status}")

    sweeper.stop()
    server.should_exit = True
    conn.close()
    return 0 if is_terminal(status) else 1


if __name__ == "__main__":
    sys.exit(main())
