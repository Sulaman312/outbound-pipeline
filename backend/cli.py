"""Command line: parses arguments, calls the step functions, prints what they return.

Commands:
  outbound check                         config, keys, budget, what's saved
  outbound source SEGMENT [--pages N]    dry run: shows the Apollo request and its cost
  outbound source SEGMENT --live         runs it for real (spends Apollo credits)
  outbound export [--segment S]          writes saved companies to a CSV file
  outbound export --contacts             writes the people Clay found to a CSV file
  outbound clay export [--rows N]        writes the next companies to a CSV to upload to Clay
  outbound clay import FILE              reads the CSV you downloaded from Clay
  outbound suppress VALUE --reason TEXT  adds a domain or email to the do-not-contact list
  outbound fields [--segment S]          which fields Apollo sent (names and counts, no values)
  outbound backup                        writes every table to data/backups/<UTC time>.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend import db, exports, fields, suppression
from backend.config import (
    ConfigError,
    Segment,
    Settings,
    key_status,
    load_env,
    load_segments,
    load_settings,
)
from backend.db import Connection
from backend.http import new_client
from backend.stages import enrich, source

MAX_PAGES_PER_RUN = 50


def _shown(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _apollo_cap(settings: Settings) -> int | None:
    return settings.caps.get("apollo", {}).get("credits")


def cmd_check(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    month = db.current_month()
    saved = db.count_companies(conn)
    print("config:   ok (config/settings.yaml, config/segments.yaml)")
    print(f"database: {db.describe_database(conn.url, settings.root)}")
    print("keys:")
    for name, is_set in key_status().items():
        print(f"  {name}  {'set' if is_set else 'not set'}")
    print(f"caps this month ({month}):")
    for provider in sorted(settings.caps):
        for unit in sorted(settings.caps[provider]):
            used = db.usage_this_month(conn, provider, unit)
            print(f"  {provider} {unit}  {used} / {settings.caps[provider][unit]}")
    print("segments:")
    width = max(len(key) for key in segments)
    for key in sorted(segments):
        print(f"  {key.ljust(width)}  {segments[key].offer.ljust(13)}  {saved.get(key, 0)} saved")
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
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    segment = segments.get(args.segment)
    if segment is None:
        print(
            f"error: no segment called {args.segment!r}. Choose one of: {', '.join(sorted(segments))}",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.pages <= MAX_PAGES_PER_RUN:
        print(f"error: --pages must be between 1 and {MAX_PAGES_PER_RUN}", file=sys.stderr)
        return 2
    cap = _apollo_cap(settings)

    if not args.live:
        print("DRY RUN: nothing is sent to Apollo. Add --live to run it for real.\n")
        print(source.describe(conn, segment, pages=args.pages, cap=cap))
        return 0

    api_key = os.environ.get("APOLLO_API_KEY", "").strip()
    if not api_key:
        print(
            "error: APOLLO_API_KEY isn't set. Add it to the .env file in the project folder.",
            file=sys.stderr,
        )
        return 2
    if cap is None:
        print(
            "error: set caps.apollo.credits in config/settings.yaml before a live run.",
            file=sys.stderr,
        )
        return 2

    with new_client() as client:
        result = source.run_live(
            conn, segment, client=client, api_key=api_key, cap=cap, pages=args.pages
        )
    used = db.usage_this_month(conn, source.PROVIDER, source.UNIT)
    print(source.summarize(result, used=used, cap=cap))
    return 1 if result.error else 0


def cmd_export(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    if args.segment and args.segment not in segments:
        print(f"error: no segment called {args.segment!r}", file=sys.stderr)
        return 2
    kind = "contacts" if args.contacts else "companies"
    path = Path(args.out).resolve() if args.out else exports.default_path(settings.root, kind)
    if args.contacts:
        count = exports.export_leads(conn, path)
    else:
        count = exports.export_companies(conn, path, args.segment)
    print(f"wrote {count} {kind} to {_shown(path, settings.root)}")
    return 0


def cmd_clay_export(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    if args.segment and args.segment not in segments:
        print(f"error: no segment called {args.segment!r}", file=sys.stderr)
        return 2
    if args.rows < 1:
        print("error: --rows must be at least 1", file=sys.stderr)
        return 2
    result = enrich.export_batch(conn, settings.root, args.segment, args.rows)
    if result is None:
        print("Nothing waiting for Clay. Find more companies first (outbound source ...).")
        return 0
    print(
        f"wrote {result.rows} companies to {_shown(result.path, settings.root)} (batch {result.batch_id})"
    )
    print("Next: upload it to a Clay table. The steps are in docs/clay-table.md.")
    return 0


def cmd_clay_import(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
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
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    try:
        value, kind, added = suppression.suppress(conn, args.value, args.reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{'added' if added else 'already on the list'}: {kind} {value}")
    return 0


def cmd_fields(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: Connection,
) -> int:
    total, counts = fields.field_counts(conn, args.segment)
    print(fields.describe(total, counts))
    return 0


def cmd_backup(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outbound", description="Arsuno outbound pipeline")
    parser.add_argument("--root", default=".", help="project folder (default: the current folder)")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="show config, keys, budget and what's saved")
    check.set_defaults(func=cmd_check)

    src = commands.add_parser("source", help="find companies for a segment (dry run unless --live)")
    src.add_argument("segment", help="a segment name from config/segments.yaml")
    src.add_argument(
        "--pages", type=int, default=1, help="pages of 100 companies to fetch (default 1)"
    )
    src.add_argument("--live", action="store_true", help="really call Apollo and spend credits")
    src.set_defaults(func=cmd_source)

    exp = commands.add_parser("export", help="write saved companies to a CSV file")
    exp.add_argument("--segment", help="only this segment")
    exp.add_argument("--contacts", action="store_true", help="the people Clay found, not companies")
    exp.add_argument("--out", help="file to write (default: data/exports/<kind>_<time>.csv)")
    exp.set_defaults(func=cmd_export)

    clay_cmd = commands.add_parser(
        "clay", help="send companies to Clay, and read Clay's results back"
    )
    clay_steps = clay_cmd.add_subparsers(dest="clay_command", required=True)
    clay_out = clay_steps.add_parser("export", help="write the next companies to a CSV for Clay")
    clay_out.add_argument("--segment", help="only this segment")
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
    fld.add_argument("--segment", help="only this segment")
    fld.set_defaults(func=cmd_fields)

    backup = commands.add_parser("backup", help="write every table to data/backups/<UTC time>.json")
    backup.set_defaults(func=cmd_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    load_env(root / ".env")
    try:
        settings = load_settings(root)
        segments = load_segments(root)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    conn = db.connect(settings.root)
    try:
        return args.func(args, settings, segments, conn)
    finally:
        conn.close()
