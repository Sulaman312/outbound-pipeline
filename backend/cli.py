"""Command line: parses arguments, calls the step functions, prints what they return.

Commands:
  outbound check                         config, keys, budget, what's saved
  outbound icps                          the ICPs (who we target); edit them in the app
  outbound source ICP [--pages N]        dry run: shows the Apollo request and its cost
  outbound source ICP --live             runs it for real (spends Apollo credits)
  outbound export [--icp ICP]            writes saved companies to a CSV file
  outbound export --contacts             writes the people Clay found to a CSV file
  outbound clay export ICP [--rows N]    writes one ICP's next companies to a CSV for Clay
  outbound clay import FILE              reads the CSV you downloaded from Clay
  outbound suppress VALUE --reason TEXT  adds a domain or email to the do-not-contact list
  outbound fields [--icp ICP]            which fields Apollo sent (names and counts, no values)
  outbound backup                        writes every table to data/backups/<UTC time>.json
  outbound serve                         starts the app at http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from backend import app, db, exports, fields, icps, suppression
from backend.config import ConfigError, Settings, key_status, load_env, load_settings
from backend.db import Connection
from backend.http import new_client
from backend.icps import Icp
from backend.sources import BY_KEY, SOURCES
from backend.stages import enrich, source


def _shown(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _icp(conn: Connection, key: str) -> Icp | None:
    """The ICP called `key`, or None after printing which ones exist."""
    icp = icps.get(conn, key)
    if icp is None:
        names = ", ".join(i.key for i in icps.list_all(conn) if i.active)
        print(f"error: no ICP called {key!r}. Active ICPs: {names or 'none'}", file=sys.stderr)
    return icp


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


def cmd_source(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    icp = _icp(conn, args.icp)
    if icp is None:
        return 2
    problem = source.pages_problem(args.pages)
    if problem:
        print(f"error: --{problem}", file=sys.stderr)
        return 2
    problem = source.icp_problem(icp, args.source)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    cap = source.cap_for(settings.caps, args.source)
    label = BY_KEY[args.source].label

    if not args.live:
        print(f"DRY RUN: nothing is sent to {label}. Add --live to run it for real.\n")
        print(source.describe(conn, icp, args.source, pages=args.pages, cap=cap))
        return 0

    api_key = os.environ.get(BY_KEY[args.source].key_env, "").strip()
    problem = source.live_problem(args.source, api_key, cap)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    assert cap is not None

    with new_client() as client:
        result = source.run_live(
            conn, icp, args.source, client=client, api_key=api_key, cap=cap, pages=args.pages
        )
    used = db.usage_this_month(conn, args.source, BY_KEY[args.source].cap_unit)
    print(source.summarize(result, used=used, cap=cap))
    return 1 if result.error else 0


def cmd_export(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    if args.icp and _icp(conn, args.icp) is None:
        return 2
    kind = "contacts" if args.contacts else "companies"
    path = Path(args.out).resolve() if args.out else exports.default_path(settings.root, kind)
    if args.contacts:
        count = exports.export_leads(conn, path)
    else:
        count = exports.export_companies(conn, path, args.icp)
    print(f"wrote {count} {kind} to {_shown(path, settings.root)}")
    return 0


def cmd_clay_export(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    if _icp(conn, args.icp) is None:
        return 2
    if args.rows < 1:
        print("error: --rows must be at least 1", file=sys.stderr)
        return 2
    result = enrich.export_batch(conn, settings.root, args.icp, args.rows)
    if result is None:
        print(f"Nothing from {args.icp} is waiting for Clay. Find more companies first.")
        return 0
    print(
        f"wrote {result.rows} companies to {_shown(result.path, settings.root)} (batch {result.batch_id})"
    )
    print("Next: upload it to a Clay table. The steps are in docs/clay-table.md.")
    return 0


def cmd_clay_import(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: no file at {path}", file=sys.stderr)
        return 2
    headers, rows = enrich.read_csv(path.read_text(encoding="utf-8-sig", errors="replace"))
    mapping = enrich.detect_columns(headers)
    missing = enrich.missing_fields(mapping)
    if missing:
        print(f"error: can't tell which column is: {', '.join(missing)}", file=sys.stderr)
        print(f"columns in the file: {', '.join(headers)}", file=sys.stderr)
        print(
            "Rename that column in Clay so the names match docs/clay-table.md.",
            file=sys.stderr,
        )
        return 2
    print("columns used: " + ", ".join(f"{name}={col}" for name, col in mapping.items() if col))
    result = enrich.import_rows(conn, rows, mapping, account=args.account, credits=args.credits)
    print(enrich.describe_import(conn, result, args.credits))
    return 0


def cmd_suppress(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    try:
        value, kind, added = suppression.suppress(conn, args.value, args.reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{'added' if added else 'already on the list'}: {kind} {value}")
    return 0


def cmd_icps(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    for icp in icps.summaries(conn):
        state = "active" if icp["active"] else "inactive"
        sources = ", ".join(sorted(icp["sources"])) or "no source settings"
        print(f"{icp['key']}  ({state}; {sources})")
        print(f"  {icp['name']}")
        print(f"  {icp['saved']} companies saved, {icp['waiting_for_clay']} waiting for Clay")
    print("Create and edit ICPs on the app's ICPs page (outbound serve).")
    return 0


def cmd_fields(
    args: argparse.Namespace,
    settings: Settings,
    conn: Connection,
) -> int:
    total, counts = fields.field_counts(conn, args.icp)
    print(fields.describe(total, counts))
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

    check = commands.add_parser("check", help="show config, keys, budget and what's saved")
    check.set_defaults(func=cmd_check)

    icps_cmd = commands.add_parser("icps", help="list the ICPs (who we target)")
    icps_cmd.set_defaults(func=cmd_icps)

    src = commands.add_parser("source", help="find companies for an ICP (dry run unless --live)")
    src.add_argument("icp", help="an ICP key, like dev_us_pain (see `outbound icps`)")
    src.add_argument(
        "--source",
        default="apollo",
        choices=[s.key for s in SOURCES],
        help="where to look (default apollo)",
    )
    src.add_argument(
        "--pages", type=int, default=1, help="pages of 100 companies to fetch (default 1)"
    )
    src.add_argument("--live", action="store_true", help="really call the source and spend credits")
    src.set_defaults(func=cmd_source)

    exp = commands.add_parser("export", help="write saved companies to a CSV file")
    exp.add_argument("--icp", help="only this ICP")
    exp.add_argument("--contacts", action="store_true", help="the people Clay found, not companies")
    exp.add_argument("--out", help="file to write (default: data/exports/<kind>_<time>.csv)")
    exp.set_defaults(func=cmd_export)

    clay_cmd = commands.add_parser(
        "clay", help="send companies to Clay, and read Clay's results back"
    )
    clay_steps = clay_cmd.add_subparsers(dest="clay_command", required=True)
    clay_out = clay_steps.add_parser(
        "export", help="write one ICP's next companies to a CSV for Clay"
    )
    clay_out.add_argument("icp", help="the ICP whose companies go into this file")
    clay_out.add_argument(
        "--rows",
        type=int,
        default=enrich.DEFAULT_ROWS,
        help=f"companies per file (default {enrich.DEFAULT_ROWS}, Clay Free's limit; use 50 on a trial)",
    )
    clay_out.set_defaults(func=cmd_clay_export)
    clay_in = clay_steps.add_parser("import", help="read the CSV you downloaded from Clay")
    clay_in.add_argument("file", help="the CSV file Clay gave you")
    clay_in.add_argument("--account", help="which Clay login ran it, to compare accounts later")
    clay_in.add_argument("--credits", type=float, help="Clay credits this batch used")
    clay_in.set_defaults(func=cmd_clay_import)

    sup = commands.add_parser("suppress", help="add a domain or email to the do-not-contact list")
    sup.add_argument("value", help="a domain like acme.com, or an email")
    sup.add_argument("--reason", required=True, help='why, like "existing client"')
    sup.set_defaults(func=cmd_suppress)

    fld = commands.add_parser("fields", help="which fields Apollo sent (names and counts only)")
    fld.add_argument("--icp", help="only this ICP")
    fld.set_defaults(func=cmd_fields)

    backup = commands.add_parser("backup", help="write every table to data/backups/<UTC time>.json")
    backup.set_defaults(func=cmd_backup)

    serve = commands.add_parser("serve", help="start the app in your browser (this computer only)")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="don't open the browser")
    serve.set_defaults(func=cmd_serve, needs_db=False)
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
