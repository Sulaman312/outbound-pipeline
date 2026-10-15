"""Which fields the provider actually sent, and how many saved companies have a value in each.

Reads the original records saved in the database. Prints field names and counts only, never
values, so the output is safe to share. Use it to check or fix how fields are mapped.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from outbound import db


def field_counts(
    conn: sqlite3.Connection, segment: str | None = None
) -> tuple[int, list[tuple[str, int]]]:
    """(number of records, [(field name, how many records have a value)]), sorted by name."""
    raws = db.raw_records(conn, segment)
    counts: Counter[str] = Counter()
    for raw in raws:
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        for name, value in record.items():
            counts[name] += 0 if value in (None, "", [], {}) else 1
    return len(raws), sorted(counts.items())


def describe(total: int, counts: list[tuple[str, int]]) -> str:
    if not total:
        return "No saved companies yet. Run `outbound source SEGMENT --live` first."
    width = max(len(name) for name, _ in counts) if counts else 0
    lines = [f"Fields in {total} saved records (how many have a value). Names only, no values:"]
    lines += [f"  {name.ljust(width)}  {filled}" for name, filled in counts]
    return "\n".join(lines)
