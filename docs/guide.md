# Guide

The manual: one section per page of the app, in sidebar order. Each section has the same parts:
What it does / In the app / In the code / Cost / Common problems. Setup and starting the app are
in the [README](../README.md).

---

## Pipeline (and the app itself)

### What it does

The app is a web page on your own computer (`outbound serve`, http://127.0.0.1:8000). Only this
computer can open it; there is no login. Wania's and Ayesha's laptops each run their own copy,
and both use the same Supabase database. Nothing is ever spent without a tick in a "Spend up
to N" box, the monthly caps in `config/settings.yaml` are never exceeded, and nothing on the
do-not-contact list is ever removed.

The Pipeline page is the overview: every stage, built or not, with how many leads are in each
state, plus usage against the caps.

### In the app

**Pipeline**: totals (companies found, waiting for Clay, verified leads, do-not-contact), Apollo
credits and Google Maps requests used this month against their caps, one card per stage (grey =
not built yet), and Setup: which database (host only, never the password), and whether each key
is set.

Two commands live outside the app: `outbound check` prints the same setup and usage in the
terminal, and `outbound backup` writes every table to `data/backups/<UTC time>.json`. Run a
backup before every `git pull`: an update can change the shared database the first time it starts.

### In the code

| File | Job |
|---|---|
| `backend/app.py` | The FastAPI app: `/api` routes, the built screens from `ui/dist`, local-only |
| `backend/api/*.py` | Routes, one file per page; each calls a stage function. `deps.py` opens one database connection per request |
| `backend/overview.py` | Everything the Pipeline page shows |
| `backend/pipeline.py` | `STAGES` and `LEAD_STATES` |
| `backend/db.py` | Engine, schema (with its migrations), every SQL statement |
| `backend/config.py` | `config/settings.yaml` (caps) and `.env` |
| `backend/cli.py` | `serve`, `check`, `backup` |
| `ui/src/api.js`, `App.jsx`, `pages/`, `styles.css` | Every call to the backend; the sidebar; one file per page; all styling |

The API's reference page is at http://127.0.0.1:8000/api/docs while the app runs. To change the
screens: `outbound serve` in one terminal, `npm run dev` in `ui/` in another, then open
http://localhost:5173 (it reloads as you edit).

### Cost

Free.

### Common problems

- **"The app's screens aren't built yet"**: run `npm install` and `npm run build` in `ui/`.
- **"Can't reach the app"**: the terminal running `outbound serve` was closed. Start it again.
- **Port 8000 in use**: `outbound serve --port 8001`, then open http://127.0.0.1:8001.
- **"Config error"**: fix the YAML file the message names, then reload the page.
- **"database schema is version N"**: the database is newer than this code. `git pull`.

---

## ICPs

### What it does

An ICP says **who** we target: a name, the offer, the people to find in Clay (job titles, person
locations, what to leave out) and a target number of leads. It also keeps its own settings for
**each place we find companies**:

| Source | Settings |
|---|---|
| Apollo | Company HQ locations, headcount ranges (like `1,10`), keywords, job-post signal (job titles, posted in the last N days) |
| Google Maps | Search phrases, cities, region code, place type, pages per search, skip chains |

There is no code for a particular niche: vets, dentists or dev agencies are each just an ICP.
ICPs are never deleted, only turned off, because saved companies point at them.

The database started with the 3 pilot ICPs (active) and the 8 old segments (inactive):

| ICP | Campaign | Apollo search | People in Clay |
|---|---|---|---|
| `dev_us_signal` | DEV_US_Signal_v1 | Software/SaaS/dev agencies, 1–10 staff, HQ Texas + New York, a developer job post in the last 60 days | Founder, Co-Founder, CEO, CTO, Owner in TX/NY |
| `dev_us_pain` | DEV_US_Pain_v1 | The same, without the job-post signal | The same |
| `bpa_us_recruit` | BPA_US_Recruit_CaseStudy_v1 | Staffing and recruiting, 11–50 staff, HQ Texas + Florida | Founder, Owner, CEO, President, Managing Director, Director of Operations, Head of Delivery in TX/FL |

A company is saved once, under the first ICP that finds it. So run `dev_us_signal` before
`dev_us_pain`: Pain then skips what Signal already saved.

### In the app

**ICPs**: the list, active first, with companies saved, waiting for Clay, and the target.
**New ICP** opens the form; **Edit** changes one; **Turn off / Turn on** switches it. The form
has who (key, name, offer, country, target, active), the people to find in Clay, and one box per
source. Lists are one per line. Leave a source's box empty if the ICP doesn't use it.

Changing where to find companies for an ICP that already searched shows a yellow warning: the
next run starts that search again, and pays for those pages again. Companies already saved stay.

### In the code

| File | Job |
|---|---|
| `backend/sources.py` | `SOURCES`: each source, its cost, its key and cap, and the settings an ICP keeps for it |
| `backend/icps.py` | Every check (`check`), with plain messages, and saving (`create`, `update`, `set_active`) |
| `backend/seed_icps.py` | The ICPs a new database starts with |
| `ui/src/pages/Icps.jsx`, `IcpForm.jsx` | The list and the form (the source boxes come from `/api/sources`) |

### Cost

Free. Saving an ICP never calls a source.

### Common problems

- **"Key must be 2 to 40 lowercase letters…"**: use something like `vets_us_small`. The key
  can't change later; the name can.
- **An ICP is missing from Find companies**: it's turned off. Turn it on here.
- **"has no Apollo settings" / "has no Google Maps settings"**: fill in at least HQ locations
  and headcount ranges (Apollo), or search phrases and cities (Google Maps).

---

## Find companies: Apollo

### What it does

Asks Apollo's Organization Search for companies matching an ICP's Apollo settings, 100 per page,
and saves the usable ones: one row per website, ever, never a do-not-contact domain, and never
one another ICP or source already saved. It remembers the next page per ICP, so a rerun
continues instead of paying for the same page twice. Changing the ICP's Apollo settings starts
again at page 1.

The job-post signal sends the ICP's job titles as `q_organization_job_titles[]`, and "posted in
the last N days" as `organization_job_posted_at_range` from today minus N days to today.

### In the app

**Find companies** → pick an active ICP → tick **Apollo** → set Apollo pages → **Preview
(free)**. The preview shows the exact filters, the pages, the most it can cost and the month's
credits, and never calls Apollo. Tick **Spend up to N Apollo credits** → **Fetch companies**.
The table after the run shows found, saved, no website, already saved and do-not-contact, and
Apollo's count of matching companies (the pool size). Ticking both Apollo and Google Maps runs
Apollo first, each with its own tick box.

### In the code

`backend/integrations/apollo.py` is the only Apollo client; it only allows Organization Search
and keeps the key in a header. `backend/stages/source.py` checks the ICP and source
(`icp_problem`, `live_problem`), reserves a credit before each page, and saves companies.

### Cost

1 Apollo credit per page (up to 100 companies). The preview is free. The monthly cap is
`caps.apollo.credits` in `config/settings.yaml`.

### Common problems

- **"APOLLO_API_KEY isn't set"**: add it to `.env`.
- **"cap is reached"**: raise `caps.apollo.credits` only when you mean to spend more.
- **403 from Apollo**: the plan or key doesn't allow Organization Search.
- **"already saved"**: those companies belong to an ICP (or source) that found them first.
- **Few results with a job-post signal**: widen its job titles or days (that starts again).

---

## Find companies: Google Maps

### What it does

Searches Google Maps (Places API (New), Text Search) for each of the ICP's **phrases in each of
its cities** ("vet clinic in Austin, TX"), up to 3 pages of 20 places per search (Google stops at
60). It keeps name, website, address, phone and type, never reviews or photos, and saves each
usable place as a company with source `google_places`. It skips and counts:

- **no website**: we need a domain for Clay;
- **closed**: not `OPERATIONAL` (closed for now, for good, or unknown);
- **do-not-contact** and **already saved** (same website or place, from any ICP or Apollo);
- **likely chains**: the same website at 3 or more places. With **Skip chains** on (the
  default) they aren't saved, and one saved earlier is marked `chain` and kept out of Clay.
  With it off, they're saved and marked "likely chain".

Pages already fetched are never paid for again. Adding a phrase or city adds only the new
searches; raising pages per search fetches only the extra pages; changing the region code or
place type starts every search again.

### In the app

**ICPs** → **Edit** → the **Google Maps** box: phrases and cities (one per line), region code
(`us`), an optional place type like `veterinary_care`, pages per search (1–3), Skip chains.
Then **Find companies** → pick the ICP → tick **Google Maps** → **Preview (free)**: it lists
every search, the requests each can use, and the month's usage. Tick **Spend up to N Google Maps
requests (free up to 1,000 a month)** → **Fetch companies**. The table after the run shows found,
saved, no website, closed, already saved, chains and do-not-contact.

### In the code

`backend/integrations/google_places.py` is the only Google client: one allowed URL, the key in
`X-Goog-Api-Key`, the exact field mask, plain error messages. In `backend/stages/source.py`,
`google_plan` lists every search and how far it got, `_run_google` fetches, and `_save_place`
does the skips and chains.

### Cost

1 request per page of up to 20 places, billed as Text Search Enterprise: the first 1,000 a month
are free, then $35 per 1,000. `caps.google_places.requests: 1000` stops at the free allowance.

### Common problems

- **"Places API (New) isn't enabled" / "billing is off" / "the key isn't allowed"**: fix it in
  the Google Cloud Console as the message says. Billing must be on even for the free 1,000.
- **"only works from certain websites / IP addresses"**: the key's application restriction
  blocks this computer.
- **429**: Google's rate limit or daily quota. Wait a minute.
- **"The saved next-page token expired"**: that search is marked done; nothing more is spent.
- **Few companies saved**: many local businesses have no website, and chains are skipped.

---

## Companies

### What it does

Lists every saved company, leaving out do-not-contact domains, with its ICP, source, city and
status: `new`, `exported` (sent to Clay), `enriched` (Clay found an email), `no_contact`
(Clay found nobody), or `chain` (a likely chain kept out of Clay).

### In the app

**Companies**: filter by ICP and source, search by name or website, **Download CSV** (opens in
Excel with accents intact). The table shows the first 500; the CSV has all of them.

### In the code

`backend/api/companies.py` and `backend/exports.py` (`company_rows`, `csv_text`).

### Cost

Free.

### Common problems

- **A company is missing**: it may be on the do-not-contact list, or another ICP saved it first
  (filter by "All ICPs").

---

## Enrich with Clay

### What it does

Sends an ICP's waiting companies to Clay as a CSV, and reads Clay's CSV of people back. Each
company goes into one file only, even if two people export at the same time. On import, each
person is matched to our company (by our `company_id`, then the domain, then the email's domain)
and given a lead state:

| Clay's email check | Lead state | Next |
|---|---|---|
| valid | `verified` | ready for the next stages |
| catch-all or unknown | `needs_check` | re-checked with Instantly's verifier (M3) |
| role address like info@ | `hold` | waits for decision D5 |
| no email, invalid, or do-not-contact | `dropped` | never sent |

A company Clay found nobody for becomes `no_contact`; one with an email becomes `enriched`.
Importing the same file twice is safe: repeats are skipped.

### In the app

**Enrich with Clay** → pick the ICP at the top, then:

1. **Download the file for Clay.** Rows: 200 on Clay Free, 50 on a trial. **Create the file** →
   **Download**. It has `company_id`, `domain`, `name`, `linkedin_url` and `icp`.
2. **In Clay** (step 2 on the page shows this ICP's titles, locations and exclusions):
   1. **Home → Import data → CSV**: pick the file, create a **new table**.
   2. Switch **Auto-run off** (top left of the table) while you set it up.
   3. **Add column → Find people** (may be called "Find people at these companies"). Company:
      the `domain` column. Job titles and person location: the ICP's, as shown on the page.
      Limit: 1 person per company. Leave out the companies the ICP's "Exclude" note names.
   4. In the people table: **Add column → Find work email** (Clay's waterfall; it shows the
      cost per row).
   5. **Add column → Validate email** on the work email column. With ZeroBounce or LeadMagic,
      turn on "only mark safe to send", or catch-alls can show as valid.
   6. Write down your Clay credits. Run **5 rows** first, check them, then run the rest. Write
      the credits down again: the difference is this batch's cost.
   7. **Actions → Export → Download CSV**. No need to rename columns.
3. **Upload Clay's CSV.** The column dropdowns are pre-filled; check them, add the Clay account
   and credits if you know them, **Import**. You see how many leads landed in each state.

Below: the **Batches** table, with companies sent, people back and each state per batch.

### In the code

`backend/stages/enrich.py` (`export_batch`, `detect_columns`, `check_mapping`, `import_rows`)
and `backend/stages/verify.py` (`clay_status`, `decide`). Routes: `backend/api/clay.py`. Page:
`ui/src/pages/Clay.jsx`, `ClayImport.jsx`.

### Cost

Nothing on our side. Clay credits are whatever the table used; entering them on import shows
cost per verified email in the batches table.

### Common problems

- **"Nothing from this ICP is waiting for Clay"**: find more companies first.
- **"Choose a column for: Email"**: pick the work email column in the dropdowns.
- **A batch's Download says the file isn't on this computer**: it was made on the other laptop.
- **Many `needs_check`**: normal for catch-all domains; Instantly re-checks them in M3.

---

## Leads

### What it does

Lists the people Clay found, with their company, ICP, state and why they got it.

### In the app

**Leads**: the chips at the top filter by state (each shows its count and what it means);
**Download CSV**.

### In the code

`backend/api/leads.py`, `backend/exports.py` (`lead_rows`), `ui/src/pages/Leads.jsx`.

### Cost

Free.

### Common problems

- **`hold` on info@ addresses**: intentional until decision D5.

---

## Do-not-contact

### What it does

Domains and emails we never contact. They're skipped when finding companies, left out of Clay
files, and dropped on Clay import. Entries are never removed.

### In the app

**Do-not-contact**: type a domain or email and a reason, **Add**. The list below shows every
entry with its reason and date.

### In the code

`backend/suppression.py` (`suppress`), `backend/api/suppression.py` (there is no delete route).

### Cost

Free.

### Common problems

- **"isn't a valid domain or email"**: type `acme.com` or `jane@acme.com`.
