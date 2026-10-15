"""Lets `python -m outbound` work the same as the `outbound` command."""

from outbound.cli import main

raise SystemExit(main())
