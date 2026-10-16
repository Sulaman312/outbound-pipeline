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

A sidebar with seven pages:

| Page | What you do there |
|---|---|
| **Pipeline** | See every step (built or not), how many leads are in each state, Apollo credits used against the cap, and whether the keys are set. |
| **ICPs** | Who we target: create, edit, turn off. Settings per source and the people to find in Clay. |
| **Find companies** | Pick an ICP and Apollo, Google Maps or both, Preview (free), tick each "Spend up to N" box, Fetch. |
| **Companies** | Search by name or website, filter by ICP and source, see likely chains, Download CSV. |
| **Enrich with Clay** | Pick an ICP. Step 1 download its file for Clay, step 2 the checklist with that ICP's titles and locations, step 3 upload Clay's CSV and import. Batches table below. |
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
| `backend/config.py` | `settings.yaml`, `.env` |
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

## ICPs

### What it does

An ICP says **who** we target: a name, the offer, the people to find in Clay (job titles,
person locations, what to leave out), and how many leads we want. It also keeps its own
settings for **each place we find companies**:

| Source | Settings | Built |
|---|---|---|
| Apollo | Company HQ locations, headcount ranges (like `1,10`), keywords, job-post signal | yes |
| Google Maps | Search phrases, cities, region code, place type, pages per search, skip chains | yes |

There is no code for a particular niche. Vets, dentists or dev agencies are each just an ICP.
ICPs live in the shared database, so Wania's and Ayesha's laptops see the same list. They are
never deleted, only turned off, because saved companies point at them.

The database started with 11 ICPs: the 3 pilot ICPs (active) and the 8 old segments
(inactive, so the companies already found under them keep a real ICP).

| ICP | Campaign | Apollo search | People in Clay |
|---|---|---|---|
| `dev_us_signal` | DEV_US_Signal_v1 | Software/SaaS/dev agencies, 1–10 staff, HQ Texas + New York, open developer job post in the last 60 days | Founder, Co-Founder, CEO, CTO, Owner in TX/NY |
| `dev_us_pain` | DEV_US_Pain_v1 | Same, without the job-post signal | Same |
| `bpa_us_recruit` | BPA_US_Recruit_CaseStudy_v1 | Staffing and recruiting, 11–50 staff, HQ Texas + Florida | Founder, Owner, CEO, President, Managing Director, Director of Operations, Head of Delivery in TX/FL |

**Two things to know:**

- **The job-post signal doesn't run yet.** Apollo's exact filter names for job posts aren't
  confirmed (`docs/research.md`, section 1). So `dev_us_signal` shows its filters in the
  preview but can't fetch. Once the names are confirmed, it's one switch in the code.
- **Signal before Pain.** A company is saved once, under the first ICP that finds it. Run
  `dev_us_signal` first; `dev_us_pain` then skips what Signal already saved.

### In the UI

**ICPs** page: the list, active first, with companies saved, companies waiting for Clay, and the
target. **New ICP** opens the form; **Edit** changes one; **Turn off / Turn on** switches it.

The form has four parts: who (key, name, offer, country, target, active), people to find in
Clay, and one box per source. Lists are typed one per line. If you change where to find
companies for an ICP that has already searched, a yellow warning says the next run starts again
at page 1 (and pays for those pages again). Companies already saved stay.

Mistakes get a plain message, like `Apollo: Headcount ranges: "1-20" must look like "1,10"`.

### In the code

| File | Job |
|---|---|
| `backend/sources.py` | `SOURCES`: each source, whether it's built, its cost, and the settings an ICP keeps for it |
| `backend/icps.py` | All the checks (`check`) and saving (`create`, `update`, `set_active`) |
| `backend/seed_icps.py` | The 11 ICPs a database starts with |
| `backend/db.py` | `icps` and `icp_sources` tables; `_migrate_to_2` moved segments to ICPs |
| `backend/api/icps.py` | `/api/sources`, `/api/icps` routes |
| `ui/src/pages/Icps.jsx`, `IcpForm.jsx` | The list and the form |

### How to run

In the app: **ICPs** in the sidebar. In the terminal, `.venv\Scripts\outbound icps` lists them.

### Cost

Free. Saving an ICP never calls a source.

### Common problems

- **"Key must be 2 to 40 lowercase letters…"** — use something like `vets_us_small`. The key
  can't change later, so pick it with care; the name can change any time.
- **An ICP is missing from Find companies** — it's turned off. Turn it on on the ICPs page.
- **"has no Apollo settings"** — fill in at least HQ locations and headcount ranges.
- **"has no Google Maps settings"** — fill in at least search phrases and cities.

---

## Source

### What it does

Finds companies for one ICP, from the sources you pick: Apollo, Google Maps, or both (Apollo
runs first). Every source saves into the same companies list: one row per website, ever, and
never a do-not-contact domain. It remembers where each source stopped, and stops before each
source's monthly cap. It reserves usage **before** each call; a failed call keeps the
reservation. Google Maps has its own section below.

### In the UI

**Find companies** page: pick an active ICP, tick the sources (and the Apollo pages), then
**Preview (free)**. That's the dry run: for each source it shows the exact filters or searches,
the most it can cost, and the month's usage, and it never calls a source. Each source has its own
tick box, like **Spend up to 1 Apollo credits** and **Spend up to 8 Google Maps requests (free
up to 1,000 a month)**. **Fetch companies** works once every box is ticked. The boxes untick after
every run. If a key, a cap or the ICP's settings for a source are missing, the preview says so
and there is no Fetch button. After a run, a table shows for each source: found, saved, no
website, closed, already saved, chains and do-not-contact, and Apollo's pool size.

**Companies** page: every saved company with its source (Apollo or Google Maps), city, status
and a "likely chain" mark, with filters for ICP and source, a search box, and **Download CSV**.

### In the code

`backend/stages/source.py` checks the ICP and source (`icp_problem`, `live_problem`), then
runs the source's fetch. `backend/integrations/apollo.py` is the only Apollo client and only
allows Organization Search; `backend/integrations/google_places.py` is the only Google client. A new source gets its own file in `integrations/` and its own branch
in `source.py`; ICPs don't change.

### How to run

```powershell
.venv\Scripts\outbound source bpa_us_recruit
.venv\Scripts\outbound source bpa_us_recruit --live
.venv\Scripts\outbound source bpa_us_recruit --live --pages 5
.venv\Scripts\outbound source vets_tx --source google_maps
```

### Cost

Apollo: 1 credit per page (up to 100 companies). Google Maps: see below. The dry run is free and
never touches the network.

### Common problems

- **APOLLO_API_KEY isn't set** — put it in `.env`.
- **cap reached** — raise `caps.apollo.credits` in `config/settings.yaml` only when you mean to.
- **403 from Apollo** — the plan or key doesn't allow Organization Search.
- **"has a job-post signal…"** — see the ICPs section: the signal isn't confirmed yet.
- **"already saved: N (by this ICP or another one)"** — those companies belong to an ICP that
  found them first. That's how Signal and Pain stay apart.

---

## Google Maps source

### What it does

Finds local businesses on Google Maps (Places API (New), Text Search) for an ICP. It searches
each of the ICP's **search phrases in each of its cities** ("vet clinic in Austin, TX"), up to 3
pages of 20 places per search (Google stops at 60). For each place it keeps the name, website,
address, phone and type, and saves it as a company with source `google_places`. It skips and
counts:

- **no website**: we need a domain for Clay;
- **closed**: `businessStatus` isn't `OPERATIONAL` (closed for now, for good, or unknown);
- **do-not-contact**: the website's domain is on the list;
- **already saved**: the same domain or place, from this ICP, another ICP or Apollo;
- **likely chains**: the same website at 3 or more places (say, 3 branches of one brand).
  With **Skip chains** on (the default), these aren't saved, and a chain saved earlier is marked
  `chain` so it never goes to Clay. With it off, they're saved and marked "likely chain".

It remembers which pages of each search are done. Running again never pays for them twice. Adding
a phrase or a city adds only the new searches; raising "pages per search" fetches only the extra
pages. Changing the region code or the place type starts every search again.

It never asks Google for reviews or photos. Wania accepted Google's terms risk for storing these
details (D2; `docs/research.md` section 2).

### In the UI

1. **ICPs** page → **Edit** (or **New ICP**) → the **Google Maps** box: search phrases and cities
   (one per line), region code (`us`), an optional Google place type like `veterinary_care`,
   pages per search (1–3), and **Skip chains**.
2. **Find companies** → pick the ICP → tick **Google Maps** (and **Apollo** for both) →
   **Preview (free)**. The preview lists every search, how many requests each can use, the
   month's usage against the cap, and how chains are handled.
3. Tick **Spend up to N Google Maps requests (free up to 1,000 a month)** → **Fetch companies**.
4. **Companies** → Source: Google Maps to see them, with city and the "likely chain" mark.
5. **Enrich with Clay** works the same as for Apollo companies: it goes by website.

### In the code

| File | Job |
|---|---|
| `backend/integrations/google_places.py` | The only Google client. One allowed URL, the key in `X-Goog-Api-Key`, the exact field mask, and plain error messages |
| `backend/stages/source.py` | `google_plan` (every search and how far it got), `_run_google`, `_save_place` (skips and chains) |
| `backend/sources.py` | The Google Maps settings an ICP keeps |
| `backend/db.py` | `places` (every place seen, for chains), `query_progress` (pages done per search), `companies.likely_chain` (schema version 3) |

### How to run

In the app: steps above. In the terminal:

```powershell
.venv\Scripts\outbound source vets_tx --source google_maps          # dry run: every search, free
.venv\Scripts\outbound source vets_tx --source google_maps --live   # spends Google requests
```

### Cost

1 Text Search request per page of up to 20 places. Every request is billed as **Text Search
Enterprise** (the website and phone fields): **the first 1,000 a month are free**, then $35 per
1,000. `config/settings.yaml` caps Google at 1,000 requests a month, so the app stops at the free
allowance. Each request is counted under `google_places requests` (see `outbound check` and the
Pipeline page) before it's sent.

### Common problems

- **"GOOGLE_PLACES_API_KEY isn't set"** — add it to `.env`.
- **"Places API (New) isn't enabled"** — in the Google Cloud Console: APIs & Services → enable
  Places API (New).
- **"billing is off"** — Google needs billing on, even for the free 1,000.
- **"the key isn't allowed to call Places API (New)"** — edit the key's API restrictions and
  tick Places API (New).
- **"only works from certain websites / IP addresses"** — the key's application restriction
  blocks this computer. Set it to None, or add this computer's IP address.
- **429** — Google's rate limit or daily quota. Wait a minute, or check quotas in the Console.
- **"The saved next-page token expired"** — Google no longer accepts the bookmark for that
  search's next page, so the search is marked done. Nothing more is spent on it.
- **Few companies saved** — many local businesses have no website, and chains are skipped. The
  table after a run shows where they went.

---

## Enrich (Clay CSV)

### What it does

Writes the next waiting companies to a CSV for Clay (claiming them in one database update so two
exports never take the same company). After you run the Clay table by hand, reads Clay's CSV back,
matches each person to a company, applies the verify rules, and saves them as leads.

### In the UI

**Enrich with Clay** page, three numbered steps:

1. **Download the file for Clay.** Pick the ICP at the top, then rows: 200 on Clay Free, 50 on a
   trial. **Create the file**, then **Download**.
2. **What to do in Clay.** A short checklist with that ICP's job titles, person locations and
   what to leave out, ready to type into Clay's "Find people" (the long version is
   `docs/clay-table.md`).
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
