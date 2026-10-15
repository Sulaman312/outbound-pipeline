# Plan: a clean, basic outbound pipeline

Read [research.md](research.md) first. Every number here comes from there.

**Status:** design only. No code yet. The decisions at the bottom are open until Wania marks
them DECIDED.

## Goal

Email the right person at US companies with 1–20 employees about two offers:

1. AI automation.
2. Outsourced front-end developers.

Code does the repeatable parts. Paid tools are used only where they're needed.

## The flow

```
  Apollo API                    Google Maps (only if D2 = yes)
  (companies, 1–20 staff)       (local businesses)
          \                       /
           v                     v
         ┌─────────────────────────┐
         │ companies   (our SQLite)│   one row per domain, ever
         └─────────────────────────┘
                     │  clay export  →  CSV batches, sized to Clay's row limit
                     v
         Clay, by hand: find decision-maker → find work email → check email
                     │  clay import  ←  Clay's CSV export
                     v
         ┌─────────────────────────┐
         │ contacts    (our SQLite)│   send / drop / maybe, from Clay's result
         └─────────────────────────┘
                     │  verify  →  Instantly verification API (maybes only)
                     v
               ready  or  dropped
                     │  campaign apply  →  campaign settings from a YAML file
                     │  push            →  ready contacts into the campaign
                     v
         Instantly sends from the warmed inboxes
                     │  sync  ←  replies, bounces, unsubscribes, finished leads
                     v
         contacts + suppression updated  →  report
```

## Who does what

| Step | Tool | Done by | Why this tool |
|---|---|---|---|
| Find companies | **Open: D10.** Apollo Organization Search (paid plan only) or Clay "Find companies" | code or Clay | Apollo: 1 credit per 100 companies, filters by headcount, returns the domain. Its Free plan has no API access. |
| Find local businesses | Google Places, or Clay's own Google Maps source | code or Clay | Only if D2 is decided |
| Find person, email, check it | Clay | you, by hand (CSV in and out) | Best email-finding coverage. Its API is the $495 plan. |
| Re-check maybes | Instantly verifier | code | 0.25 credits per email, with a catch-all check |
| Campaigns and sending | Instantly | code (API); Instantly sends | Campaigns live as files in the repo. Instantly handles inbox rotation, warmup and scheduling. |
| Who was contacted, opt-outs, report | Our SQLite file | code | Instantly Growth has a contact cap and we clear old leads, so our database is the permanent record |

## One month in numbers (Instantly Growth)

These are **estimates** to plan with. Month 1 replaces them with real numbers.

| Item | Number | Comes from |
|---|---|---|
| Emails Instantly will send | 5,000 a month | Growth plan |
| New people a month | up to about 1,666 | 3-email sequence; only works if finished leads are cleared (1,000 contact cap) |
| Inboxes needed | about 8 | 5,000 ÷ 22 days ≈ 230 a day, at 30 per inbox (D7) |
| Sendable emails Clay must deliver | 1,000–1,600 a month | to fill the above |
| Companies to feed Clay | 2,000–3,200 | assumes about 50% of companies give a sendable email (we'll measure this) |
| Apollo credits | 20–32 | only if D10 = Apollo Basic (about 2,500 a month) |
| Clay finished leads | Free about 75–150, one trial about 750–2,000, Launch 1,900+ | **the real bottleneck (D3)** |
| Instantly checks for maybes | about 300–500 = 75–125 credits | Nano credits ($9, 150 credits) ✔ |
| Positive replies | about 7–30 per 1,000 people | reply-rate benchmarks |

## Data: one SQLite file, five small tables

SQLite is one file, needs no server, and is built into Python. It answers "have we seen this domain
or email before?", which CSV files are bad at.

| Table | Key columns | Rule |
|---|---|---|
| `companies` | id, source, source_id, name, domain, city, state, employees, segment, raw, status, created_at | **Unique domain**: a company enters once, from whichever source finds it first. Status goes `new` → `exported` → `enriched` or `no_contact`. |
| `contacts` | id, company_id, first_name, last_name, title, email, clay_status, verify_status, decision, reason, campaign, instantly_lead_id, state, timestamps | **Unique email.** Decision is `send`, `drop` or `hold`. State goes `ready` → `pushed` → `finished`, `replied`, `bounced` or `unsubscribed`. |
| `batches` | id, file, rows, clay_account, exported_at, imported_at, emails_found | One row per Clay CSV round trip. This gives the real cost per lead for each Clay account or plan. |
| `suppression` | value, kind (email, domain or email_hash), reason, added_at | **Never deleted.** Checked before Clay and again before sending. If someone asks for their data to be deleted, we delete it and store only a one-way hash of their email here, so we never contact them again. |
| `usage` | provider, month, units | Counts API spend so monthly caps are enforced (Google 1,000 requests, Apollo credits, Instantly credits) |

`raw` stores the provider's original response, so a mapping mistake is fixed by re-reading the
data instead of paying for it again. Google Places data is the exception: it's stored only if D2
allows it.

## Commands: one per step

```
outbound check                                 # config valid? which keys set? usage vs caps this month
outbound source apollo --segment S             # shows the query and credit cost; --live runs it
outbound source places --segment S             # only if D2 = yes
outbound clay export --rows 50                 # writes data/clay/out/batch_007.csv (50 rows each)
outbound clay import FILE --account LABEL      # reads Clay's export, creates contacts, applies rules
outbound verify                                # maybes → Instantly verifier (--live)
outbound campaign apply campaigns/X.yaml       # create or update the Instantly campaign (--live)
outbound push --campaign X                     # ready contacts → Instantly (--live)
outbound sync                                  # pull replies, bounces, unsubscribes, finished (--live)
outbound report                                # counts per stage, bounce rate, cost per lead per batch
```

Anything that would call a paid API only shows what it would do, unless you add `--live`.

## Rules the code follows

1. **Dry run by default.** `--live` is needed to spend credits or call a paid API.
2. **Monthly caps are hard stops.** Raising one is your decision, not the code's.
3. **Suppression is checked twice:** before export to Clay, and right before pushing to Instantly.
4. **One company enters once. One email is contacted once.** That holds across all campaigns,
   unless D11 says otherwise.
5. **Before clearing finished leads from Instantly,** their outcome is saved in our database.
6. **Every email has a postal address,** an unsubscribe line and the unsubscribe header.
   Opt-outs sync at least daily, to meet the 48-hour rule.
7. **Each API client only calls the endpoints it's allowed to.** Every client has a fixed list of
   paths and refuses anything else. This matters most when a provider only offers keys that can
   do everything (like an Apollo master key).
8. **Secrets live only in `.env`.** `data/` and lead CSVs are never committed, because they hold
   personal data.
9. **Tests run offline.** HTTP is faked; no test needs a real key.

## Code layout

```
outbound-pipeline/
  pyproject.toml          # deps: httpx, PyYAML; dev: pytest, ruff
  .env.example            # names of the keys, no values
  config/
    settings.yaml         # caps, paths, Clay column names
    segments.yaml         # who we target: offer, source, filters
  campaigns/
    <name>.yaml           # one Instantly campaign each: schedule, steps, settings
  docs/
    research.md
    plan.md
    clay-table.md         # step-by-step recipe to build the Clay table the same way every time
  src/outbound/
    cli.py                # commands only; no logic
    config.py             # load and check YAML and env
    db.py                 # SQLite schema and small query helpers
    http.py               # the one HTTP client: timeouts, retry on 429/5xx, dry-run guard, usage count
    rules.py              # send / drop / hold from statuses; pure functions, easy to test
    clients/
      apollo.py           # Apollo calls → plain dicts
      places.py           # Google Places calls (only if D2)
      instantly.py        # verify, campaigns, leads, emails, blocklist
    steps/
      source.py  clay.py  verify.py  campaign.py  push.py  sync.py  report.py
  tests/                  # offline; fake HTTP; sample CSVs
```

The structure stays basic on purpose:

- Plain functions.
- Standard library first.
- No plugin systems or base classes until a second real use exists.

## Decisions needed from you

Each decision is open until marked DECIDED. The "Suggestion" column is my view; the decision is
yours.

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Which source for which offer? | (a) Apollo for both offers. (b) Apollo for front-end, Google Maps for AI automation at local businesses. (c) Both sources for both. | Depends on D10. Start with one source for month 1, and add local businesses in month 2. |
| D2 | Google Maps, given Google's ban on storing Places data | (a) Use the Places API and accept the risk. (b) Use Clay's own Google Maps source instead. (c) Skip Google Maps. | Decide in month 2. If yes, (b) keeps us off Google's terms, but it uses Clay rows. |
| D3 | Clay: which plan, how many accounts | (a) Free only, about 75–150 a month. (b) Trials rotated: about 750–2,000 each, 50-row tables, terms risk. (c) Launch $185/mo. Also worth one test as email sources: Apollo Basic ($49), Instantly SuperSearch credits. | Month 1: one trial plus the free plan, with every batch recorded. Then compare real cost per lead and pick (b) or (c). |
| D4 | Maybes and catch-alls | Instantly re-checks maybes. If still catch-all or unknown: (a) drop, (b) hold, (c) send a capped share. | Buy Nano credits ($9). Hold in month 1. Test a 10% share in month 2 if bounces stay under 1%. |
| D5 | Role-based emails (`info@`, `contact@`) | (a) Drop. (b) Allow for local businesses only. (c) Allow. | (a) for Apollo leads, since we want a named person. Revisit with D2. |
| D6 | Instantly plan, and clearing finished leads | (a) Growth; code saves outcomes, then deletes finished leads to free space. (b) Hypergrowth $97: no clearing, has webhooks. | (a) |
| D7 | Inboxes | How many are warming? Since when? Daily limit per inbox? | Need your numbers. Default 30 a day each once warmup is past 2 weeks. |
| D8 | CAN-SPAM details | Which postal address (a USPS PO box is fine)? How does the footer say it's an offer? Wording of the unsubscribe line? | You decide the wording; the code makes sure it's in every email. |
| D9 | Sequence shape | Number of steps, gap between them, one offer per campaign or mixed | 3 plain-text emails (day 0, +3, +7). One offer per campaign. Stop on reply. Open and link tracking off. |
| D10 | **Where companies come from** (Apollo Free has no API access; confirmed Oct 2026) | (a) Apollo Basic ($49/mo annual; monthly price higher): full API for companies, people and emails, about 2,500 credits a month. Its emails could replace much of Clay's job. (b) Clay "Find companies": free list building, but 200-row tables on Free; Clay then does companies, people and emails in one table. (c) Apollo website on Free, by hand: CSV export 25 at a time. Slow. (d) Google Places API: see D2. | (a) if about $50–60 a month is OK: sourcing stays automatic, and it may save the $185 Clay Launch plan. Otherwise (b): $0, one tool fewer, but by hand and row-limited. |
| D11 | Re-contact | Contact a person once ever? Once per offer? Again after N months? | Once per offer. Never again after a reply, unsubscribe or bounce. |
| D12 | Where the database lives | One person's laptop, or a shared machine? Backups? | One machine (whoever runs it), with a daily private backup. Never in git. |
| D13 | AI-written first line per email | (a) No, same template for all. (b) Yes: an AI model writes one line from the company data, and a person approves it. The teammate's prototype did this with Claude. | Snooze until sending works end to end. Then test it as a variant against the plain template. |

## Build order

Each step is small, tested, and usable on its own. Each one starts as a dry run, then gets one
tiny live test, and only with your go-ahead.

Each step gets its own instruction file in `docs/steps/`, written once the decisions it needs are
made. A coding agent implements exactly one file per task. Ready so far:
[step 0](steps/step-0-skeleton.md).

| Step | What | Needs |
|---|---|---|
| 0 | Skeleton: pyproject, config loading, SQLite schema, `check`, CI (ruff and pytest). No network. | nothing |
| 1 | Company sourcing (Apollo API or a Clay companies CSV, per D10). First live test is tiny. | D1, D10 |
| 2 | Clay CSV export and import, batches, `docs/clay-table.md`. Built after you make the first Clay table, so we copy its real column names. | D3 |
| 3 | Rules and the Instantly verifier. First live test: 1 email. | D4, D5 |
| 4 | Campaign from a file, and pushing leads. First live test: one campaign left as a draft. | D6–D9 |
| 5 | Sync, suppression, clearing finished leads | D6, D11 |
| 6 | Report | — |
| 7 | Google Places | only if D2 = yes |

## What was binned

The earlier setup was removed from this branch:

- The code in `src/` and its tests.
- `config/`: 3 target profiles, plus AU and UK compliance rules.
- `ARCHITECTURE.md`, the CI workflow and `pyproject.toml`.

`.gitignore` was kept. Everything removed is still in git history: commit `532f68b`, also on
`main`.
