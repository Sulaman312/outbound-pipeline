"""Copy an old data/outbound.db (the pre-M0a SQLite layout) into DATABASE_URL.

Safe to run twice (ON CONFLICT DO NOTHING). Prints rows copied per table.
Maps contacts.decision/reason -> leads.state/state_reason (ready->verified, etc.), and
segment -> icp. Each old segment is already an inactive ICP in the database.

Usage (from the project folder, with DATABASE_URL set):
  .venv\\Scripts\\python scripts/copy_sqlite_to_db.py
  .venv\\Scripts\\python scripts/copy_sqlite_to_db.py path/to/outbound.db
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _copy_table(
    source: sqlite3.Connection,
    dest: object,
    src_name: str,
    dst_name: str,
    rename: dict[str, str],
    decision_to_state: dict[str, str],
    now_utc: object,
) -> int:
    rows = source.execute(f"SELECT * FROM {src_name}").fetchall()
    if not rows:
        return 0
    src_cols = list(rows[0].keys())
    copied = 0
    with dest:  # type: ignore[attr-defined]
        for row in rows:
            params: dict[str, object] = {}
            for src_col in src_cols:
                dst_col = rename.get(src_col, src_col)
                value: object = row[src_col]
                if src_col == "decision":
                    value = decision_to_state.get(str(value), value)
                params[dst_col] = value
            if dst_name == "sourcing_progress":
                params.setdefault("source", "apollo")  # the only source before ICPs
            if dst_name == "leads":
                params.setdefault("state_changed_at", params.get("created_at") or now_utc())
            cols = list(params)
            placeholders = ", ".join(f":{c}" for c in cols)
            result = dest.execute(  # type: ignore[attr-defined]
                f"INSERT INTO {dst_name} ({', '.join(cols)}) VALUES ({placeholders}) "
                "ON CONFLICT DO NOTHING",
                params,
            )
            copied += result.rowcount
    return copied


def copy_sqlite(source_path: Path, dest: object) -> dict[str, int]:
    """Copy every known table from the old SQLite file into dest. Returns counts per dest table."""
    _ensure_path()
    from backend import db

    table_map: list[tuple[str, str, dict[str, str]]] = [
        ("suppression", "suppression", {}),
        ("usage", "usage", {}),
        ("sourcing_progress", "sourcing_progress", {"segment": "icp"}),
        ("batches", "batches", {"segment": "icp"}),
        ("companies", "companies", {"segment": "icp"}),
        ("contacts", "leads", {"decision": "state", "reason": "state_reason"}),
    ]
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        available = {
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        counts: dict[str, int] = {}
        for src_name, dst_name, rename in table_map:
            if src_name not in available:
                counts[dst_name] = 0
                continue
            counts[dst_name] = _copy_table(
                source,
                dest,
                src_name,
                dst_name,
                rename,
                db.DECISION_TO_STATE,
                db.now_utc,
            )
        return counts
    finally:
        source.close()


def main(argv: list[str] | None = None) -> int:
    _ensure_path()
    from backend import db
    from backend.config import load_env

    args = list(sys.argv[1:] if argv is None else argv)
    load_env(ROOT / ".env")
    source_path = Path(args[0]) if args else ROOT / "data" / "outbound.db"
    if not source_path.is_file():
        print(f"error: no SQLite file at {source_path}", file=sys.stderr)
        return 2
    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "error: set DATABASE_URL in .env to the Supabase Session pooler URL before copying.",
            file=sys.stderr,
        )
        return 2
    dest = db.connect(ROOT)
    try:
        print(f"source: {source_path}")
        print(f"target: {db.describe_database(dest.url, ROOT)}")
        counts = copy_sqlite(source_path, dest)
        for table, n in counts.items():
            print(f"  {table}: {n} row(s) copied")
        print(f"total: {sum(counts.values())} row(s)")
    finally:
        dest.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
