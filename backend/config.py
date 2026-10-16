"""Load config/settings.yaml and .env. Nothing else. (Who we target lives in the database.)"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Environment variables the pipeline reads. Later steps add to this.
KNOWN_KEYS: tuple[str, ...] = ("APOLLO_API_KEY", "GOOGLE_PLACES_API_KEY", "DATABASE_URL")


class ConfigError(Exception):
    """A config file is missing or has a wrong value."""


@dataclass(frozen=True)
class Settings:
    root: Path  # project folder (absolute)
    caps: dict[str, dict[str, int]]  # provider -> unit -> monthly cap


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
    unknown = sorted(set(data) - {"caps"})
    if unknown:
        raise ConfigError(f"config/settings.yaml: unknown key {unknown[0]!r}")

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

    return Settings(root=root, caps=caps)


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
