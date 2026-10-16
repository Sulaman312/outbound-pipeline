# Plan: a clean, basic outbound pipeline

Read [research.md](research.md) first. Every number here comes from there.

**Status:** M0a (Foundation) is built: `backend/` package, Supabase Postgres (SQLite for
tests and offline), stage list, Clay CSV enrich, verify rules. M0b (UI) and M1–M7 are still
design. See the decisions table at the bottom.

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

Dry run by default. `--live` is required to spend credits.

## Code layout

```
outbound-pipeline/
  pyproject.toml          # httpx, PyYAML, sqlalchemy, psycopg; entry: outbound
  .env.example            # DATABASE_URL=, APOLLO_API_KEY=
  config/
    settings.yaml         # monthly caps
    segments.yaml         # targets (M1 replaces with ICPs)
  docs/
    research.md  plan.md  guide.md  clay-table.md
  backend/
    cli.py                # commands only
    config.py             # settings + .env
    db.py                 # engine, schema, every SQL statement
    http.py  normalize.py
    pipeline.py           # STAGES + LEAD_STATES
    suppression.py  exports.py  fields.py
    integrations/apollo.py
    stages/source.py  enrich.py  verify.py
  scripts/copy_sqlite_to_db.py
  tests/                  # offline on SQLite; CI also runs against Postgres
```

## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Which source for which offer? | **OPEN.** Suggestion: Apollo for both in month 1. |
| D2 | Google Maps / Places? | **OPEN.** Decide in month 2. |
| D3 | Emails: Clay waterfall; plan/accounts | **DECIDED (M0a):** Clay waterfall through CSV export/import, no Google Sheet for now. Whether Apollo also supplies emails is decided in M1. Plan/account count still open; record credits per batch on import. |
| D4 | Email check / maybes | **DECIDED (M0a):** Clay "valid" = verified (ready). Catch-all/unknown = needs_check, re-checked with Instantly's verifier. Hold for role addresses until D5. |
| D5 | Role-based emails (`info@`) | **OPEN.** Suggestion: drop for Apollo leads. |
| D6 | Instantly plan | **DECIDED (M0a):** Growth plan; campaigns created in Instantly by code. Clearing finished leads still to confirm vs Hypergrowth. |
| D7 | Inboxes | **OPEN.** Need numbers. |
| D8 | CAN-SPAM details | **OPEN.** |
| D9 | Sequence / tracking / campaigns | **DECIDED (M0a):** Follow the Miro campaign logic; campaigns created in Instantly (Growth) by code. |
| D10 | Where companies come from | **DECIDED (2026-10-15):** Apollo Basic. Whether emails also come from Apollo is M1. |
| D11 | Re-contact | **OPEN.** Suggestion: once per offer. |
| D12 | Where the database lives | **DECIDED (M0a):** Supabase Postgres, shared by two laptops. Tests use SQLite. |
| D13 | AI-written first line | **OPEN.** Snooze until sending works. |
| D14 | UI | **DECIDED (M0a):** FastAPI + React (Vite). Streamlit is removed. Built in M0b. |

## Build order

| Step | What | Needs |
|---|---|---|
| M0a | **Built.** Foundation: `backend/` layout, Supabase/SQLite, pipeline stages, Clay CSV, verify rules, backup, copy script, CI on Postgres. | D3, D4, D9, D12, D14 (partial) |
| M0b | FastAPI + React (Vite) UI for the built stages | D14 |
| M1 | ICPs replace segments; decide Apollo vs Clay for emails | D1, D3/D10 email source |
| M2 | Instantly verifier for needs_check | D4, D5 |
| M3 | Campaign from Miro logic; push leads | D6–D9 |
| M4 | Sync, suppression, clearing finished leads | D6, D11 |
| M5 | Report | — |
| M6 | Personalize / QA gates | D13 if AI line |
| M7 | Google Places | only if D2 = yes |

## What was binned

Earlier layouts (`src/outbound`, Streamlit UI) were removed in M0a. Everything removed is still in
git history.
