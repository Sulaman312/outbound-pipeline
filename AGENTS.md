# AGENTS.md

Rules for any coding agent (Cursor, Claude Code) working in this repo.

## What this is

A Python pipeline for cold email to US companies with 1–20 employees, about two offers: AI
automation, and outsourced front-end developers. Owner: Wania.

Read before doing anything:

- `docs/research.md`: facts about each tool, with sources.
- `docs/plan.md`: the design, the build order, and the decisions table (D1–D13).

## How work is done

- Build in the order of "Build order" in `docs/plan.md`: one step at a time, and only once the
  decisions it needs are made.
- If something needs a choice the plan doesn't make, stop and ask. Don't pick.
- Everything goes straight to `main`. No branches or pull requests (Wania's choice).
- Before pushing, run `ruff format . && ruff check . && pytest`. All three must pass.
- Keep `README.md` (how to run it) and `docs/plan.md` (what's built) in step with the code.

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
- Monthly caps in `config/settings.yaml` are hard stops. Don't raise them without a go-ahead.
- Secrets only in `.env` (gitignored). Config names the env var, never the key. Never print a
  secret's value.
- Never commit `.env`, keys, `data/`, or lead CSVs: they hold personal data.
- Suppression is checked before export to Clay and again before pushing to Instantly. Entries are
  never removed.

## Code style

- Keep it basic:
  - Plain functions and small modules, each with a docstring at the top.
  - All SQL lives in `src/outbound/db.py`. Other modules call its functions and never write SQL.
  - Standard library first. Add a dependency only when it clearly earns its place.
  - No base classes, registries, plugin systems or "manager" objects until a second real use
    exists.
- Python 3.11+, type hints on every function.
- Ruff: `ruff check . && ruff format .`
- Tests are offline only (fake HTTP). Every module ships with tests. No test may need a real key.
