"""Lets `python -m backend` work the same as the `outbound` command."""

from backend.cli import main

raise SystemExit(main())
