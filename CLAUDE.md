# CLAUDE.md

## What this is

A Python pipeline for cold email to US companies with 1–20 employees, about two offers: AI
automation, and outsourced front-end developers. Owner: Wania.

Read before doing anything:

- `docs/research.md`: facts about each tool, with sources.
- `docs/plan.md`: the design, the build order, and the decisions table (D1–D12).

**Status:** research and plan only. No code yet. Build in the order given in `docs/plan.md`, and
start a step only once the decisions it needs are marked DECIDED.

## Decisions

- Don't choose providers, paid plans, compliance wording, re-contact policy or data handling for
  Wania. If the plan doesn't cover something, add it to the decisions table in `docs/plan.md` and
  ask.
- When a vendor fact turns out different from `docs/research.md`, update the doc in the same
  change.

## Safety (non-negotiable)

- Dry run by default. Anything that calls a paid or credit-using API needs `--live`, and a dry run
  must not touch the network.
- Never run `--live`, or anything that spends credits or money, without Wania's explicit go-ahead.
- Monthly caps in config are hard stops. Don't raise them without a go-ahead.
- Secrets only in `.env` (gitignored). Config names the env var, never the key.
- Never commit `.env`, keys, `data/`, or lead CSVs: they hold personal data.
- Suppression is checked before export to Clay and again before pushing to Instantly. Entries are
  never removed.

## Code style

- Keep it basic:
  - Plain functions and small modules, each with a docstring at the top.
  - Standard library first.
  - No base classes, registries or plugin systems until a second real use exists.
- Python 3.11+, type hints, ruff (`ruff check . && ruff format .`).
- Tests are offline only (fake HTTP). Every module ships with tests. No test may need a real key.
