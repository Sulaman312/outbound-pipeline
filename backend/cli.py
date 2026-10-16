"""Command line: three commands. Everything else is done in the app (`outbound serve`).

Commands:
  outbound serve    starts the app at http://127.0.0.1:8000 and opens the browser
  outbound check    config, keys, database, usage against the caps, what's saved
  outbound backup   writes every table to data/backups/<UTC time>.json
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from backend import app, db, icps
from backend.config import ConfigError, Settings, key_status, load_env, load_settings
from backend.db import Connection


def _shown(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def cmd_check(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    month = db.current_month()
    saved = db.count_companies(conn)
    print("config:   ok (config/settings.yaml)")
    print(f"database: {db.describe_database(conn.url, settings.root)}")
    print("keys:")
    for name, is_set in key_status().items():
        print(f"  {name}  {'set' if is_set else 'not set'}")
    print(f"caps this month ({month}):")
    for provider in sorted(settings.caps):
        for unit in sorted(settings.caps[provider]):
            used = db.usage_this_month(conn, provider, unit)
            print(f"  {provider} {unit}  {used} / {settings.caps[provider][unit]}")
    print("ICPs (edit them on the app's ICPs page):")
    all_icps = icps.list_all(conn)
    width = max((len(i.key) for i in all_icps), default=0)
    for icp in all_icps:
        state = "active  " if icp.active else "inactive"
        print(f"  {icp.key.ljust(width)}  {state}  {saved.get(icp.key, 0)} saved")
    print(f"waiting for Clay: {db.count_waiting_for_clay(conn)} companies")
    leads = db.count_leads(conn)
    print(
        "leads: "
        + ", ".join(
            f"{leads.get(s, 0)} {s}" for s in ("verified", "needs_check", "hold", "dropped")
        )
    )
    print(f"do-not-contact: {db.count_suppression(conn)} entries")
    return 0


def cmd_backup(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = settings.root / "data" / "backups" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = db.dump_all_tables(conn)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(len(rows) for rows in payload.values())
    print(f"wrote {total} rows across {len(payload)} tables to {_shown(path, settings.root)}")
    return 0


UI_MISSING = """The app's screens aren't built yet. Build them once (needs Node.js LTS):
  cd ui
  npm install
  npm run build
  cd ..
Then run `outbound serve` again. Starting only the /api routes for now (enough for npm run dev)."""


def cmd_serve(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection | None,
) -> int:
    url = f"http://127.0.0.1:{args.port}"
    if (app.UI_DIST / "index.html").is_file():
        print(f"The app is at {url} (only this computer can open it). Press Ctrl+C to stop.")
        if not args.no_browser:
            threading.Timer(1.5, webbrowser.open, [url]).start()
    else:
        print(UI_MISSING)
    uvicorn.run(
        app.create_app(settings.root), host="127.0.0.1", port=args.port, log_level="warning"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outbound", description="Arsuno outbound pipeline")
    parser.add_argument("--root", default=".", help="project folder (default: the current folder)")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="start the app in your browser (this computer only)")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="don't open the browser")
    serve.set_defaults(func=cmd_serve, needs_db=False)

    check = commands.add_parser("check", help="show config, keys, usage and what's saved")
    check.set_defaults(func=cmd_check)

    backup = commands.add_parser("backup", help="write every table to data/backups/<UTC time>.json")
    backup.set_defaults(func=cmd_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    load_env(root / ".env")
    try:
        settings = load_settings(root)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if not getattr(args, "needs_db", True):  # serve opens one connection per request instead
        return args.func(args, settings, None)
    conn = db.connect(settings.root)
    try:
        return args.func(args, settings, conn)
    finally:
        conn.close()
