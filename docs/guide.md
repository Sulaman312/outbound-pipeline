# Guide

One section per module. Each has the same headings: What it does / In the UI / In the code /
How to run / Cost / Common problems.

Start the app with `.venv\Scripts\outbound serve` (see the App section). Every command below
still works in the terminal too.

---

## App

### What it does

A web page on your own computer for everything the pipeline can do today: see the pipeline,
find companies, search and download them, do the Clay round trip, see leads, and keep the
do-not-contact list. It uses the same code as the commands, so the rules are the same: dry run
first, credits only after you confirm, caps never exceeded, do-not-contact never removed.

Only your computer can open it (it listens on 127.0.0.1, and there is no login yet). Wania's
and Ayesha's laptops each run their own copy, and both talk to the same Supabase database.

### In the UI

A sidebar with six pages:

| Page | What you do there |
|---|---|
| **Pipeline** | See every step (built or not), how many leads are in each state, Apollo credits used against the cap, and whether the keys are set. |
| **Find companies** | Pick a segment and pages, Preview (free), tick "Spend up to N credits", Fetch. |
| **Companies** | Search by name or website, filter by segment, Download CSV. |
| **Enrich with Clay** | Step 1 download the file for Clay, step 2 the checklist for Clay, step 3 upload Clay's CSV and import. Batches table below. |
| **Leads** | Filter by state (verified, needs_check, hold, dropped), Download CSV. |
| **Do-not-contact** | Add a domain or email with a reason. The list can't be shortened. |

### In the code

| File | Job |
|---|---|
| `backend/app.py` | Builds the FastAPI app, mounts `/api`, serves `ui/dist` |
| `backend/api/*.py` | One file per resource; each route calls a stage function |
| `backend/api/deps.py` | Config and one database connection per request |
| `backend/overview.py` | Everything the Pipeline page shows |
| `ui/src/api.js` | Every call the screens make to the backend |
| `ui/src/App.jsx` | Sidebar and page switching (`#/page` in the address) |
| `ui/src/pages/*.jsx` | One file per page |
| `ui/src/styles.css` | All the styling |

The API's own reference page is at http://127.0.0.1:8000/api/docs while the app runs.

### How to run

Once (and again after a `git pull` that changes `ui/`):

```powershell
cd ui
npm install
npm run build
cd ..
```

Every time:

```powershell
.venv\Scripts\outbound serve
```

The browser opens http://127.0.0.1:8000. Leave the terminal open; Ctrl+C stops the app.

Changing the screens: run `outbound serve` in one terminal and `npm run dev` (in `ui/`) in
another, then open http://localhost:5173. It reloads as you edit.

### Cost

Free. Only "Fetch companies" spends Apollo credits, and only after you tick the box.

### Common problems

- **"The app's screens aren't built yet"** — run the `npm install` and `npm run build` steps above.
- **"Can't reach the app"** — the terminal running `outbound serve` was closed. Start it again.
- **Port 8000 is in use** — `outbound serve --port 8001`, then open http://127.0.0.1:8001.
- **A batch's Download link says the file isn't on this computer** — that file was made on the
  other laptop. The batch is in the shared database, but the file stays where it was made.
- **"Config error"** — fix the YAML file the message names, then reload the page (no restart needed).

---

## Foundation

### What it does

Holds the shared pieces every stage uses: config, the database, HTTP, normalisation, the stage
list, the CLI, and backups. Talks to Supabase Postgres when `DATABASE_URL` is set, otherwise a
local SQLite file. Two people can run commands at the same time without double-claiming Clay
batches or going over the Apollo credit cap.

### In the UI

**Pipeline** page: which database you're on (host or path, never the password), keys set or
not, Apollo credits used against the cap, companies found and waiting for Clay, and one card per
stage from `backend/pipeline.py` with the leads in each state it writes.

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

**Find companies** page: pick a segment and how many pages, then **Preview (free)**. That's the
dry run: it shows the Apollo filters, the pages, and the most it can cost, and never calls Apollo.
To run it, tick **Spend up to N Apollo credits** and press **Fetch companies**. The box unticks
after every run, so each run needs its own tick. If the key or the cap is missing, the preview
says so and there is no Fetch button.

**Companies** page: every saved company with its status, a search box, and **Download CSV**.

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

**Enrich with Clay** page, three numbered steps:

1. **Download the file for Clay.** Pick a segment (or all) and rows: 200 on Clay Free, 50 on a
   trial. **Create the file**, then **Download**.
2. **What to do in Clay.** A short checklist (the long version is `docs/clay-table.md`).
3. **Upload Clay's CSV.** The column dropdowns are pre-filled; check them, add the Clay account
   and credits used if you know them, and **Import**. You see how many leads landed in each state.

Below the steps, the **Batches** table: companies sent, people back, and each state per batch.

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

**Leads** page: filter by state with the chips at the top (each shows its count and what it
means), see why each lead got its state, and **Download CSV**. Later (M3): a "re-check
needs_check" action with Instantly's verifier.

### In the code

`backend/stages/verify.py` (`clay_status`, `decide`, `is_role_address`).

### How to run

No command of its own yet. States are set by `outbound clay import`. Inspect with
`outbound export --contacts` or `outbound check`.

### Cost

Free for the rules. Instantly verifier (later) is about 0.25 credits per email.

### Common problems

- **Too many `needs_check`** — normal for catch-alls; Instantly re-check comes in M3.
- **`hold` on info@** — intentional until D5 is decided.
