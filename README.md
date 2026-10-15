# outbound-pipeline

Cold email pipeline for Arsuno. It targets US companies with 1–20 employees, with two offers: AI
automation, and outsourced front-end developers.

**What works today: finding companies.**
- For each target group ("segment"), it asks Apollo for matching US companies.
- It saves the usable ones and skips:
  - companies with no website;
  - companies not based in the US;
  - companies with too many staff;
  - companies on the do-not-contact list;
  - companies it already has.
- It remembers where it stopped, and never goes over the monthly credit cap.
- You can export everything to a CSV for Excel or Google Sheets.

Next comes finding the right person and email at each company. See [docs/plan.md](docs/plan.md).

- [docs/how-it-works.md](docs/how-it-works.md) explains the code in plain words: what happens on
  each run, and what each file does.
- [docs/research.md](docs/research.md) covers what each tool can do, its costs and the rules, with
  sources.
- [docs/plan.md](docs/plan.md) covers the design, what's built, the build order, and open
  decisions.

---

## One-time setup (Windows)

Run these in a terminal: Cursor's built-in terminal, or PowerShell.

1. **Python 3.11 or newer.** Check with `py --version`. If it's missing, install it from
   python.org and tick "Add python.exe to PATH".
2. **Get the code.** If you already have the folder:
   ```powershell
   cd outbound-pipeline
   git checkout main
   git pull
   ```
   Otherwise:
   ```powershell
   git clone https://github.com/wania4264/outbound-pipeline.git
   cd outbound-pipeline
   ```
3. **Install it** in its own environment:
   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -e .
   ```
4. **Add your Apollo key.** Make a file called `.env` in the project folder, next to `README.md`,
   containing:
   ```
   APOLLO_API_KEY=your-key-here
   ```
   Notepad sometimes saves this as `.env.txt`. The name must be exactly `.env`.
   `.env` is never uploaded to GitHub.
5. **Check it:**
   ```powershell
   .venv\Scripts\outbound check
   ```
   It should say `APOLLO_API_KEY  set`. It never shows the key itself.

**Mac or Linux** is the same, except:
- use `python3 -m venv .venv` to create the environment;
- the tools live in `.venv/bin/` (so `.venv/bin/pip`, `.venv/bin/outbound`).

**Getting updates later:** run `git pull` in the project folder. If you added new dependencies,
run the install line (step 3) again.

---

## Test it

The first test spends **1 Apollo credit** in total. Windows commands are shown.

1. **See the setup:**
   ```powershell
   .venv\Scripts\outbound check
   ```
   This shows your segments, the monthly cap, and credits used so far.

2. **Dry run.** It's free and sends nothing to Apollo; it shows exactly what it *would* send and
   what it would cost:
   ```powershell
   .venv\Scripts\outbound source ai_accounting
   ```

3. **Real run, 1 page** (up to 100 companies, 1 credit):
   ```powershell
   .venv\Scripts\outbound source ai_accounting --live
   ```
   You'll see a summary like:
   ```
   done: 1 page(s), 1 credit(s) (1 of 50 used this month)
     saved (new)          83
     already saved        0
     no website           9
     not US               0
     over 20 staff        5
     do-not-contact       3
     fields filled: domain 91/100, employees 87/100, country 100/100, city 95/100
   Apollo reports about 1,234 matching companies.
   Next run continues at page 2.
   ```

4. **Look at the results in Excel:**
   ```powershell
   .venv\Scripts\outbound export
   ```
   This writes `data\exports\companies_<time>.csv`. Open it in Excel or upload it to Google
   Sheets.

5. **Run the same command again.** It should continue at page 2, not pay for page 1 twice.

6. **Try the do-not-contact list:** pick a domain from your export and run:
   ```powershell
   .venv\Scripts\outbound suppress thatdomain.com --reason "test"
   ```
   Export again, and that company is gone from the CSV.

**Send Claude** the summary from step 3, especially the `fields filled` line. If any field is
0 out of 100, Apollo uses a different field name than expected, and it'll be fixed without
spending more credits. Apollo's original data for every company is saved too.

---

## Everyday commands

| Command | What it does | Cost |
|---|---|---|
| `outbound check` | Config, key status, credits used this month, companies per segment | free |
| `outbound source SEGMENT` | Dry run: shows the Apollo request and its cost | free |
| `outbound source SEGMENT --live` | Fetches 1 page (100 companies) and saves the usable ones | 1 credit |
| `outbound source SEGMENT --live --pages 5` | The same for 5 pages | up to 5 credits |
| `outbound export` | All saved companies to a CSV (`--segment S` for one segment) | free |
| `outbound suppress acme.com --reason "client"` | Never contact this domain (or email). Can't be undone. | free |
| `outbound fields` | Which fields Apollo sent, with counts. Names only, so it's safe to share. | free |

On Windows, put `.venv\Scripts\` in front of each command, for example
`.venv\Scripts\outbound check`.

## Changing who you target

- **Segments** live in `config/segments.yaml`, one block each. You can change the keywords, the
  headcount range (`"1,20"`) or the HQ location, or add a new block. The file explains every
  field. If you change a segment's filters, its next run starts again at page 1.
- **The monthly credit cap** is in `config/settings.yaml` (`caps: apollo: credits: 50`). The
  pipeline stops before going over it. Apollo's website and any other tools using the same
  account spend from the same credits, so keep it below your plan's allowance.

## Where your data is

- **`data/outbound.db`** holds everything saved: companies, the do-not-contact list, credits
  used and progress. It's never uploaded to GitHub. Back it up now and then by copying it
  somewhere private; the do-not-contact list in it matters legally.
- **`data/exports/`** holds the CSVs you export.

## For developers

```bash
pip install -e ".[dev]"
ruff format . && ruff check . && pytest    # all offline; no test needs a real key
```

Code layout, rules and design: `AGENTS.md` and `docs/plan.md`.
