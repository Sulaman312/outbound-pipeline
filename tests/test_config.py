import pytest
from pydantic import ValidationError

from outbound.config import load_config
from outbound.errors import ConfigError, MissingSecretError
from outbound.sources import SOURCES
from tests.conftest import CONFIG_DIR


def test_shipped_config_loads_and_every_source_block_is_valid():
    cfg = load_config(CONFIG_DIR)
    assert {"A", "B", "C"} <= set(cfg.icps)
    for icp in cfg.icps.values():
        for name, opts in icp.sources.items():
            assert name in SOURCES, f"ICP {icp.id} uses unknown source {name}"
            SOURCES[name].Options(**opts)


def test_unknown_country_in_icp_is_rejected(tmp_path):
    for f in ("settings.yaml", "countries.yaml"):
        (tmp_path / f).write_text((CONFIG_DIR / f).read_text())
    (tmp_path / "icps").mkdir()
    (tmp_path / "icps" / "x.yaml").write_text("id: X\nname: x\ncountries: [FR]\n")
    with pytest.raises(ConfigError, match="unknown countries"):
        load_config(tmp_path)


def test_typo_in_source_options_is_an_error():
    with pytest.raises(ValidationError):
        SOURCES["apollo"].Options(person_tittles=["CEO"])


def test_missing_secret(monkeypatch):
    cfg = load_config(CONFIG_DIR)
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    with pytest.raises(MissingSecretError, match="APOLLO_API_KEY"):
        cfg.settings.provider("apollo").api_key()
