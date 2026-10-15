"""Loading and validating config.

Three kinds of config, all YAML under config/:
  settings.yaml   paths, provider settings, budgets (no secrets)
  countries.yaml  per-country names and compliance rules
  icps/*.yaml     one file per ICP: who to target and which sources to use

Secrets never live in these files. Each provider names the environment
variable that holds its key (e.g. APOLLO_API_KEY).

Source-specific blocks inside an ICP (`sources.apollo`, `sources.google_places`)
are kept as plain dicts here and validated by the source adapter itself, so
adding a new source never requires touching this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from outbound.errors import ConfigError, MissingSecretError


class ProviderSettings(BaseModel):
    api_key_env: str
    base_url: str | None = None
    monthly_request_cap: int | None = None  # hard stop; None = no cap
    min_seconds_between_requests: float = 0.0

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise MissingSecretError(f"Set the {self.api_key_env} environment variable.")
        return key


class HttpSettings(BaseModel):
    timeout_seconds: float = 30.0
    max_retries: int = 4
    backoff_seconds: float = 2.0


class Settings(BaseModel):
    database: Path
    exports_dir: Path
    http: HttpSettings = Field(default_factory=HttpSettings)
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)

    def provider(self, name: str) -> ProviderSettings:
        try:
            return self.providers[name]
        except KeyError:
            raise ConfigError(f"No provider '{name}' in settings.yaml") from None


class Compliance(BaseModel):
    require_email_source_url: bool = False  # Australia: proof of publication
    limited_companies_only: bool = False  # UK: no sole traders
    footer: str | None = None  # postal address / contact line


class Country(BaseModel):
    code: str
    name: str
    apollo_location: str
    places_region_code: str
    compliance: Compliance = Field(default_factory=Compliance)


class Disqualifiers(BaseModel):
    max_employees: int | None = None
    min_employees: int | None = None
    name_keywords: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class Icp(BaseModel):
    id: str
    name: str
    offer: str | None = None
    countries: list[str]
    disqualify: Disqualifiers = Field(default_factory=Disqualifiers)
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("countries")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [c.upper() for c in v]


class Config(BaseModel):
    root: Path
    settings: Settings
    countries: dict[str, Country]
    icps: dict[str, Icp]

    def icp(self, icp_id: str) -> Icp:
        try:
            return self.icps[icp_id]
        except KeyError:
            known = ", ".join(sorted(self.icps)) or "none"
            raise ConfigError(f"Unknown ICP '{icp_id}'. Known: {known}") from None

    def country(self, code: str) -> Country:
        try:
            return self.countries[code.upper()]
        except KeyError:
            raise ConfigError(f"Unknown country '{code}' (add it to countries.yaml)") from None


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_dir: str | Path) -> Config:
    """Load and validate everything under config_dir. Fails loudly on any problem."""
    root = Path(config_dir).resolve()
    try:
        settings = Settings(**_read_yaml(root / "settings.yaml"))
        countries = {
            code.upper(): Country(code=code.upper(), **body)
            for code, body in _read_yaml(root / "countries.yaml").items()
        }
        icps: dict[str, Icp] = {}
        for path in sorted((root / "icps").glob("*.yaml")):
            icp = Icp(**_read_yaml(path))
            if icp.id in icps:
                raise ConfigError(f"ICP id '{icp.id}' is defined twice ({path.name})")
            icps[icp.id] = icp
    except ValidationError as e:
        raise ConfigError(str(e)) from e

    # Relative paths in settings are relative to the pipeline folder (config's parent).
    base = root.parent
    if not settings.database.is_absolute():
        settings.database = base / settings.database
    if not settings.exports_dir.is_absolute():
        settings.exports_dir = base / settings.exports_dir

    for icp in icps.values():
        unknown = [c for c in icp.countries if c not in countries]
        if unknown:
            raise ConfigError(f"ICP {icp.id} uses unknown countries {unknown}")

    return Config(root=root, settings=settings, countries=countries, icps=icps)
