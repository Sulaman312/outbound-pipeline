"""Load config/settings.yaml, config/segments.yaml and .env. Nothing else."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Environment variables the pipeline reads. Later steps add to this.
KNOWN_KEYS: tuple[str, ...] = ("APOLLO_API_KEY",)

OFFERS: tuple[str, ...] = ("ai_automation", "frontend")

_SEGMENT_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_SEGMENT_FIELDS = ("offer", "description", "employees", "locations", "keywords")


class ConfigError(Exception):
    """A config file is missing or has a wrong value."""


@dataclass(frozen=True)
class Settings:
    root: Path  # project folder (absolute)
    database: Path  # absolute path to the SQLite file
    caps: dict[str, dict[str, int]]  # provider -> unit -> monthly cap


@dataclass(frozen=True)
class Segment:
    key: str
    offer: str
    description: str
    employees: tuple[str, ...]  # Apollo headcount ranges, like "1,20"
    locations: tuple[str, ...]  # company HQ locations
    keywords: tuple[str, ...]  # Apollo company keyword tags


def _read_yaml(root: Path, name: str) -> dict[str, Any]:
    path = root / "config" / name
    if not path.is_file():
        raise ConfigError(
            f"config/{name} is missing (looked in {path.parent}). Run from the project folder."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"config/{name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config/{name} must be a mapping of keys to values")
    return data


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_settings(root: Path) -> Settings:
    """Read and check config/settings.yaml."""
    data = _read_yaml(root, "settings.yaml")
    unknown = sorted(set(data) - {"database", "caps"})
    if unknown:
        raise ConfigError(f"config/settings.yaml: unknown key {unknown[0]!r}")

    database = data.get("database")
    if not isinstance(database, str) or not database.strip():
        raise ConfigError("config/settings.yaml: 'database' must be a file path")

    caps = data.get("caps")
    if not isinstance(caps, dict):
        raise ConfigError(
            "config/settings.yaml: 'caps' must be a mapping like {apollo: {credits: 50}}"
        )
    for provider, units in caps.items():
        if not isinstance(units, dict) or not units:
            raise ConfigError(f"config/settings.yaml: caps.{provider} must map units to numbers")
        for unit, value in units.items():
            if not _is_int(value) or value < 0:
                raise ConfigError(
                    f"config/settings.yaml: caps.{provider}.{unit} must be a whole number >= 0"
                )

    return Settings(root=root, database=(root / database).resolve(), caps=caps)


def _string_list(value: Any, where: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{where} must be a list of text values")
    if not value and not allow_empty:
        raise ConfigError(f"{where} must not be empty")
    return tuple(v.strip() for v in value)


def _check_range(text: str, where: str) -> None:
    parts = text.split(",")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ConfigError(f'{where}: {text!r} must look like "1,20"')
    low, high = (int(p) for p in parts)
    if not 1 <= low <= high:
        raise ConfigError(f"{where}: {text!r} must have 1 <= min <= max")


def load_segments(root: Path) -> dict[str, Segment]:
    """Read and check config/segments.yaml."""
    data = _read_yaml(root, "segments.yaml")
    raw = data.get("segments")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("config/segments.yaml: 'segments' must list at least one segment")

    segments: dict[str, Segment] = {}
    for key, fields in raw.items():
        where = f"config/segments.yaml: segment {key!r}"
        if not isinstance(key, str) or not _SEGMENT_KEY.match(key):
            raise ConfigError(f"{where}: name must be lowercase letters, digits and _")
        if not isinstance(fields, dict):
            raise ConfigError(f"{where} must be a mapping")
        missing = [f for f in _SEGMENT_FIELDS if f not in fields]
        if missing:
            raise ConfigError(f"{where}: missing {missing[0]!r}")
        unknown = sorted(set(fields) - set(_SEGMENT_FIELDS))
        if unknown:
            raise ConfigError(f"{where}: unknown key {unknown[0]!r}")
        if fields["offer"] not in OFFERS:
            raise ConfigError(f"{where}: offer must be one of {', '.join(OFFERS)}")
        if not isinstance(fields["description"], str) or not fields["description"].strip():
            raise ConfigError(f"{where}: description must be text")

        employees = _string_list(fields["employees"], f"{where}: employees")
        for text in employees:
            _check_range(text, f"{where}: employees")

        segments[key] = Segment(
            key=key,
            offer=fields["offer"],
            description=fields["description"].strip(),
            employees=employees,
            locations=_string_list(fields["locations"], f"{where}: locations"),
            keywords=_string_list(fields["keywords"], f"{where}: keywords", allow_empty=True),
        )
    return segments


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into os.environ, never overriding what's set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def key_status() -> dict[str, bool]:
    """For each known key: is it set to something? Never returns the values."""
    return {name: bool(os.environ.get(name, "").strip()) for name in KNOWN_KEYS}
