# outbound-pipeline

Cold email pipeline for Arsuno. It targets US companies with 1–20 employees, with two offers: AI
automation, and outsourced front-end developers.

**What works today: finding companies, then finding the person and email through Clay.**
- You describe who to target as **ICPs** on the app's ICPs page (shared by both laptops).
- For each ICP, it asks Apollo for matching companies (Google Maps comes next, in M1b).
- It saves the usable ones and skips no-website, do-not-contact, and duplicates.
- It remembers where it stopped, and never goes over the monthly credit cap.
- It writes an ICP's next companies to a file for Clay, with that ICP's people to look for
  (two laptops never claim the same company).
- It reads Clay's results back, and sorts every person into a lead state:
  - **verified**: Clay says valid;
  - **needs_check**: catch-all or unknown, re-checked with Instantly next;
  - **hold**: info@-style addresses;
  - **dropped**: no email, invalid, or do-not-contact.
- You can export companies or people to a CSV for Excel or Google Sheets.
- The database is Supabase Postgres (shared); tests and a no-`DATABASE_URL` laptop use SQLite.
- All of it works from a **web app on your own computer** (`outbound serve`), or from commands.

Next: Google Maps as a second source (M1b), then Instantly verification and campaigns. See
[docs/plan.md](docs/plan.md).

- [docs/clay-table.md](docs/clay-table.md) — what to click in Clay for each batch
- [docs/guide.md](docs/guide.md) — one section per module
- [docs/research.md](docs/research.md) — tools, costs, rules
- [docs/plan.md](docs/plan.md) — design, build order, decisions

---

## One-time setup (Windows)

1. **Python 3.11 or newer** (check with `py --version`) and **Node.js LTS** from
   https://nodejs.org (check with `node --version`). Node is only needed to build the app's
   screens.
2. **Get the code:**
   ```powershell
   cd outbound-pipeline
   git checkout main
   git pull
   ```
3. **Install it:**
   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -e .
   cd ui
   npm install
   npm run build
   cd ..
   ```
   Run the `pip install` line again after a `git pull` that changes `pyproject.toml`, and the
   three `npm`/`cd` lines again after one that changes `ui/`.
4. **Create a Supabase project** (free tier is fine to start). In Project Settings → Database,
   copy the **Session pooler** connection string (port **5432**). It should look like
   `postgresql://postgres.[ref]:[password]@aws-0-....pooler.supabase.com:5432/postgres`.
5. **Make a `.env`** next to `README.md` (never commit it):
   ```
   DATABASE_URL=postgresql://postgres.[ref]:[YOUR-PASSWORD]@aws-0-....pooler.supabase.com:5432/postgres?sslmode=require
   APOLLO_API_KEY=your-key-here
   ```
   The code rewrites this to the psycopg driver automatically. Leave `DATABASE_URL` empty to use
   a local SQLite file at `data/outbound.db` instead.
6. **If you have an old `data/outbound.db`**, copy it once into Supabase:
   ```powershell
   .venv\Scripts\python scripts\copy_sqlite_to_db.py
   ```
   Safe to run twice. Prints rows copied per table.
7. **Check it:**
   ```powershell
   .venv\Scripts\outbound check
   ```
   It should say `postgres at ...` (or `sqlite at data/outbound.db`), and `APOLLO_API_KEY  set`.
   It never shows the password or the full `DATABASE_URL`.

**Mac or Linux:** use `python3 -m venv .venv` and `.venv/bin/` instead of `.venv\Scripts\`.

---

## Start the app

```powershell
.venv\Scripts\outbound serve
```

Your browser opens http://127.0.0.1:8000. Keep the terminal open while you use it; Ctrl+C stops
it. Only this computer can open the app. Pages: Pipeline, Find companies, Companies, Enrich with
Clay, Leads, Do-not-contact. What each one does: [docs/guide.md](docs/guide.md#app).

If it says the screens aren't built yet, run the `cd ui`, `npm install`, `npm run build` lines
from step 3.

---

## Test it

The first live test spends **1 Apollo credit**. In the app: **Find companies → Preview (free)**,
then tick **Spend up to 1 Apollo credit** and **Fetch companies**. Or with commands:

1. **See the setup:** `.venv\Scripts\outbound check`
2. **Dry run (free):** `.venv\Scripts\outbound source bpa_us_recruit`
3. **Real run, 1 page:** `.venv\Scripts\outbound source bpa_us_recruit --live`
4. **Export:** `.venv\Scripts\outbound export`
5. **Run again** — it should continue at page 2.
6. **Do-not-contact:** `.venv\Scripts\outbound suppress thatdomain.com --reason "test"`

---

## Everyday commands

| Command | What it does | Cost |
|---|---|---|
| `outbound serve` | Starts the app at http://127.0.0.1:8000 | free |
| `outbound check` | Config, key status, database host/path, credits, counts | free |
| `outbound backup` | Every table → `data/backups/<UTC time>.json` | free |
| `outbound icps` | Lists the ICPs (edit them in the app) | free |
| `outbound source ICP` | Dry run: shows the Apollo request and its cost | free |
| `outbound source ICP --live` | Fetches 1 page (100 companies) | 1 credit |
| `outbound source ICP --live --pages 5` | Same for 5 pages | up to 5 credits |
| `outbound export` | Companies CSV (`--icp ICP` for one) | free |
| `outbound export --contacts` | Leads Clay found, with state | free |
| `outbound clay export ICP --rows 200` | An ICP's next companies → Clay file (50 on a trial) | free |
| `outbound clay import FILE --credits 40` | Clay's CSV → leads | free |
| `outbound suppress acme.com --reason "client"` | Do-not-contact (can't be undone) | free |
| `outbound fields` | Which fields Apollo sent (names and counts) | free |

On Windows, put `.venv\Scripts\` in front of each command.

## Changing who you target

- **ICPs** are made and edited on the app's **ICPs** page, and stored in the shared database.
  What each field means: [docs/guide.md](docs/guide.md#icps).
- **Monthly credit cap** is in `config/settings.yaml` (`caps.apollo.credits`).

## Where your data is

- **Supabase Postgres** (when `DATABASE_URL` is set) holds ICPs, companies, leads, batches,
  suppression, usage and progress. Back it up with `outbound backup` now and then.
- **`data/outbound.db`** is used only when `DATABASE_URL` is unset.
- **`data/exports/`**, **`data/clay/`**, **`data/backups/`** stay on disk and are gitignored.

## For developers

```bash
pip install -e ".[dev]"
ruff format . && ruff check . && pytest    # offline SQLite; no test needs a real key
cd ui && npm ci && npm run build           # the screens
```

Working on the screens: `outbound serve` in one terminal, `npm run dev` in `ui/` in another, then
open http://localhost:5173 (it sends `/api` to port 8000 and reloads as you edit).

CI also runs pytest against a Postgres service container, and builds `ui/`. Layout and rules: `AGENTS.md` and
`docs/plan.md`. Module guide: `docs/guide.md`.
