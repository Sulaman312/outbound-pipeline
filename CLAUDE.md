# CLAUDE.md

Guidance for Claude Code working in this repo. Read ARCHITECTURE.md before changing anything structural.

## What this is

Arsuno's cold outbound pipeline (Section 2 of the outbound system, owned by Wania). A lead is one
company we might email for one ICP. It moves through fixed stages:
SOURCED → ENRICHED → VERIFIED → QUEUED (or DROPPED with a reason).

Status: stage 1 (sourcing: Apollo People API Search + Google Places Text Search) is built and tested
offline. Stages 2–8 are designed in ARCHITECTURE.md §2 but not built.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # offline, fake APIs only
ruff check . && ruff format --check .   # CI runs both plus pytest
outbound check            # validates config/, shows which API keys are set
```

## Architecture rules (keep these)

- `src/outbound/models.py` (`Lead`) is the data contract. Stages only add their own fields; never
  overwrite upstream fields.
- One stage = one module in `src/outbound/stages/`. It reads leads at its input stage from the
  store and writes them at the next stage. Stages never call each other.
- Every outside tool sits behind an adapter interface (`LeadSource`, `EmailFinder`, `Verifier`,
  `Sender`, `Crm`, `Reporter`), chosen by name in config. Add a provider = one adapter class + one
  registry line (see `src/outbound/sources/__init__.py`). Don't put provider logic in stages.
- All HTTP goes through `src/outbound/http.py` (retries, pacing, monthly caps). Don't create
  another client.
- Store the raw provider payload (`raw_records`) so a wrong mapping is fixed by re-reading, not
  re-paying.
- What changes often lives in `config/` (ICPs, countries, budgets), not in code.

## Safety rules (non-negotiable)

- Dry run by default. Anything that calls an API needs `--live`. A dry run must not reach the network.
- Never run `--live` or anything that spends credits or money without Wania's explicit go-ahead.
- Monthly caps in `config/settings.yaml` are hard limits (Google Places: 1,000 free requests). Don't
  raise them without a go-ahead to pay.
- Secrets only in environment variables / `.env` (gitignored). Config names the env var, never the
  key. Never commit `.env`, keys, the `data/` folder, or lead exports (they hold personal data).
- Suppression is checked at sourcing and again before sending; nothing is ever deleted from it.
- Compliance per country (`config/countries.yaml`): AU needs `email_source_url` for every email
  (Spam Act inferred consent); UK limited companies only.

## Conventions

- Python 3.11+, type hints, pydantic models, small modules with a docstring at the top.
- Tests are offline only: use `FakeApi` from `tests/conftest.py`. No test may need a real key.
- Every new adapter/stage ships with tests in `tests/`.
- Ruff config is in `pyproject.toml`; run `ruff format .` before committing.
- Build only what the design calls for. Don't add features, providers, or stages that aren't decided.

## Decisions and open questions

Decisions are made outside this repo, in the Claude project "Lead generation swiss":
- Decisions file: `section2_decisions.md` in that project (status per part, PROPOSED / DECIDED).
  As of 2026-10-14: 1 Lead sources DECIDED; 2 Clay enrichment PROPOSED; 3 Bounce check DECIDED
  (Instantly verification API); 4 Instantly send + track PROPOSED; 5 Pipedrive + daily report
  PROPOSED.
- Build plan: Miro board "section 2 (how to send)", frame "Final pipeline design".
- Known conflicts with the Section 1 playbook (owned by Ayesha Noor): HubSpot vs Pipedrive,
  MillionVerifier vs Instantly verify, opens tracking on vs off, markets UK/US/AU vs AU/US state.
  ARCHITECTURE.md §6 shows where each lands (usually: pick an adapter in config).
- Open checks: ARCHITECTURE.md §7 (Apollo free search may omit domain / obfuscate last names;
  Apollo industry names must match its UI list).

If a task needs a decision that is PROPOSED or not covered (which provider, a paid plan, a
compliance rule, a schema change to `Lead`), stop and ask Wania to settle it in the project. Don't
pick one in code. Write the question down in the PR or in ARCHITECTURE.md §7 so it isn't lost.
