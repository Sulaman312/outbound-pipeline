# AGENTS.md

Rules for any coding agent (Cursor, Claude Code) working in this repo.

## What this is

A Python pipeline for cold email to US companies with 1–20 employees, about two offers: AI
automation, and outsourced front-end developers. Owner: Wania.

Read before doing anything:

- `docs/research.md`: facts about each tool, with sources.
- `docs/plan.md`: the stage list, what's built, the build order ahead, and the decisions table.
- `docs/guide.md`: the manual, one section per app page (What it does / In the app / In the
  code / Cost / Common problems).
- `README.md`: what this is, one-time setup, how to start the app.

## How work is done

- Build in the order of "Build order" in `docs/plan.md`: one step at a time, and only once the
  decisions it needs are made.
- If something needs a choice the plan doesn't make, stop and ask. Don't pick.
- Everything goes straight to `main`. No branches or pull requests (Wania's choice).
- Before pushing, run `ruff format . && ruff check . && pytest`. All three must pass.
- Every module ships with its `docs/guide.md` section.
- Docs: each module updates only its own `docs/guide.md` section and its status in
  `docs/plan.md`. `README.md` changes only when setup changes. No new doc files.

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
  secret's value. Never print `DATABASE_URL` (it contains the password).
- Never commit `.env`, keys, `data/`, or lead CSVs: they hold personal data.
- Suppression is checked before export to Clay and again before pushing to Instantly. Entries are
  never removed.

## Code layout

```
backend/
  cli.py                 serve, check, backup (everything else is in the app); no logic
  app.py                 FastAPI app: /api routes + serves ui/dist (127.0.0.1 only)
  api/                   routes by resource (overview, icps, source, companies, clay, leads,
                         suppression) + deps.py; routes call stage functions, no logic
  overview.py            what the Pipeline page shows
  sources.py             SOURCES: where companies come from + the settings an ICP keeps for each
  icps.py                ICPs (who we target): every check and save
  seed_icps.py           the ICPs a new database starts with
  config.py              settings.yaml + .env
  db.py                  engine, schema, every SQL statement
  http.py, normalize.py
  pipeline.py            STAGES + LEAD_STATES
  suppression.py         do-not-contact
  exports.py             CSV exports
  integrations/apollo.py, integrations/google_places.py
  stages/source.py       company sourcing per ICP and source (Apollo, Google Maps)
  stages/enrich.py       Clay CSV out and in
  stages/verify.py       lead-state rules from Clay's result
config/settings.yaml     caps
ui/                      React + Vite, plain CSS
  src/api.js             every fetch to the backend
  src/pages/             one file per sidebar page
```

Package install: `pip install -e .`. CLI entry: `outbound`. App: `outbound serve` (build the
screens once with `npm install && npm run build` in `ui/`). Never commit `ui/dist` or
`node_modules`.

## Sources and ICPs

- An ICP says who we target; it never decides the source. Each ICP keeps settings per source
  (`icp_sources`). No niche-specific code anywhere: a new niche is a new ICP.
- Every source saves into the same companies table (one row per domain, do-not-contact checked)
  and feeds the same Clay flow. A new source: add it to `backend/sources.py`, write its client in
  `backend/integrations/`, and its branch in `backend/stages/source.py`.

## Code style

- Keep it basic:
  - Plain functions and small modules, each with a docstring at the top.
  - All SQL lives in `backend/db.py`. Other modules call its functions and never write SQL.
  - Standard library first. Add a dependency only when it clearly earns its place.
  - No base classes, registries, plugin systems or "manager" objects until a second real use
    exists.
- Python 3.11+, type hints on every function.
- Ruff: `ruff check . && ruff format .`
- UI: React function components, no UI or state library, plain CSS in `ui/src/styles.css`.
  Keep components small; every fetch goes through `ui/src/api.js`.
- Tests are offline only (fake HTTP). Every module ships with tests. API routes are tested with
  FastAPI's TestClient. No test may need a real key.
  Default pytest uses SQLite. CI also runs against Postgres when `OUTBOUND_TEST_POSTGRES=1`.
