"""Everything the app's Pipeline page shows, in one read-only dict.

The stage list comes from backend/pipeline.py, so a new stage shows up on the board without
touching the UI. Keys are reported as set or not set, never their values. The database is shown
as a host or a path, never the URL.
"""

from __future__ import annotations

from typing import Any

from backend import db
from backend.config import Settings, key_status
from backend.db import Connection
from backend.pipeline import LEAD_STATES, STAGES
from backend.sources import SOURCES
from backend.stages import source


def overview(conn: Connection, settings: Settings) -> dict[str, Any]:
    """Stages with counts, Apollo credits against the cap, key status, and totals."""
    companies = db.count_companies_by_status(conn)
    icps = db.list_icps(conn)
    counts = {state: 0 for state in LEAD_STATES}
    counts.update(db.count_leads(conn))
    # Companies aren't leads yet, so "sourced" counts the companies any source found.
    counts["sourced"] = sum(companies.values())
    return {
        "stages": [
            {
                "key": stage.key,
                "label": stage.label,
                "built": stage.built,
                "reads": list(stage.reads),
                "writes": [{"state": state, "count": counts[state]} for state in stage.writes],
            }
            for stage in STAGES
        ],
        "states": counts,
        "companies": {
            "total": counts["sourced"],
            "by_status": companies,
            "by_icp": db.count_companies(conn),
            "waiting_for_clay": db.count_waiting_for_clay(conn),
        },
        "apollo": {
            "month": db.current_month(),
            "used": db.usage_this_month(conn, source.PROVIDER, source.UNIT),
            "cap": settings.caps.get("apollo", {}).get("credits"),
        },
        "usage": [
            {
                "source": s.key,
                "label": s.label,
                "unit": s.cap_unit,
                "used": source.used_this_month(conn, s.key),
                "cap": source.cap_for(settings.caps, s.key),
            }
            for s in SOURCES
            if s.built
        ],
        "keys": key_status(),
        "database": db.describe_database(conn.url, settings.root),
        "icps": {"active": sum(1 for i in icps if i["active"]), "total": len(icps)},
        "do_not_contact": db.count_suppression(conn),
    }
