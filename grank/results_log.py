"""Append-only results log for GRank rank checks.

Each run appends one block to a log file (default: rankings.log) so you
build a history of how each term's Google page number moves over time.

Only terms that were found (or errored) are recorded; "not found" terms
are omitted to keep the log focused. The header reports totals.

Format per run (one term per line):

    ===============================================================
    2026-09-15 13:16  |  target=risk-runway.com  |  60 terms checked, 3 found
    ---------------------------------------------------------------
    risk runway automation          p1 (#5) https://risk-runway.com/
    reduce E&O exposure data entry  p1 (#7) https://risk-runway.com/blog/...
    ===============================================================

- "p<N> (#<pos>) <url>" means found on Google results page N, at overall
  position <pos>, at the given matched URL.
- "ERR" means the lookup errored for that term (see console logs).
- Terms not found are not listed.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Iterable

from grank.search_client import RankResult

DEFAULT_LOG_PATH = "rankings.log"


def format_status(result: RankResult) -> str:
    """Render just the outcome part for a term.

    - Found:     'p<N> (#<position>) <matched-url>'
    - Not found: 'NF'
    - Error:     'ERR'
    """
    if result.error:
        return "ERR"
    if result.found and result.page is not None:
        detail = f"p{result.page}"
        if result.position is not None:
            detail += f" (#{result.position})"
        if result.url:
            detail += f" {result.url}"
        return detail
    return "NF"


def format_entry(result: RankResult) -> str:
    """Render one term's outcome as 'term: <status>' (single line)."""
    return f"{result.term}: {format_status(result)}"


def format_run(target: str, results: list[RankResult], when: _dt.datetime | None = None) -> str:
    """Build the full appended block for one run, one term per line.

    Only terms that were found (or errored) are listed; "not found" terms
    are omitted to keep the log focused. The header still reports the total
    number of terms checked and how many were found.
    """
    when = when or _dt.datetime.now()
    stamp = when.strftime("%Y-%m-%d %H:%M")
    bar = "=" * 63

    # Keep only meaningful entries: found on a page, or errored.
    shown = [r for r in results if r.found or r.error]
    found_count = sum(1 for r in results if r.found)
    header = (
        f"{stamp}  |  target={target}  |  "
        f"{len(results)} terms checked, {found_count} found"
    )

    if shown:
        # Align the status column so results are easy to scan down the page.
        term_width = max(len(r.term) for r in shown)
        lines = [f"{r.term.ljust(term_width)}   {format_status(r)}" for r in shown]
        body = "\n".join(lines)
    else:
        body = "(no terms found)"

    return f"{bar}\n{header}\n{'-' * 63}\n{body}\n{bar}\n"


def append_run(
    target: str,
    results: list[RankResult],
    path: str = DEFAULT_LOG_PATH,
    when: _dt.datetime | None = None,
) -> str:
    """Append one run's block to ``path`` (created if missing). Returns path."""
    block = format_run(target, results, when=when)
    # Open in append mode; a leading newline keeps runs visually separated.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n" + block)
    return os.path.abspath(path)
