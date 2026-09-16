"""Append-only results log for GRank rank checks.

Each run appends one block to a log file (default: rankings.log) so you
build a history of how each term's Google page number moves over time.

Format per run:

    ===============================================================
    2026-09-15 13:16  |  target=risk-runway.com  |  59 terms
    ---------------------------------------------------------------
    riskrunway: p1 / risk runway automation: p1 / risk-runway: NF / ...
    ===============================================================

- "p<N>" means the target was found on Google results page N.
- "NF"   means not found within the pages searched.
- "ERR"  means the lookup errored for that term (see console logs).
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Iterable

from grank.search_client import RankResult

DEFAULT_LOG_PATH = "rankings.log"


def format_entry(result: RankResult) -> str:
    """Render one term's outcome as 'term: pN' / 'term: NF' / 'term: ERR'."""
    if result.error:
        code = "ERR"
    elif result.found and result.page is not None:
        code = f"p{result.page}"
    else:
        code = "NF"
    return f"{result.term}: {code}"


def format_run(target: str, results: list[RankResult], when: _dt.datetime | None = None) -> str:
    """Build the full appended block for one run."""
    when = when or _dt.datetime.now()
    stamp = when.strftime("%Y-%m-%d %H:%M")
    entries = " / ".join(format_entry(r) for r in results)
    bar = "=" * 63
    header = f"{stamp}  |  target={target}  |  {len(results)} terms"
    return f"{bar}\n{header}\n{'-' * 63}\n{entries}\n{bar}\n"


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
