# Step 0: Project skeleton

**Paste this into Cursor (Agent mode):**

> Read `AGENTS.md`, `docs/plan.md` and `docs/steps/step-0-skeleton.md`. Implement exactly
> `step-0-skeleton.md`, nothing more, on a new branch `build/step-0`. If anything is unclear or
> seems to need a decision, stop and ask me instead of choosing. When done, run every check under
> "Done when" and show me the output.

## Goal

An installable Python package `outbound` with:

- one working command, `outbound check`;
- a config loader;
- a SQLite database with the first three tables.

**No network code at all in this step.**

## Files

Create:

```
pyproject.toml
.env.example
.github/workflows/ci.yml
config/settings.yaml
src/outbound/__init__.py
src/outbound/config.py
src/outbound/db.py
src/outbound/cli.py
tests/conftest.py
tests/test_config.py
tests/test_db.py
tests/test_cli.py
```

Edit: `README.md` (add the Setup section at the end).

---

## 1. `pyproject.toml`

- **Build:** setuptools, `src/` layout. Package `outbound`, version `0.1.0`,
  `requires-python = ">=3.11"`.
- **Dependencies:** `PyYAML>=6.0` only.
- **Dev extras:** `pytest>=8`, `ruff>=0.6`.
- **Script:** `outbound = "outbound.cli:main"`.
- **pytest:** `testpaths = ["tests"]`.
- **ruff:** `line-length = 100`, `target-version = "py311"`, lint
  `select = ["E", "F", "I", "B", "UP"]`, `ignore = ["E501"]`.

## 2. `.env.example`

```
# Copy to .env and fill in. Never commit .env.
APOLLO_API_KEY=
```

## 3. `config/settings.yaml`

```yaml
# Paths are relative to the project root.
database: data/outbound.db

# Monthly hard caps per provider. The code refuses to go over them.
# Set by Wania. Don't raise without a go-ahead.
caps:
  apollo:
    credits: 75   # Apollo free plan allowance (about 900 a year)
```

## 4. `src/outbound/config.py`

Docstring: loads `config/settings.yaml` and `.env`; nothing else.

**`class ConfigError(Exception)`**

**`Settings`** — a frozen dataclass:

```python
@dataclass(frozen=True)
class Settings:
    root: Path                         # project root (absolute)
    database: Path                     # absolute path to the SQLite file
    caps: dict[str, dict[str, int]]    # provider -> unit -> monthly cap
```

**`load_settings(root: Path) -> Settings`** reads `root / "config" / "settings.yaml"`.

- `database` is resolved against `root`.
- Raise `ConfigError` with a message that names the file and the key when:
  - the file is missing, or isn't a YAML mapping;
  - `database` is missing, or isn't a non-empty string;
  - `caps` is missing, or isn't `{provider: {unit: int}}` with every int ≥ 0;
  - there's any top-level key other than `database` and `caps` (catches typos).

**`load_env(path: Path) -> None`**

- If the file exists, read `KEY=VALUE` lines into `os.environ`.
- Never override a variable that is already set.
- Skip blank lines and lines starting with `#`.
- Strip surrounding single or double quotes from the value.
- No `python-dotenv`.

**`KNOWN_KEYS: tuple[str, ...] = ("APOLLO_API_KEY",)`** — the env var names the pipeline uses.
Later steps add to it.

**`key_status() -> dict[str, bool]`** — for each name in `KNOWN_KEYS`, whether it's set and
non-empty. It returns booleans only, never values.

## 5. `src/outbound/db.py`

Docstring: SQLite connection, schema, and small helpers.

**`SCHEMA_VERSION = 1`**

**`SCHEMA`** — exactly this SQL:

```sql
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY,
    domain      TEXT NOT NULL UNIQUE,       -- normalized: lowercase, no scheme, no www, no path
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,              -- 'apollo' (later: 'google_places')
    source_id   TEXT NOT NULL,              -- the provider's own id for this company
    segment     TEXT NOT NULL,              -- key from config/segments.yaml (step 1)
    city        TEXT,
    state       TEXT,
    employees   INTEGER,                    -- as reported by the source; NULL if unknown
    raw         TEXT,                       -- the provider's JSON for this record
    status      TEXT NOT NULL DEFAULT 'new',-- new | exported | enriched | no_contact
    created_at  TEXT NOT NULL,              -- UTC, e.g. 2026-10-15T09:30:00Z
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS suppression (
    value     TEXT PRIMARY KEY,             -- lowercase email, domain, or sha256 hex of an email
    kind      TEXT NOT NULL,                -- email | domain | email_hash
    reason    TEXT NOT NULL,
    added_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    provider  TEXT NOT NULL,                -- e.g. apollo
    unit      TEXT NOT NULL,                -- e.g. credits, requests
    month     TEXT NOT NULL,                -- YYYY-MM, UTC
    amount    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, unit, month)
);
```

**`connect(path: Path) -> sqlite3.Connection`**

- Create the parent folder if it's missing.
- Set `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`.
- Call `init_schema`, then return the connection.

**`init_schema(conn) -> None`**

- Run `SCHEMA`.
- If `PRAGMA user_version` is 0, set it to `SCHEMA_VERSION`.
- If it's greater than `SCHEMA_VERSION`, raise `RuntimeError`: the database was made by newer
  code.

**Small helpers:**

- **`now_utc() -> str`** — like `2026-10-15T09:30:00Z` (seconds, `Z` suffix).
- **`current_month() -> str`** — like `2026-10`, UTC.
- **`usage_this_month(conn, provider: str, unit: str) -> int`** — returns 0 if there's no row.
- **`add_usage(conn, provider: str, unit: str, amount: int) -> None`** — upserts into the current
  month and commits.

## 6. `src/outbound/cli.py`

Docstring: command-line entry point; parses arguments and calls functions, with no logic of its
own.

**`main(argv: list[str] | None = None) -> int`**, built with `argparse`:

- Global option `--root PATH`, defaulting to the current directory.
- Subcommands are required. For now there's only one: `check`.

**`check` does, in order:**

1. `load_env(root / ".env")`.
2. `load_settings(root)`. On `ConfigError`, print `config error: <message>` to stderr and return
   `2`.
3. `connect(settings.database)`. This creates the file if it's missing.
4. Print exactly this layout. Show paths relative to the root, or as an absolute path if they're
   outside it. List caps one line per provider and unit, sorted.

```
config:   ok (config/settings.yaml)
database: data/outbound.db
keys:
  APOLLO_API_KEY  not set
caps this month (2026-10):
  apollo credits  0 / 75
```

5. Return `0`.

A key shows as `set` or `not set`. **Never print a key's value.**

## 7. Tests

All offline. Use `tmp_path` and `monkeypatch`; never touch the real `data/` or `.env`.

**`conftest.py`**

- Fixture `project(tmp_path)`: writes a minimal valid `config/settings.yaml` (with `apollo:
  credits: 75`) and returns the root `Path`.
- Fixture that runs `monkeypatch.delenv("APOLLO_API_KEY", raising=False)`.

**`test_config.py`**

- A valid file loads, and `database` resolves under the root.
- A missing file raises `ConfigError` whose message contains `settings.yaml`.
- An unknown top-level key raises `ConfigError` naming that key.
- A cap of `-1`, or `"ten"`, raises `ConfigError`.
- `load_env`:
  - sets missing variables;
  - doesn't override existing ones;
  - skips comments and blank lines;
  - strips quotes.
- `key_status` returns only booleans.

**`test_db.py`**

- `connect` creates the file and its parent folder.
- All three tables exist, and `user_version == 1`.
- Calling `init_schema` twice is fine.
- A duplicate `companies.domain` raises `sqlite3.IntegrityError`.
- `add_usage` adds up across calls; `usage_this_month` is 0 when there's no row.

**`test_cli.py`**

- `main(["--root", str(project), "check"])` returns 0 and prints `not set` for the key.
- With `APOLLO_API_KEY=secret-123` in the env, the output shows `set`, and `secret-123` appears
  **nowhere** in stdout or stderr.
- A broken `settings.yaml` makes it return 2, with `config error` in stderr.

## 8. `.github/workflows/ci.yml`

- Runs on push and on pull_request, on `ubuntu-latest` with Python 3.11.
- Steps: `pip install -e ".[dev]"`, then `ruff check .`, then `ruff format --check .`, then
  `pytest`.

## 9. `README.md`: add a Setup section

````
## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # then fill in the keys you have
outbound check
```

Checks: `pytest && ruff check . && ruff format --check .`
````

## Do not

- Add network code, an HTTP client, Apollo code, `segments.yaml`, or any other table. Those come in
  later steps.
- Add dependencies beyond PyYAML, pytest and ruff.
- Add base classes, registries, logging setup, or a class hierarchy for settings.
- Print or log any secret's value.
- Commit `.env` or `data/`.

## Done when

- `pip install -e ".[dev]"` works in a fresh venv.
- `ruff check .` and `ruff format --check .` both pass.
- `pytest` passes with no network.
- `outbound check` in the repo prints the block above (the key may show `not set`).
- `git status` shows no `data/` or `.env`.
