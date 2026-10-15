"""Command line: parses arguments, calls the step functions, prints what they return.

Commands:
  outbound check                         config, keys, budget, what's saved
  outbound source SEGMENT [--pages N]    dry run: shows the Apollo request and its cost
  outbound source SEGMENT --live         runs it for real (spends Apollo credits)
  outbound export [--segment S]          writes saved companies to a CSV file
  outbound suppress VALUE --reason TEXT  adds a domain or email to the do-not-contact list
  outbound fields [--segment S]          which fields Apollo sent (names and counts, no values)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from outbound import db
from outbound.config import (
    ConfigError,
    Segment,
    Settings,
    key_status,
    load_env,
    load_segments,
    load_settings,
)
from outbound.http import new_client
from outbound.steps import export, fields, source, suppress

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
    conn: sqlite3.Connection,
) -> int:
    month = db.current_month()
    saved = db.count_companies(conn)
    print("config:   ok (config/settings.yaml, config/segments.yaml)")
    print(f"database: {_shown(settings.database, settings.root)}")
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
    print(f"do-not-contact: {db.count_suppression(conn)} entries")
    return 0


def cmd_source(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: sqlite3.Connection,
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
    print(source.summarize(result, segment, used=used, cap=cap))
    return 1 if result.error else 0


def cmd_export(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: sqlite3.Connection,
) -> int:
    if args.segment and args.segment not in segments:
        print(f"error: no segment called {args.segment!r}", file=sys.stderr)
        return 2
    path = Path(args.out).resolve() if args.out else export.default_path(settings.root)
    count = export.export_companies(conn, path, args.segment)
    print(f"wrote {count} companies to {_shown(path, settings.root)}")
    return 0


def cmd_suppress(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: sqlite3.Connection,
) -> int:
    try:
        value, kind, added = suppress.suppress(conn, args.value, args.reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{'added' if added else 'already on the list'}: {kind} {value}")
    return 0


def cmd_fields(
    args: argparse.Namespace,
    settings: Settings,
    segments: dict[str, Segment],
    conn: sqlite3.Connection,
) -> int:
    total, counts = fields.field_counts(conn, args.segment)
    print(fields.describe(total, counts))
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
    exp.add_argument("--out", help="file to write (default: data/exports/companies_<time>.csv)")
    exp.set_defaults(func=cmd_export)

    sup = commands.add_parser("suppress", help="add a domain or email to the do-not-contact list")
    sup.add_argument("value", help="a domain like acme.com, or an email")
    sup.add_argument("--reason", required=True, help='why, like "existing client"')
    sup.set_defaults(func=cmd_suppress)

    fld = commands.add_parser("fields", help="which fields Apollo sent (names and counts only)")
    fld.add_argument("--segment", help="only this segment")
    fld.set_defaults(func=cmd_fields)
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
    conn = db.connect(settings.database)
    try:
        return args.func(args, settings, segments, conn)
    finally:
        conn.close()
