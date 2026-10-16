# Guide

One section per module. Each has the same headings: What it does / In the UI / In the code /
How to run / Cost / Common problems.

The UI (FastAPI + React) is not built yet (M0b). Until then, "In the UI" notes what the screen
will cover; use the CLI today.

---

## Foundation

### What it does

Holds the shared pieces every stage uses: config, the database, HTTP, normalisation, the stage
list, the CLI, and backups. Talks to Supabase Postgres when `DATABASE_URL` is set, otherwise a
local SQLite file. Two people can run commands at the same time without double-claiming Clay
batches or going over the Apollo credit cap.

### In the UI

Overview: which database you're on (host or path, never the password), keys set or not, credits
used against the cap, companies per segment, leads per state, do-not-contact count.

### In the code

| File | Job |
|---|---|
| `backend/cli.py` | Commands only; no logic |
| `backend/config.py` | `settings.yaml`, `segments.yaml`, `.env` |
| `backend/db.py` | Engine, schema, every SQL statement |
| `backend/http.py` | Timeouts and retries |
| `backend/normalize.py` | Domains and emails in one form |
| `backend/pipeline.py` | `STAGES` and `LEAD_STATES` |
| `scripts/copy_sqlite_to_db.py` | One-time copy from an old SQLite file |

### How to run

```powershell
.venv\Scripts\outbound check
.venv\Scripts\outbound backup
```

`check` prints `postgres at <host>` or `sqlite at <path>`. It never prints `DATABASE_URL`.

### Cost

Free. No network.

### Common problems

- **config error** — fix the YAML file named in the message; run from the project folder.
- **database schema is version N** — this code is older than the database; update the code.
- **Two laptops** — put the Supabase Session pooler URL in `.env` as `DATABASE_URL` on both.

---

## Source

### What it does

Asks Apollo for US companies that match a segment (1–20 staff, keywords, HQ location). Saves new
ones, skips no-website and do-not-contact, remembers the next page, and stops before the monthly
credit cap. Reserves a credit **before** each call; a failed call keeps the reservation.

### In the UI

Pick a segment and page count. Preview is the dry run. Fetch needs an explicit "spend credits"
confirm.

### In the code

`backend/stages/source.py` orchestrates. `backend/integrations/apollo.py` is the only Apollo
client and only allows Organization Search.

### How to run

```powershell
.venv\Scripts\outbound source ai_accounting
.venv\Scripts\outbound source ai_accounting --live
.venv\Scripts\outbound source ai_accounting --live --pages 5
```

### Cost

1 Apollo credit per page (up to 100 companies). Dry run is free and never touches the network.

### Common problems

- **APOLLO_API_KEY isn't set** — put it in `.env`.
- **cap reached** — raise `caps.apollo.credits` in `config/settings.yaml` only when you mean to.
- **403 from Apollo** — the plan or key doesn't allow Organization Search.

---

## Enrich (Clay CSV)

### What it does

Writes the next waiting companies to a CSV for Clay (claiming them in one database update so two
exports never take the same company). After you run the Clay table by hand, reads Clay's CSV back,
matches each person to a company, applies the verify rules, and saves them as leads.

### In the UI

Create the Clay file and download it. Drop Clay's export back in, confirm columns, import. See
batches with people / emails / states.

### In the code

`backend/stages/enrich.py`. Column detection is in `detect_columns()`. Click-by-click Clay steps:
`docs/clay-table.md`.

### How to run

```powershell
.venv\Scripts\outbound clay export --rows 200
.venv\Scripts\outbound clay import path\to\clay_export.csv --credits 40
.venv\Scripts\outbound export --contacts
```

Use `--rows 50` on a Clay trial (50-row tables).

### Cost

No API cost from our side. Clay credits are whatever that table used; pass `--credits` on import
so the batches table can show cost per verified email.

### Common problems

- **Nothing waiting for Clay** — run `outbound source` first.
- **can't tell which column is: Email** — rename the column in Clay to match `docs/clay-table.md`.
- **Same company twice** — shouldn't happen; export claims rows with `UPDATE ... RETURNING`.

---

## Verify rules

### What it does

Turns Clay's email-check result into a lead state:

| Clay result | Lead state | Next |
|---|---|---|
| valid | `verified` | ready for later stages |
| catch-all or unknown | `needs_check` | re-checked with Instantly's verifier (not built yet) |
| role address (`info@`, …) | `hold` | waiting on decision D5 |
| no email, invalid, or do-not-contact | `dropped` | never sent |

Pure functions: no database, no network. Applied during Clay import today; Instantly re-check is
a later milestone.

### In the UI

Contacts/leads table filtered by state. Later: a "re-check maybes" action for Instantly.

### In the code

`backend/stages/verify.py` (`clay_status`, `decide`, `is_role_address`).

### How to run

No command of its own yet. States are set by `outbound clay import`. Inspect with
`outbound export --contacts` or `outbound check`.

### Cost

Free for the rules. Instantly verifier (later) is about 0.25 credits per email.

### Common problems

- **Too many `needs_check`** — normal for catch-alls; Instantly re-check comes in M2.
- **`hold` on info@** — intentional until D5 is decided.
