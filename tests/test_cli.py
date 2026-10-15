from outbound.cli import main
from tests.conftest import CONFIG_DIR


def test_check_and_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    cfg = tmp_path / "config"
    (cfg / "icps").mkdir(parents=True)
    for f in ["countries.yaml", "icps/a_software.yaml"]:
        (cfg / f).write_text((CONFIG_DIR / f).read_text())
    settings = (
        (CONFIG_DIR / "settings.yaml")
        .read_text()
        .replace("data/outbound.db", str(tmp_path / "t.db"))
    )
    (cfg / "settings.yaml").write_text(settings)

    assert main(["--config", str(cfg), "check"]) == 0
    assert "APOLLO_API_KEY NOT set" in capsys.readouterr().out

    # Dry run works with no key at all and calls nothing.
    assert main(["--config", str(cfg), "source", "--icp", "A", "--country", "US"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "United States" in out

    assert main(["--config", str(cfg), "source", "--icp", "Z", "--country", "US"]) == 2
