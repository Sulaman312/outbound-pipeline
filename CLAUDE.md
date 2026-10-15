# CLAUDE.md

The project rules live in AGENTS.md so that Cursor and Claude Code follow the same file.

@AGENTS.md

Before every push to `main`:

- Nothing beyond the step being built.
- Tests are offline, and `ruff format . && ruff check . && pytest` all pass.
- README and `docs/plan.md` match the code.
