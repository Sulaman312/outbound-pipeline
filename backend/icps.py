"""ICPs: who we target. Checked and saved here, and only here.

An ICP holds the people filters for Clay (titles, person locations, what to exclude) and one
block of settings per source (backend/sources.py). It is never deleted, only deactivated,
because saved companies point at it. Every message is written for the person on the ICPs page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend import db
from backend.db import Connection
from backend.sources import BY_KEY, Field

_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_RANGE = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*$")


class IcpError(ValueError):
    """Something on the ICP form isn't right. The message says what to fix."""


@dataclass(frozen=True)
class Icp:
    key: str
    name: str
    description: str = ""
    offer: str = ""
    country: str = ""
    active: bool = True
    person_titles: list[str] = field(default_factory=list)
    person_locations: list[str] = field(default_factory=list)
    exclude_notes: str = ""
    target_leads: int = 0
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)  # source key -> settings


# --- checking -----------------------------------------------------------------------------------


def _text(data: dict[str, Any], name: str, label: str, *, required: bool = False) -> str:
    value = data.get(name)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise IcpError(f"{label} must be text")
    value = value.strip()
    if required and not value:
        raise IcpError(f"{label} can't be empty")
    return value


def _list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):  # one per line, as typed in a text box
        value = value.splitlines()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise IcpError(f"{label} must be a list of text values, one per line")
    cleaned: list[str] = []
    for item in (v.strip() for v in value):
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _int(value: Any, label: str, *, allow_empty: bool) -> int | None:
    if value is None or value == "":
        if allow_empty:
            return None
        raise IcpError(f"{label} can't be empty")
    if isinstance(value, bool):
        raise IcpError(f"{label} must be a whole number")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < 0:
        raise IcpError(f"{label} must be a whole number of 0 or more")
    return value


def _ranges(value: Any, label: str) -> list[str]:
    ranges = []
    for item in _list(value, label):
        match = _RANGE.match(item)
        if not match:
            raise IcpError(f'{label}: "{item}" must look like "1,10" (smallest, largest)')
        low, high = int(match[1]), int(match[2])
        if not 1 <= low <= high:
            raise IcpError(
                f'{label}: in "{item}" the first number must be 1 or more and not above the second'
            )
        ranges.append(f"{low},{high}")
    return ranges


def _setting(spec: Field, value: Any, source_label: str) -> Any:
    label = f"{source_label}: {spec.label}"
    if spec.kind == "list":
        return _list(value, label)
    if spec.kind == "ranges":
        return _ranges(value, label)
    if spec.kind == "int":
        number = _int(value, label, allow_empty=True)
        if number is not None and (
            (spec.low is not None and number < spec.low)
            or (spec.high is not None and number > spec.high)
        ):
            raise IcpError(f"{label} must be from {spec.low} to {spec.high}")
        return number
    if spec.kind == "text":
        if value is None:
            return None
        if not isinstance(value, str):
            raise IcpError(f"{label} must be text")
        text = value.strip().lower() if spec.pattern else value.strip()
        if text and spec.pattern and not re.fullmatch(spec.pattern, text):
            raise IcpError(f'{label}: "{value.strip()}" must be {spec.pattern_help}')
        return text or None
    if spec.kind == "bool":
        if value is None or value == "":
            return None
        if not isinstance(value, bool):
            raise IcpError(f"{label} must be yes or no")
        return value
    raise AssertionError(f"unknown field kind {spec.kind}")


def check_source_settings(source_key: str, settings: Any) -> dict[str, Any]:
    """One source's settings, cleaned, with defaults filled in. {} means "not used".

    A source counts as used when something other than a default or a yes/no is filled in.
    """
    source = BY_KEY.get(source_key)
    if source is None:
        raise IcpError(f"there is no source called {source_key!r}")
    if not isinstance(settings, dict):
        raise IcpError(f"{source.label} settings must be a set of fields")
    unknown = sorted(set(settings) - {f.key for f in source.fields})
    if unknown:
        raise IcpError(f"{source.label} has no setting called {unknown[0]!r}")
    given = {}
    for spec in source.fields:
        value = _setting(spec, settings.get(spec.key), source.label)
        if value not in (None, []):
            given[spec.key] = value
    used = any(
        spec.kind != "bool" and spec.key in given and given[spec.key] != spec.default
        for spec in source.fields
    )
    if not used:
        return {}
    for spec in source.fields:
        if spec.required and spec.key not in given:
            raise IcpError(
                f"{source.label}: {spec.label} can't be empty when {source.label} is used"
            )
        if spec.key not in given and spec.default is not None:
            given[spec.key] = spec.default
    return given


def check(data: dict[str, Any]) -> Icp:
    """A whole ICP from the form, cleaned, or IcpError naming the first problem."""
    if not isinstance(data, dict):
        raise IcpError("the ICP must be a set of fields")
    key = _text(data, "key", "Key", required=True).lower()
    if not _KEY.match(key):
        raise IcpError(
            "Key must be 2 to 40 lowercase letters, digits or _, starting with a letter, "
            'like "vets_us_small"'
        )
    raw_sources = data.get("sources") or {}
    if not isinstance(raw_sources, dict):
        raise IcpError("sources must be a set of settings per source")
    sources = {}
    for source_key, settings in raw_sources.items():
        cleaned = check_source_settings(str(source_key), settings)
        if cleaned:
            sources[str(source_key)] = cleaned
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise IcpError("Active must be yes or no")
    return Icp(
        key=key,
        name=_text(data, "name", "Name", required=True),
        description=_text(data, "description", "Description"),
        offer=_text(data, "offer", "Offer"),
        country=_text(data, "country", "Country"),
        active=active,
        person_titles=_list(data.get("person_titles"), "Job titles to find in Clay"),
        person_locations=_list(data.get("person_locations"), "Person locations in Clay"),
        exclude_notes=_text(data, "exclude_notes", "Exclude"),
        target_leads=_int(data.get("target_leads", 0), "Target leads", allow_empty=False) or 0,
        sources=sources,
    )


# --- reading and saving -------------------------------------------------------------------------


def _from_row(row: dict[str, Any], sources: dict[str, dict[str, Any]]) -> Icp:
    return Icp(
        key=row["key"],
        name=row["name"],
        description=row["description"],
        offer=row["offer"],
        country=row["country"],
        active=row["active"],
        person_titles=row["person_titles"],
        person_locations=row["person_locations"],
        exclude_notes=row["exclude_notes"],
        target_leads=int(row["target_leads"]),
        sources=sources,
    )


def get(conn: Connection, key: str) -> Icp | None:
    row = db.get_icp(conn, key)
    if row is None:
        return None
    return _from_row(row, db.list_icp_sources(conn, key).get(key, {}))


def list_all(conn: Connection) -> list[Icp]:
    """Every ICP, active ones first."""
    sources = db.list_icp_sources(conn)
    return [_from_row(row, sources.get(row["key"], {})) for row in db.list_icps(conn)]


def _plain(icp: Icp) -> dict[str, Any]:
    return {name: getattr(icp, name) for name in db.ICP_COLUMNS}


def _save_sources(conn: Connection, icp: Icp, before: dict[str, dict[str, Any]]) -> None:
    for source_key, settings in icp.sources.items():
        db.save_icp_source(conn, icp.key, source_key, settings)
    for source_key in set(before) - set(icp.sources):
        db.delete_icp_source(conn, icp.key, source_key)


def create(conn: Connection, data: dict[str, Any]) -> Icp:
    icp = check(data)
    with conn:
        if not db.insert_icp(conn, _plain(icp)):
            raise IcpError(f'there is already an ICP called "{icp.key}". Pick another key.')
        _save_sources(conn, icp, {})
    return icp


def update(conn: Connection, key: str, data: dict[str, Any]) -> Icp:
    """Change an ICP. Its key stays: companies and batches point at it."""
    before = get(conn, key)
    if before is None:
        raise LookupError(f'there is no ICP called "{key}"')
    icp = check({**data, "key": key})
    with conn:
        db.update_icp(conn, key, _plain(icp))
        _save_sources(conn, icp, before.sources)
    return icp


def set_active(conn: Connection, key: str, active: bool) -> Icp:
    icp = get(conn, key)
    if icp is None:
        raise LookupError(f'there is no ICP called "{key}"')
    with conn:
        db.update_icp(conn, key, {**_plain(icp), "active": active})
    return get(conn, key)  # type: ignore[return-value]


def summaries(conn: Connection) -> list[dict[str, Any]]:
    """Every ICP for the ICPs page, with companies saved and waiting for Clay."""
    saved = db.count_companies(conn)
    waiting = db.waiting_for_clay_by_icp(conn)
    return [
        {
            **icp.__dict__,
            "saved": saved.get(icp.key, 0),
            "waiting_for_clay": waiting.get(icp.key, 0),
        }
        for icp in list_all(conn)
    ]
