"""GRank command-line runner.

Runs a list of search terms against a target domain via the Serper.dev
Google Search API, prints a results table, and appends a one-line-per-run
summary to a persistent log file.

Usage:
    python check.py --target risk-runway.com --terms terms.txt
    python check.py -t risk-runway.com -f terms.txt --log rankings.log

Terms file: one term per line; blank lines and lines starting with '#'
are ignored.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from grank.logging_config import get_logger
from grank.results_log import DEFAULT_LOG_PATH, append_run, format_entry
from grank.search_client import SearchError, parse_terms
from grank.serper_client import DEFAULT_MAX_PAGES, SerperSearchClient

load_dotenv()
logger = get_logger("grank.cli")

_PLACEHOLDER_KEY = "your_serper_api_key_here"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def read_terms_file(path: str) -> list[str]:
    """Read terms from a file, ignoring blanks and '#' comment lines."""
    with open(path, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh]
    kept = [ln for ln in lines if ln and not ln.startswith("#")]
    return parse_terms("\n".join(kept))


def build_client() -> SerperSearchClient:
    key = (os.environ.get("SERPER_API_KEY") or "").strip()
    if key == _PLACEHOLDER_KEY:
        key = ""
    return SerperSearchClient(
        api_key=key,
        max_pages=_int_env("MAX_PAGES", DEFAULT_MAX_PAGES),
        gl=os.environ.get("SEARCH_COUNTRY") or None,
        hl=os.environ.get("SEARCH_LANGUAGE") or None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Google rankings for a list of terms.")
    parser.add_argument("-t", "--target", required=True, help="Target domain, e.g. risk-runway.com")
    parser.add_argument("-f", "--terms", default="terms.txt", help="Path to terms file (default: terms.txt)")
    parser.add_argument("--log", default=DEFAULT_LOG_PATH, help=f"Append-log path (default: {DEFAULT_LOG_PATH})")
    parser.add_argument("--no-log", action="store_true", help="Don't append to the results log")
    args = parser.parse_args(argv)

    try:
        terms = read_terms_file(args.terms)
    except OSError as exc:
        print(f"Could not read terms file {args.terms!r}: {exc}", file=sys.stderr)
        return 2
    if not terms:
        print(f"No terms found in {args.terms!r}.", file=sys.stderr)
        return 2

    try:
        client = build_client()
    except SearchError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print("Set SERPER_API_KEY in your .env (get a key at https://serper.dev).", file=sys.stderr)
        return 2

    print(f"Checking {len(terms)} term(s) against {args.target} ...\n")
    results = client.find_ranks(terms, args.target)

    # Console table
    width = max(len(r.term) for r in results)
    for r in results:
        if r.error:
            status = "ERROR"
        elif r.found:
            status = f"page {r.page}  (#{r.position})"
        else:
            status = "not found"
        print(f"  {r.term.ljust(width)}  {status}")

    found = sum(1 for r in results if r.found)
    print(f"\nDone: {len(results)} checked, {found} found on a results page.")

    if not args.no_log:
        path = append_run(args.target, results, path=args.log)
        print(f"Appended run to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
