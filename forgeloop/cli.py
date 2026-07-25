from __future__ import annotations
import argparse
import getpass
import sys
import threading
from pathlib import Path

from forgeloop.config.app_config import load_app_config
from forgeloop.storage.db import connect, init_schema
from forgeloop.agent.loop import AgentLoop
from forgeloop.agent.session import is_terminal
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
from forgeloop.credentials.store import set_key, get_key, status, clear_key


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="forgeloop")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="start agent loop + WebUI")
    run_p.add_argument("--task", required=True)
    run_p.add_argument("--workspace", default=None)
    run_p.add_argument("--config", default="./forgeloop.yaml")
    run_p.add_argument("--host", default=None)
    run_p.add_argument("--port", type=int, default=None)
    run_p.add_argument("--max-rounds", type=int, default=None)

    serve_p = sub.add_parser("serve", help="start WebUI only (no agent loop)")
    serve_p.add_argument("--workspace", default=None)
    serve_p.add_argument("--config", default="./forgeloop.yaml")
    serve_p.add_argument("--host", default=None)
    serve_p.add_argument("--port", type=int, default=None)

    resume_p = sub.add_parser("resume", help="resume a session with pending approval")
    resume_p.add_argument("session_id")
    resume_p.add_argument("--workspace", default=None)
    resume_p.add_argument("--config", default="./forgeloop.yaml")
    resume_p.add_argument("--host", default=None)
    resume_p.add_argument("--port", type=int, default=None)

    key_p = sub.add_parser("key", help="manage API credentials")
    key_sub = key_p.add_subparsers(dest="key_command", required=True)
    key_sub.add_parser("set", help="store API key (hidden input)")
    key_sub.add_parser("status", help="show key status (masked)")
    key_sub.add_parser("clear", help="remove stored key")

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


def _load_config(args) -> object:
    cli_overrides = {}
    if getattr(args, "workspace", None) is not None:
        cli_overrides["workspace"] = args.workspace
    if getattr(args, "host", None) is not None:
        cli_overrides["host"] = args.host
    if getattr(args, "port", None) is not None:
        cli_overrides["port"] = args.port
    if getattr(args, "max_rounds", None) is not None:
        cli_overrides["max_rounds"] = args.max_rounds
    config_path = Path(getattr(args, "config", "./forgeloop.yaml"))
    return load_app_config(config_path if config_path.exists() else None, cli_overrides)


def _cmd_run(args) -> int:
    config = _load_config(args)
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


def _cmd_serve(args) -> int:
    config = _load_config(args)
    db_path = Path(config.workspace_root) / "forgeloop.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)
    conn.close()

    from forgeloop.server.app import create_app
    from forgeloop.server.sweeper import TimeoutSweeper
    import uvicorn

    app = create_app(config, db_path)
    sweeper = TimeoutSweeper(db_path, config.agent.approval_timeout_seconds, poll_interval=60.0)
    sweeper.start()

    print(f"WebUI: http://{config.server.host}:{config.server.port}")
    print(f"Secret: {config.server.secret}")
    print("Press Ctrl+C to stop.")

    try:
        uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        sweeper.stop()
    return 0


def _cmd_resume(args) -> int:
    config = _load_config(args)
    db_path = Path(config.workspace_root) / "forgeloop.db"
    conn = connect(db_path, wal=True)
    init_schema(conn)

    from forgeloop.storage.models import get_session
    s = get_session(conn, args.session_id)
    if not s:
        print(f"Session {args.session_id} not found")
        conn.close()
        return 1
    if s.status != "PENDING_APPROVAL":
        print(f"Session {args.session_id} status is {s.status}, not PENDING_APPROVAL")
        conn.close()
        return 1

    print(f"Resuming session {args.session_id} (task: {s.task})")
    print(f"Check WebUI to approve/deny pending actions.")

    from forgeloop.server.app import create_app
    from forgeloop.server.sweeper import TimeoutSweeper
    import uvicorn

    app = create_app(config, db_path)
    sweeper = TimeoutSweeper(db_path, config.agent.approval_timeout_seconds, poll_interval=60.0)
    sweeper.start()

    print(f"WebUI: http://{config.server.host}:{config.server.port}")
    print(f"Secret: {config.server.secret}")
    print("Press Ctrl+C to stop.")

    try:
        uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        sweeper.stop()
        conn.close()
    return 0


def _cmd_key(args) -> int:
    provider = "openai"
    if args.key_command == "set":
        key = getpass.getpass("Enter API key: ")
        if not key:
            print("Empty key, aborting.")
            return 1
        set_key(provider, key)
        print(f"Key stored for provider '{provider}'.")
    elif args.key_command == "status":
        st = status(provider)
        if st["configured"]:
            print(f"Provider: {provider}")
            print(f"Status: configured")
            print(f"Last 4 chars: {st['last_four']}")
        else:
            print(f"Provider: {provider}")
            print(f"Status: not configured")
            print(f"Set with: forgeloop key set")
    elif args.key_command == "clear":
        clear_key(provider)
        print(f"Key cleared for provider '{provider}'.")
    return 0


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.command == "run":
        return _cmd_run(args)
    elif args.command == "serve":
        return _cmd_serve(args)
    elif args.command == "resume":
        return _cmd_resume(args)
    elif args.command == "key":
        return _cmd_key(args)
    print(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
