# Plan: a clean, basic outbound pipeline

Read [research.md](research.md) first. Every number here comes from there.

**Status:** M0a (Foundation) and M0b (App) are built: `backend/` package, Supabase Postgres
(SQLite for tests and offline), stage list, Clay CSV enrich, verify rules, and a local web app
(FastAPI + React) for all of it. M1–M7 are still design. See the decisions table at the bottom.

## Goal

Email the right person at US companies with 1–20 employees about two offers:

1. AI automation.
2. Outsourced front-end developers.

Code does the repeatable parts. Paid tools are used only where they're needed.

## The flow

```
  Apollo API
  (companies, 1–20 staff)
          |
          v
  ┌───────────────────────────┐
  │ companies  (Supabase PG)  │   one row per domain, ever
  └───────────────────────────┘
          |  clay export  →  CSV batches (claimed in one UPDATE)
          v
  Clay, by hand: find decision-maker → find work email → check email
          |  clay import  ←  Clay's CSV export
          v
  ┌───────────────────────────┐
  │ leads      (Supabase PG)  │   verified / needs_check / hold / dropped
  └───────────────────────────┘
          |  verify (Instantly) for needs_check   [not built]
          |  personalize → qa → send → track → classify   [not built]
          v
  Instantly campaigns (Growth), created by code; Miro campaign logic
```

## Stages (`backend/pipeline.py`)

| Stage | Built | Reads | Writes |
|---|---|---|---|
| source | yes | — | sourced |
| enrich | yes | sourced | enriched, verified, needs_check, hold, dropped |
| verify | yes (rules) | enriched, needs_check | verified, needs_check, hold, dropped |
| personalize | no | verified | personalized |
| qa | no | personalized | approved, hold |
| send | no | approved | in_campaign |
| track | no | in_campaign | replied, bounced, unsubscribed, finished |
| classify | no | replied | finished, dropped |

**Lead states:** sourced, enriched, verified, needs_check, hold, personalized, approved,
in_campaign, replied, bounced, unsubscribed, finished, dropped.

## Who does what

| Step | Tool | Done by | Why this tool |
|---|---|---|---|
| Find companies | Apollo Organization Search (Basic plan) | code | 1 credit per 100 companies |
| Find person, email, check it | Clay | you, by hand (CSV in and out) | Best email coverage; API is the $495 plan |
| Re-check needs_check | Instantly verifier | code | 0.25 credits per email |
| Campaigns and sending | Instantly Growth | code creates campaigns; Instantly sends | Miro campaign logic |
| Record and suppression | Supabase Postgres | code | Shared by two laptops; Instantly contact cap is not the permanent record |

## Data: Supabase Postgres (SQLite for tests)

Schema version 1 (`schema_version` table). Tests use SQLite. Production uses the Supabase
Session pooler URL (`DATABASE_URL`, port 5432, `sslmode=require`). Row level security is on
every table (no policies), so the public API key cannot read rows; we connect as the owner.

| Table | Key columns | Rule |
|---|---|---|
| `companies` | id, source, source_id, name, domain, segment, status, … | Unique domain. Status `new` → `exported` → `enriched` or `no_contact`. |
| `leads` | id, company_id, email, clay_status, state, state_reason, state_changed_at, … | Unique email. States as above. |
| `batches` | id, file, rows, clay_account, clay_credits, … | One Clay CSV round trip |
| `suppression` | value, kind, reason | Never deleted |
| `usage` | provider, unit, month, amount | Monthly caps; Apollo credits reserved before the call |
| `sourcing_progress` | segment, filters_hash, next_page, exhausted | Never pay for the same page twice |

Concurrency:

1. Clay export claims companies with one `UPDATE ... RETURNING`.
2. Apollo credits are reserved in one statement that refuses to go over the cap; failures keep the reservation.

## Commands

```
outbound check                                 # config, keys, db host/path, usage, counts   [built]
outbound serve                                 # the app at http://127.0.0.1:8000             [built]
outbound backup                                # every table → data/backups/<UTC>.json      [built]
outbound source SEGMENT [--pages N]            # dry run; --live spends Apollo credits        [built]
outbound export [--segment S]                  # companies CSV                                [built]
outbound export --contacts                     # leads CSV                                    [built]
outbound suppress VALUE --reason TEXT          # do-not-contact                               [built]
outbound fields [--segment S]                  # Apollo field names and counts                [built]
outbound clay export [--rows 200]              # claim companies → Clay CSV                   [built]
outbound clay import FILE [--account A] [--credits N]  # Clay CSV → leads                     [built]
outbound verify                                # needs_check → Instantly verifier (--live)
outbound campaign apply … / push / sync / report
```

Dry run by default. `--live` is required to spend credits. In the app, the same rule is a
"Spend up to N credits" tick box: the request must repeat the exact credits, and the box unticks
after every run.

## App (M0b)

`outbound serve` starts FastAPI on 127.0.0.1:8000 (this computer only; there is no login) and
serves the React screens built into `ui/dist`. Requests whose Host or Origin isn't this computer
are refused.

| Page | API routes | Calls |
|---|---|---|
| Pipeline | `GET /api/overview` | `overview.overview` (stages from `pipeline.py`) |
| Find companies | `GET /api/segments`, `POST /api/source/preview`, `POST /api/source/run` | `source.describe`, `source.run_live` |
| Companies | `GET /api/companies`, `GET /api/companies.csv` | `exports.company_rows` |
| Enrich with Clay | `POST /api/clay/export`, `GET /api/clay/batches[/{id}/file]`, `POST /api/clay/columns`, `POST /api/clay/import` | `enrich.export_batch`, `detect_columns`, `check_mapping`, `import_rows` |
| Leads | `GET /api/leads`, `GET /api/leads.csv` | `exports.lead_rows` |
| Do-not-contact | `GET /api/suppression`, `POST /api/suppression` (no delete) | `suppression.suppress` |

One database connection per request, closed at the end, so Supabase never holds an idle
transaction. Errors are JSON `{detail}`. Routes hold no logic of their own.

## Code layout

```
outbound-pipeline/
  pyproject.toml          # httpx, PyYAML, sqlalchemy, psycopg, fastapi, uvicorn; entry: outbound
  .env.example            # DATABASE_URL=, APOLLO_API_KEY=
  config/
    settings.yaml         # monthly caps
    segments.yaml         # targets (M1 replaces with ICPs)
  docs/
    research.md  plan.md  guide.md  clay-table.md
  backend/
    cli.py                # commands only
    app.py                # FastAPI app: /api routes + the built UI
    api/                  # routes by resource: overview, source, companies, clay, leads, suppression
    overview.py           # what the Pipeline page shows
    config.py             # settings + .env
    db.py                 # engine, schema, every SQL statement
    http.py  normalize.py
    pipeline.py           # STAGES + LEAD_STATES
    suppression.py  exports.py  fields.py
    integrations/apollo.py
    stages/source.py  enrich.py  verify.py
  ui/                     # React + Vite: api.js (every fetch), pages/ (one per sidebar item)
  scripts/copy_sqlite_to_db.py
  tests/                  # offline on SQLite; CI also runs against Postgres
```

## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Which source for which offer? | **OPEN.** Suggestion: Apollo for both in month 1. |
| D2 | Google Maps / Places? | **OPEN.** Decide in month 2. |
| D3 | Emails: Clay waterfall; plan/accounts | **DECIDED (2026-10-16):** Clay only, through CSV export/import by hand (Clay Free/trial has no API); no Google Sheet for now. Apollo only finds companies. Apollo person enrichment is not used: it charges 1 credit per person even with no email, and a test found very few emails. Company filters (HQ state, headcount, keywords) go to Apollo; people filters (titles, person location) go into the Clay table's "find people" step. Plan/account count still open; record credits per batch on import. |
| D4 | Email check / maybes | **DECIDED (M0a):** Clay "valid" = verified (ready). Catch-all/unknown = needs_check, re-checked with Instantly's verifier. Hold for role addresses until D5. |
| D5 | Role-based emails (`info@`) | **OPEN.** Suggestion: drop for Apollo leads. |
| D6 | Instantly plan | **DECIDED (2026-10-16):** Growth plan (1,000 contacts total, 5,000 emails a month, no webhooks); campaigns created in Instantly by code. Before a finished lead is removed from Instantly, its outcome is saved first. |
| D7 | Inboxes | **OPEN.** Need numbers. |
| D8 | CAN-SPAM details | **OPEN.** |
| D9 | Sequence / tracking / campaigns | **DECIDED (M0a):** Follow the Miro campaign logic; campaigns created in Instantly (Growth) by code. |
| D10 | Where companies come from | **DECIDED (2026-10-15):** Apollo Basic, Organization Search only (1 credit per 100 companies). Emails come from Clay (D3). |
| D11 | Re-contact | **OPEN.** Suggestion: once per offer. |
| D12 | Where the database lives | **DECIDED (M0a):** Supabase Postgres, shared by two laptops. Tests use SQLite. |
| D13 | AI-written first line | **OPEN.** Snooze until sending works. |
| D14 | UI | **DECIDED (M0a), BUILT (M0b):** FastAPI + React (Vite), local only (127.0.0.1). Streamlit is removed. |
| D15 | Where targets live | **DECIDED (2026-10-16):** ICPs are edited on an app page and stored in Supabase, replacing `config/segments.yaml` (M1). Caps stay in `config/settings.yaml` as hard stops. |
| D16 | Parked until just before M5 | Developer offer details; Arsuno's legal name and postal address for the footer (D8); inbox warmup on arsuno.io and arsuno.si (D7); tracking (the Miro plan has no tracking on day 1, but its follow-up branches depend on clicks and opens). |

## Build order

One module at a time; each is usable in the app and ships with its `docs/guide.md` section.
Pilot: lists built by 8 Nov, launch 9–15 Nov, so M0b–M5 should work by about 7 Nov.

| Step | What | Needs |
|---|---|---|
| M0a | **Built.** Foundation: `backend/` layout, Supabase/SQLite, pipeline stages, Clay CSV, verify rules, backup, copy script, CI on Postgres. | D3, D4, D9, D12, D14 |
| M0b | **Built.** App: FastAPI + React (Vite) for everything above. `outbound serve`. | D14 |
| M1 | ICPs (app page, stored in Supabase) + Source from them | D1, D15 |
| M2 | Enrich: Clay CSV per ICP (people filters in the Clay steps) | D3 |
| M3 | Verify: Instantly verifier for needs_check | D4, D5 |
| M4 | Personalize + QA + review queue | D13 if AI line |
| M5 | Send: Instantly campaigns created by code | D6–D9, D16 |
| M6 | Track + classify replies | D6, D11 |
| M7 | Follow-up campaigns + weekly report | — |

First ICPs (tentative, from the launch plan; they go into the ICP page in M1):

- **DEV_US_Signal_v1:** software/SaaS/dev agencies, 1–10 staff, HQ Texas + New York; people:
  Founder, Co-Founder, CEO, CTO, Owner; signal: open developer/engineer/full-stack job post in
  the last 60 days; 250 leads; arsuno.io; offer: full-stack developer outsourcing; exclude IT
  outsourcing and staff augmentation firms.
- **DEV_US_Pain_v1:** same ICP, no hiring signal found; 250 leads; arsuno.io.
- **BPA_US_Recruit_CaseStudy_v1:** staffing and recruiting agencies, 11–50 staff (1–10 only
  with at least 5 staff), HQ Texas + Florida; people: Founder, Owner, CEO, President, Managing
  Director, Director of Operations, Head of Delivery; 500 leads; arsuno.si; offer: business
  process automation (AI sourcing and screening); exclude solo recruiters, firms over 200 staff,
  national chains' branch offices.

Sequence: 4 steps (day 1, 3, 7, 14), send window 9–11am Eastern. Success test: positive reply
rate of 2% or more after 300 delivered emails.

## What was binned

Earlier layouts (`src/outbound`, Streamlit UI) were removed in M0a. Everything removed is still in
git history.
