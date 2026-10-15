# How the code works, in plain words

## The whole idea

Ask Apollo for companies that match a segment, keep the usable ones, and save them in one local
file. Then you can export them to a CSV.

## What happens when you run `outbound source ai_accounting --live`

1. **`cli.py`** reads what you typed: the command `source`, the segment `ai_accounting`, and
   `--live`.
2. **`config.py`** loads three files:
   - `config/settings.yaml`: where the database is, and the monthly credit cap;
   - `config/segments.yaml`: what "ai_accounting" means (keywords, headcount, HQ location);
   - `.env`: your Apollo key.

   If a file has a mistake, it stops here and tells you which file and which line.
3. **`db.py`** opens `data/outbound.db`, creating it the first time.
4. **`steps/source.py`** asks the database two questions:
   - Which page is next for this segment? (So it never pays for the same page twice.)
   - Is there room under the monthly cap? If not, it stops before spending anything.
5. **`clients/apollo.py`** builds the request from the segment's filters and sends it to
   Apollo:
   - It sends it through **`http.py`**, which waits and tries again if Apollo says "too busy".
   - The key goes in a header, never in the web address.
   - This file refuses to call any Apollo endpoint except company search.
6. **For each company Apollo sends back,** `source.py`:
   - turns the website into a clean domain (`https://www.Acme.com/about` becomes `acme.com`),
     using **`normalize.py`**;
   - skips it if there's no website, it's not in the US, it's over 20 staff, or it's on your
     do-not-contact list;
   - saves the rest. If the domain is already saved, the database ignores it (domains are
     unique).
7. **It saves three things in one go:** "1 credit used", the new companies, and "next time start
   at page 2". If anything fails halfway, none of it is saved, so the numbers never drift.
8. **It prints the summary** you saw.

A dry run (no `--live`) only does steps 1–4 and prints what it *would* send. It never touches
the internet.

## Each file

| File | Its one job | You'd touch it when... |
|---|---|---|
| `config/segments.yaml` | Who to look for | Changing targets. No code needed. |
| `config/settings.yaml` | Monthly credit cap, database location | Changing the budget |
| `.env` | Your API key (stays on your computer) | Changing the key |
| `src/outbound/cli.py` | Turns typed commands into function calls; no logic | Adding a command |
| `src/outbound/config.py` | Loads and checks the config files | Adding a setting |
| `src/outbound/db.py` | The database: tables, and every query | Storing something new |
| `src/outbound/http.py` | Sends web requests, retries when busy | Rarely |
| `src/outbound/normalize.py` | Cleans websites and emails | Rarely |
| `src/outbound/clients/apollo.py` | Talks to Apollo, and only company search | Apollo changes its API |
| `src/outbound/steps/source.py` | The sourcing step described above | Changing what counts as usable |
| `src/outbound/steps/export.py` | Writes the CSV | Changing the CSV columns |
| `src/outbound/steps/suppress.py` | Adds to the do-not-contact list | Rarely |
| `src/outbound/steps/fields.py` | Lists which fields Apollo sent (names only) | Checking the data |
| `tests/` | Checks every file above with a fake Apollo | Any change |

## What's in the database (`data/outbound.db`)

| Table | What it holds |
|---|---|
| `companies` | One row per company: domain, name, segment, LinkedIn, Apollo's original record, and status (`new` until the next step uses it) |
| `suppression` | The do-not-contact list. Nothing is ever deleted from it. |
| `usage` | Credits spent per month, which is how the cap works |
| `sourcing_progress` | The next page for each segment, and whether it's used up |

To look inside without code, install the free app **DB Browser for SQLite**, open
`data/outbound.db`, and click "Browse Data". Close it before running a command.

## Safety built in

- **Nothing spends credits** unless you add `--live`.
- **The monthly cap** stops runs before going over.
- **The key** is never printed and never put in a web address.
- **The Apollo code** can only call company search, even though the key can do more.
- **Tests** use a fake Apollo, so running them costs nothing and needs no key.
