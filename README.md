# outbound

The Arsuno outbound pipeline. Design: [ARCHITECTURE.md](ARCHITECTURE.md).

## Setup

```bash
git clone https://github.com/wania4264/outbound-pipeline.git && cd outbound-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # then fill in the keys you have
```

## Use

```bash
outbound check                                  # config valid? which keys are set?
outbound source --icp A --country US            # dry run: prints the requests, calls nothing
outbound source --icp A --country US --live     # calls Apollo (0 credits) and stores leads
outbound stats                                  # leads per stage, API requests this month
outbound export --icp A --stage sourced         # CSV in data/exports/
outbound suppress --domain acme.com --reason "asked to stop"
```

## Tests and lint

```bash
pytest
ruff check . && ruff format --check .
```

Tests use fake APIs only; they never call a provider or need a key.

## Layout

```
config/                 everything you change without touching code (ICPs, countries, budgets)
src/outbound/
  models.py             the Lead format shared by every stage
  config.py             loads and validates config/
  store.py              SQLite: leads, raw provider data, runs, usage, suppression
  http.py               one HTTP client: retries, pacing, monthly caps
  normalize.py          domains, names, dedupe keys
  sources/              one adapter per lead source (apollo, google_places)
  stages/sourcing.py    stage 1
  export.py, cli.py
tests/
```
