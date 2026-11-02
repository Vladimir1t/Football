"""Command line: python -m fdq {generate,run,check}.

Exit codes (for cron / an orchestrator): 0 ok, 1 error-level checks failed
with --strict, 2 usage or pipeline error.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from . import pipeline
from .config import load_settings
from .dq import summary_json
from .generate import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fdq", description="Football data ETL + data quality")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="write synthetic provider deliveries with planted problems")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--matches", type=int, default=10)

    for name, help_text in [("run", "extract + transform + marts + checks + report"),
                            ("check", "only run the data quality checks on the current database")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--as-of", type=date.fromisoformat, help="'today' for freshness checks (YYYY-MM-DD)")
        p.add_argument("--strict", action="store_true", help="exit 1 if any error-level check fails")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    settings = load_settings()

    if args.cmd == "generate":
        manifest = generate(settings.raw_dir, seed=args.seed, n_matches=args.matches)
        print(f"wrote {settings.raw_dir}; known data issues: {len(manifest['issues'])} (see _manifest.json)")
        return 0

    as_of = args.as_of or pipeline.default_as_of(settings.raw_dir)
    try:
        summary = pipeline.run(settings, as_of) if args.cmd == "run" else pipeline.check_only(settings, as_of)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(summary_json(summary))
    print(f"report: {settings.reports_dir / 'dq_report.md'}")
    return 1 if args.strict and summary.errors else 0


if __name__ == "__main__":
    sys.exit(main())
