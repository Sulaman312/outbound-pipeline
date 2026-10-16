# Plan: a clean, basic outbound pipeline

Read [research.md](research.md) first. Every number here comes from there.

**Status:** M0a (Foundation), M0b (App) and M1 (ICPs + Source) are built: `backend/` package,
Supabase Postgres (SQLite for tests and offline), stage list, ICPs with settings per source,
Apollo sourcing per ICP, Clay CSV enrich per ICP, verify rules, and a local web app (FastAPI +
React) for all of it, and M1b: Google Maps as the second company source. M2–M7 are still design. See the decisions table
at the bottom.

## Goal

Email the right person at US companies with 1–20 employees about two offers:

1. AI automation.
2. Outsourced front-end developers.

Code does the repeatable parts. Paid tools are used only where they're needed.

## The flow

```
  ICP (who we target; settings per source)
          |
  Apollo  ·  Google Maps (Places Text Search)      one or both, picked per run
          |
          v
  ┌───────────────────────────┐
  │ companies  (Supabase PG)  │   one row per domain, ever
  └───────────────────────────┘
          |  clay export ICP  →  CSV batches, one ICP each (claimed in one UPDATE)
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
| Find local businesses | Google Places API (New) Text Search | code | 1 request per 20 places; first 1,000 a month free |
| Find person, email, check it | Clay | you, by hand (CSV in and out) | Best email coverage; API is the $495 plan |
| Re-check needs_check | Instantly verifier | code | 0.25 credits per email |
| Campaigns and sending | Instantly Growth | code creates campaigns; Instantly sends | Miro campaign logic |
| Record and suppression | Supabase Postgres | code | Shared by two laptops; Instantly contact cap is not the permanent record |

## Data: Supabase Postgres (SQLite for tests)

Schema version 3 (`schema_version` table; version 1 is never edited; versions 2 (ICPs) and 3
(Google Maps) are migrations that run on the first start of the new code). Tests use SQLite. Production uses the Supabase
Session pooler URL (`DATABASE_URL`, port 5432, `sslmode=require`). Row level security is on
every table (no policies), so the public API key cannot read rows; we connect as the owner.

| Table | Key columns | Rule |
|---|---|---|
| `icps` | key, name, description, offer, country, active, person_titles, person_locations, exclude_notes, target_leads | Who we target. Never deleted, only made inactive. Lists are JSON text. |
| `icp_sources` | icp, source, settings | One row per ICP per source: Apollo = HQ locations, headcount, keywords, job-post signal; Google Maps = search phrases, cities, region code, place type, pages per search, skip chains. |
| `companies` | id, source (`apollo` / `google_places`), source_id (Apollo id / place id), name, domain, icp, city, state, status, likely_chain, … | Unique domain: a company belongs to the first ICP and source that saves it. Status `new` → `exported` → `enriched` or `no_contact`; `chain` for a likely chain held back from Clay. |
| `places` | place_id, domain, icp | Every Google place seen with a website. 3 or more places on one domain = likely chain. |
| `leads` | id, company_id, email, clay_status, state, state_reason, state_changed_at, … | Unique email. States as above. |
| `batches` | id, icp, file, rows, clay_account, clay_credits, … | One Clay CSV round trip, one ICP |
| `suppression` | value, kind, reason | Never deleted |
| `usage` | provider, unit, month, amount | Monthly caps; Apollo credits and Google requests reserved before each call |
| `sourcing_progress` | icp, source, filters_hash, next_page, exhausted | Apollo, per ICP. Never pay for the same page twice; changed settings start at page 1. |
| `query_progress` | icp, source, query, filters_hash, pages_done, next_token, exhausted | Google Maps, per ICP and search (phrase x city). Pages done are never repaid; a new region or place type starts again. |

Concurrency:

1. Clay export claims companies with one `UPDATE ... RETURNING`.
2. Apollo credits are reserved in one statement that refuses to go over the cap; failures keep the reservation.
3. The version 2 migration locks `schema_version` on Postgres, so two laptops starting new code
   at once migrate once. The schema is checked once per process per database, not per request.

## Commands

```
outbound check                                 # config, keys, db host/path, usage, counts   [built]
outbound serve                                 # the app at http://127.0.0.1:8000             [built]
outbound backup                                # every table → data/backups/<UTC>.json      [built]
outbound icps                                  # list ICPs (edit them in the app)             [built]
outbound source ICP [--source S] [--pages N]   # S = apollo or google_maps; --live spends     [built]
outbound export [--icp ICP]                    # companies CSV                                [built]
outbound export --contacts                     # leads CSV                                    [built]
outbound suppress VALUE --reason TEXT          # do-not-contact                               [built]
outbound fields [--icp ICP]                    # Apollo field names and counts                [built]
outbound clay export ICP [--rows 200]          # claim one ICP's companies → Clay CSV         [built]
outbound clay import FILE [--account A] [--credits N]  # Clay CSV → leads                     [built]
outbound verify                                # needs_check → Instantly verifier (--live)
outbound campaign apply … / push / sync / report
```

Dry run by default. `--live` is required to spend credits. In the app, the same rule is a
"Spend up to N credits" tick box: the request must repeat the exact credits, and the box unticks
after every run.

## App (M0b, M1)

`outbound serve` starts FastAPI on 127.0.0.1:8000 (this computer only; there is no login) and
serves the React screens built into `ui/dist`. Requests whose Host or Origin isn't this computer
are refused.

| Page | API routes | Calls |
|---|---|---|
| Pipeline | `GET /api/overview` | `overview.overview` (stages from `pipeline.py`) |
| ICPs | `GET /api/sources`, `GET/POST /api/icps`, `GET/PUT /api/icps/{key}`, `POST /api/icps/{key}/active` (no delete) | `icps.summaries`, `create`, `update`, `set_active` |
| Find companies | `POST /api/source/preview`, `POST /api/source/run` (ICP + sources + pages) | `source.describe`, `source.run_live` per source |
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
  docs/
    research.md  plan.md  guide.md  clay-table.md
  backend/
    cli.py                # commands only
    app.py                # FastAPI app: /api routes + the built UI
    api/                  # routes by resource: overview, icps, source, companies, clay, leads, suppression
    overview.py           # what the Pipeline page shows
    sources.py            # SOURCES: where companies come from, and the settings an ICP keeps for each
    icps.py               # ICPs: checking and saving (the only place)
    seed_icps.py          # the ICPs a database starts with (8 old segments, 3 pilot ICPs)
    config.py             # settings + .env
    db.py                 # engine, schema, every SQL statement
    http.py  normalize.py
    pipeline.py           # STAGES + LEAD_STATES
    suppression.py  exports.py  fields.py
    integrations/apollo.py  google_places.py
    stages/source.py  enrich.py  verify.py
  ui/                     # React + Vite: api.js (every fetch), pages/ (one per sidebar item)
  scripts/copy_sqlite_to_db.py
  tests/                  # offline on SQLite; CI also runs against Postgres
```

## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Which source for which offer? | **DECIDED (2026-10-16):** sources are chosen per ICP in the app (Apollo, Google Maps, or both per run). Apify is dropped. |
| D2 | Google Maps / Places? | **DECIDED (2026-10-16), BUILT (M1b):** Google Places API (New), Text Search, as the second source. Wania accepts the Google terms risk (storing names, websites, addresses, phones). Ask only for id, displayName, websiteUri, formattedAddress, addressComponents, nationalPhoneNumber, types, primaryType, businessStatus; never reviews or photos. Key `GOOGLE_PLACES_API_KEY`, restricted to Places API (New). Cap `caps.google_places.requests: 1000` (the free monthly allowance). Likely chains (3+ places on one website) are skipped by default, an ICP setting. |
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
| D17 | Sources and ICPs | **DECIDED (2026-10-16):** an ICP says who we target, not where to look. It keeps settings per source; every source saves into the same companies table (one row per domain, do-not-contact checked) and the same Clay flow. No niche-specific code: a new niche is a new ICP. |
| D18 | Pilot campaigns | **DECIDED (2026-10-16):** the 3 pilot ICPs are the 3 pilot campaigns (DEV_US_Signal_v1, DEV_US_Pain_v1, BPA_US_Recruit_CaseStudy_v1). Run `dev_us_signal` before `dev_us_pain`, so Signal keeps the companies they share. |
| D19 | Where exclusions apply | **DECIDED (2026-10-16):** in Clay, by hand, from the ICP's "Exclude" note shown on the Clay page. Apollo's company search returns no industry, so the app can't filter them. |

## Build order

One module at a time; each is usable in the app and ships with its `docs/guide.md` section.
Pilot: lists built by 8 Nov, launch 9–15 Nov, so M0b–M5 should work by about 7 Nov.

| Step | What | Needs |
|---|---|---|
| M0a | **Built.** Foundation: `backend/` layout, Supabase/SQLite, pipeline stages, Clay CSV, verify rules, backup, copy script, CI on Postgres. | D3, D4, D9, D12, D14 |
| M0b | **Built.** App: FastAPI + React (Vite) for everything above. `outbound serve`. | D14 |
| M1 | **Built.** ICPs (app page, stored in Supabase, settings per source) + Apollo sourcing per ICP; one Clay file per ICP with its people filters on the Clay page. Job-post signal sent as `q_organization_job_titles[]` + `organization_job_posted_at_range` (names confirmed 2026-10-16, research.md §1). | D1, D15, D17–D19 |
| M1b | **Built.** Google Maps (Places API (New) Text Search) as the second source: phrase x city searches per ICP, page tokens, per-search progress, request cap, closed/no-website/chain skips. First live test (1 search, 1 page, 1 request) waits for Wania's go-ahead. | D2 |
| M2 | Enrich: Clay CSV per ICP (the per-ICP file and people filters came with M1) | D3 |
| M3 | Verify: Instantly verifier for needs_check | D4, D5 |
| M4 | Personalize + QA + review queue | D13 if AI line |
| M5 | Send: Instantly campaigns created by code | D6–D9, D16 |
| M6 | Track + classify replies | D6, D11 |
| M7 | Follow-up campaigns + weekly report | — |

First ICPs (from the launch plan; created by the version 2 migration and edited on the ICPs
page as `dev_us_signal`, `dev_us_pain`, `bpa_us_recruit`):

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
