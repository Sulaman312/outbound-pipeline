# outbound-pipeline

Cold email pipeline for Arsuno: US companies with 1–20 employees, two offers (AI automation, and
outsourced front-end developers). A web app on your own computer, sharing one Supabase database
between Wania's and Ayesha's laptops:

1. **ICPs**: describe who to target.
2. **Find companies** on Apollo, Google Maps, or both.
3. **Enrich with Clay**: a file goes to Clay, Clay's people and emails come back as leads.
4. Verify, send and track come next.

How each page works: [docs/guide.md](docs/guide.md). What's built and what's next:
[docs/plan.md](docs/plan.md). Facts about each tool: [docs/research.md](docs/research.md).

## One-time setup (Windows)

1. Install **Python 3.11+** (`py --version`) and **Node.js LTS** from https://nodejs.org
   (`node --version`).
2. Get the code and install it, in the project folder:
   ```powershell
   git pull
   py -m venv .venv
   .venv\Scripts\pip install -e .
   cd ui
   npm install
   npm run build
   cd ..
   ```
   Run `pip install -e .` again after a pull that changes `pyproject.toml`, and the `npm` lines
   again after one that changes `ui/`.
3. **Supabase:** in the Supabase project, Project Settings → Database, copy the **Session pooler**
   connection string (port 5432).
4. **Make a `.env`** next to this file (never commit it):
   ```
   DATABASE_URL=postgresql://postgres.[ref]:[YOUR-PASSWORD]@aws-0-....pooler.supabase.com:5432/postgres?sslmode=require
   APOLLO_API_KEY=...
   GOOGLE_PLACES_API_KEY=...
   ```
   The Google key is restricted to Places API (New). Leave `DATABASE_URL` empty to use a local
   SQLite file (`data/outbound.db`) instead.
5. **Check it:**
   ```powershell
   .venv\Scripts\outbound check
   ```
   It shows `postgres at <host>`, each key as `set` or `not set`, and usage against the monthly
   caps. It never shows a key or the database password.

Mac or Linux: `python3 -m venv .venv`, and `.venv/bin/` instead of `.venv\Scripts\`.

## Start the app

```powershell
.venv\Scripts\outbound serve
```

The browser opens http://127.0.0.1:8000. Only this computer can open it. Keep the terminal open
while you use it; Ctrl+C stops it. If it says the screens aren't built yet, run the `npm` lines
from step 2.
