"""Command line entry point for local server administration."""

from __future__ import annotations

import argparse
import getpass
import json
from typing import Any

from server.app import create_app
from server.config import ServerSettings
from server.store import AdminNotFoundError, BootstrapAlreadyCompletedError, ServerStore


def _settings() -> ServerSettings:
    return ServerSettings.from_env()


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def init_command(args: argparse.Namespace) -> None:
    settings = _settings()
    store = ServerStore(settings)
    store.initialize()
    created_admin = None
    if args.admin:
        password = args.password or getpass.getpass("Admin password: ")
        try:
            created_admin = store.create_initial_admin(args.admin, password)
        except BootstrapAlreadyCompletedError:
            created_admin = {"skipped": True, "reason": "Administrator already exists"}
    _print_json(
        {
            "database": str(settings.database_path),
            "initialized": True,
            "admin": created_admin,
        }
    )


def check_command(_args: argparse.Namespace) -> None:
    settings = _settings()
    store = ServerStore(settings)
    store.initialize()
    _print_json({"checks": store.system_checks()})


def diagnose_command(args: argparse.Namespace) -> None:
    settings = _settings()
    store = ServerStore(settings)
    store.initialize()
    payload = {
        "settings": {
            "host": settings.host,
            "port": settings.port,
            "data_dir": str(settings.data_dir),
            "database_path": str(settings.database_path),
            "credential_path": str(settings.credential_path),
            "public_base_url": settings.public_base_url,
        },
        "runtime_config": store.get_config_map(),
        "checks": store.system_checks(),
    }
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        _print_json(payload)


def reset_admin_command(args: argparse.Namespace) -> None:
    settings = _settings()
    store = ServerStore(settings)
    store.initialize()
    if not store.has_admin():
        raise SystemExit("No administrator configured; use `init --admin` first.")

    password = args.password
    if password:
        confirm = password
    else:
        password = getpass.getpass("New admin password: ")
        confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters")

    try:
        result = store.reset_admin_password(password, username=args.username)
    except AdminNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    store.add_audit(
        "admin.password.reset",
        "success",
        actor_type="cli",
        actor_id=result["id"],
        metadata={"username": result["username"]},
    )
    _print_json({"reset": True, "admin": result})


def run_command(args: argparse.Namespace) -> None:
    import os

    import uvicorn

    settings = _settings()
    app = create_app(settings)

    # 默认关闭 uvicorn access log：前端每 500ms 轮询同步进度会淹没控制台，
    # 且这类日志在 stdio 上是同步阻塞的，Windows 下会明显吃 CPU。
    # 通过环境变量 MIJIA_SERVER_ACCESS_LOG=1 或 --access-log 显式开启。
    env_access_log = os.environ.get("MIJIA_SERVER_ACCESS_LOG", "").lower()
    access_log = getattr(args, "access_log", False) or env_access_log in {
        "1",
        "true",
        "yes",
        "on",
    }
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        access_log=access_log,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mijia-server")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="initialize SQLite storage")
    init_parser.add_argument("--admin", help="create the initial administrator")
    init_parser.add_argument("--password", help="administrator password")
    init_parser.set_defaults(func=init_command)

    run_parser = subparsers.add_parser("run", help="run the API server")
    run_parser.add_argument(
        "--access-log",
        action="store_true",
        help="启用 uvicorn access log（默认关闭以避免高频轮询淹没控制台）",
    )
    run_parser.set_defaults(func=run_command)

    check_parser = subparsers.add_parser("check", help="run system checks")
    check_parser.set_defaults(func=check_command)

    diagnose_parser = subparsers.add_parser("diagnose", help="export diagnostic data")
    diagnose_parser.add_argument("--output", type=lambda value: __import__("pathlib").Path(value))
    diagnose_parser.set_defaults(func=diagnose_command)

    reset_parser = subparsers.add_parser("reset-admin", help="reset administrator password")
    reset_parser.add_argument("--username", help="administrator username (default: first admin)")
    reset_parser.add_argument("--password", help="new administrator password")
    reset_parser.set_defaults(func=reset_admin_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    
    # 如果没有提供子命令，默认执行 run
    if args.command is None:
        run_command(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
