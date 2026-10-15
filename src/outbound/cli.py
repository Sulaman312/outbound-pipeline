"""Command line entry point.

    outbound check                                  validate config, show which keys are set
    outbound source --icp A --country US            dry run: print the requests, call nothing
    outbound source --icp A --country US --live     call the APIs and store leads
    outbound export --icp A --stage sourced         CSV for review or a manual import
    outbound suppress --domain acme.com --reason "asked to stop"
    outbound stats

Every command that can spend money is a dry run unless --live is given.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from outbound.config import Config, load_config
from outbound.errors import PipelineError
from outbound.export import write_csv
from outbound.http import current_month
from outbound.models import Stage
from outbound.sources import SOURCES, build_source
from outbound.stages.sourcing import SourcingStage
from outbound.store import Store

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config"


def load_dotenv(path: Path) -> None:
    """Read KEY=value lines into the environment. Variables already set win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(DEFAULT_CONFIG.parent / ".env")
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
        store = Store(config.settings.database)
        try:
            return args.func(args, config, store)
        finally:
            store.close()
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="outbound")
    p.add_argument(
        "--config",
        default=os.environ.get("OUTBOUND_CONFIG", DEFAULT_CONFIG),
        help="config folder (default: %(default)s)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("check", help="validate config and show which API keys are set")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("source", help="stage 1: find companies and people")
    s.add_argument("--icp", required=True)
    s.add_argument("--country", required=True)
    s.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCES),
        help="limit to these sources (repeatable); default: all enabled in the ICP",
    )
    s.add_argument("--live", action="store_true", help="actually call the APIs")
    s.set_defaults(func=cmd_source)

    s = sub.add_parser("export", help="write leads to CSV")
    s.add_argument("--icp")
    s.add_argument("--country")
    s.add_argument("--stage", choices=[st.value for st in Stage])
    s.add_argument("--out", type=Path)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("suppress", help="never contact an email or domain again")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--email")
    g.add_argument("--domain")
    s.add_argument("--reason")
    s.set_defaults(func=cmd_suppress)

    s = sub.add_parser("stats", help="lead counts and this month's API usage")
    s.set_defaults(func=cmd_stats)
    return p


def cmd_check(args, config: Config, store: Store) -> int:
    print(f"config: {config.root}")
    print(f"database: {config.settings.database}")
    for icp in config.icps.values():
        enabled = [n for n, o in icp.sources.items() if o.get("enabled", True)]
        print(
            f"ICP {icp.id} ({icp.name}): countries {', '.join(icp.countries)}; "
            f"sources {', '.join(enabled) or 'none'}"
        )
        for name in icp.sources:
            if name not in SOURCES:
                print(f"  ! unknown source '{name}'")
                continue
            SOURCES[name].Options(**icp.sources[name])  # raises on a bad option
    for name, provider in config.settings.providers.items():
        state = "set" if os.environ.get(provider.api_key_env) else "NOT set"
        print(f"{name}: {provider.api_key_env} {state}")
    return 0


def cmd_source(args, config: Config, store: Store) -> int:
    names = args.source or [n for n in SOURCES if n in config.icp(args.icp).sources]
    sources = [build_source(n, config, store, live=args.live) for n in names]
    stage = SourcingStage(config, store, sources)

    if not args.live:
        result = stage.plan(args.icp, args.country)
        print(f"DRY RUN for ICP {result.icp} in {result.country}. Nothing was called.")
        for src, plans in result.plans.items():
            client = next(s.client for s in sources if s.name == src)
            total = sum(pl.max_requests for pl in plans)
            left = client.remaining_budget()
            budget = f"; {left} left of this month's cap" if left is not None else ""
            print(f"\n{src}: up to {total} request(s){budget}")
            for pl in plans:
                print(f"  - {pl.description}")
                print(f"    {pl.body}")
        print("\nRe-run with --live to make these calls.")
        return 0

    result = stage.run(args.icp, args.country)
    print(f"ICP {result.icp} in {result.country}: {dict(result.counts)}")
    for src, err in result.errors.items():
        print(f"  {src} stopped early: {err}")
    return 1 if result.errors else 0


def cmd_export(args, config: Config, store: Store) -> int:
    stage = Stage(args.stage) if args.stage else None
    out = args.out or config.settings.exports_dir / (
        "_".join(filter(None, ["leads", args.icp, args.country, args.stage])) + ".csv"
    )
    n = write_csv(store.leads(icp=args.icp, country=args.country, stage=stage), out)
    print(f"wrote {n} leads to {out}")
    return 0


def cmd_suppress(args, config: Config, store: Store) -> int:
    kind, value = ("email", args.email) if args.email else ("domain", args.domain)
    store.suppress(kind, value, args.reason)
    print(f"suppressed {kind} {value}")
    return 0


def cmd_stats(args, config: Config, store: Store) -> int:
    counts = Counter((lead.icp, lead.country, lead.stage.value) for lead in store.leads())
    for (icp, country, stage), n in sorted(counts.items()):
        print(f"ICP {icp} {country} {stage}: {n}")
    month = current_month()
    for name, provider in config.settings.providers.items():
        cap = provider.monthly_request_cap
        print(
            f"{name} requests in {month}: {store.usage(name, month)}" + (f" / {cap}" if cap else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
