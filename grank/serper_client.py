"""Client for the Serper.dev Google Search API with rank detection.

Serper returns real, whole-web Google organic results as JSON. This
client pages through those results for each term and reports where a
target domain first appears: its absolute position and which page of
results that maps to (10 results/page, matching Google.com numbering).

API contract (https://serper.dev):
    POST https://google.serper.dev/search
    Header: X-API-KEY: <key>
    Body:   {"q": <term>, "num": 10, "page": <1-based>, "gl": ..., "hl": ...}
    Response: {"organic": [{"title", "link", "snippet", "position"}, ...]}
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from grank.logging_config import get_logger
from grank.search_client import (
    RankResult,
    SearchError,
    _link_matches_target,
    normalize_domain,
)

logger = get_logger("grank.serper")

SERPER_ENDPOINT = "https://google.serper.dev/search"

# Serper serves 10 organic results per page and supports paging via "page".
RESULTS_PER_PAGE = 10
# How deep to look before giving up. 10 pages = top 100 results, which is
# plenty for a rank checker (results past page 10 are rarely meaningful).
DEFAULT_MAX_PAGES = 10

# When a term isn't found, log this many top-ranking competitors at DEBUG.
TOP_COMPETITORS_TO_LOG = 5


class SerperSearchClient:
    """Rank checker backed by the Serper.dev Google Search API."""

    def __init__(
        self,
        api_key: str,
        max_pages: int = DEFAULT_MAX_PAGES,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: float = 20.0,
    ) -> None:
        if not api_key:
            raise SearchError("Missing SERPER_API_KEY.")

        self.api_key = api_key
        self.max_pages = max(1, max_pages)
        self.gl = gl  # optional country code, e.g. "us", "gb"
        self.hl = hl  # optional UI language, e.g. "en"
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request_page(self, term: str, page: int) -> list[dict]:
        """Fetch one page (1-based) of organic results for ``term``."""
        body: dict = {"q": term, "num": RESULTS_PER_PAGE, "page": page}
        if self.gl:
            body["gl"] = self.gl
        if self.hl:
            body["hl"] = self.hl

        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

        logger.debug("POST Serper  term=%r  page=%d", term, page)
        started = time.monotonic()
        try:
            resp = self.session.post(
                SERPER_ENDPOINT, json=body, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.error("Network error for term=%r page=%d: %s", term, page, exc)
            raise SearchError(f"Network error contacting Serper: {exc}") from exc

        elapsed_ms = (time.monotonic() - started) * 1000
        logger.debug(
            "Serper response  term=%r  page=%d  status=%d  %.0fms",
            term,
            page,
            resp.status_code,
            elapsed_ms,
        )

        if resp.status_code == 401 or resp.status_code == 403:
            logger.error(
                "Serper auth error  term=%r  status=%d  body=%s",
                term,
                resp.status_code,
                resp.text[:300],
            )
            raise SearchError(
                f"Serper rejected the request (HTTP {resp.status_code}). "
                "Check that SERPER_API_KEY is set correctly."
            )
        if resp.status_code == 429:
            raise SearchError(
                "Serper rate limit / credits exhausted (HTTP 429). Check your "
                "plan or wait before retrying."
            )
        if resp.status_code >= 400:
            logger.error(
                "Serper error  term=%r  status=%d  body=%s",
                term,
                resp.status_code,
                resp.text[:300],
            )
            raise SearchError(
                f"Serper API error (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise SearchError("Serper returned a non-JSON response.") from exc

        organic = payload.get("organic", [])
        return organic if isinstance(organic, list) else []

    def find_rank(self, term: str, target_domain: str) -> RankResult:
        """Search ``term`` and locate ``target_domain`` in the results.

        Pages through Serper until the target is found or ``max_pages`` is
        reached. Uses Serper's own ``position`` when present, otherwise
        derives it from the page and index. Page = ((position-1)//10)+1.
        """
        target_domain = normalize_domain(target_domain)
        if not target_domain:
            return RankResult(term=term, found=False, error="No target domain provided.")

        logger.info("Checking term=%r for target=%r", term, target_domain)

        scanned = 0
        # Remember the first handful of results so we can show what actually
        # ranks when the target isn't found (helps diagnose "why not me?").
        top_seen: list[tuple[int, str]] = []
        for page in range(1, self.max_pages + 1):
            organic = self._request_page(term, page)
            if not organic:
                break  # no more results

            for idx, item in enumerate(organic):
                scanned += 1
                link = item.get("link", "")
                # Prefer Serper's absolute position; fall back to computing it.
                position = item.get("position") or ((page - 1) * RESULTS_PER_PAGE + idx + 1)
                if len(top_seen) < TOP_COMPETITORS_TO_LOG:
                    top_seen.append((position, link))

                if _link_matches_target(link, target_domain):
                    result_page = ((position - 1) // RESULTS_PER_PAGE) + 1
                    logger.info(
                        "FOUND term=%r  page=%d  position=%d  url=%s",
                        term,
                        result_page,
                        position,
                        link,
                    )
                    return RankResult(
                        term=term,
                        found=True,
                        page=result_page,
                        position=position,
                        url=link,
                        title=item.get("title"),
                        total_results_scanned=scanned,
                    )

            # Serper returned a short page -> no further pages exist.
            if len(organic) < RESULTS_PER_PAGE:
                break

        logger.info(
            "NOT FOUND term=%r  scanned %d result(s) without a match", term, scanned
        )
        # At DEBUG, show what DID rank so it's clear who you're up against.
        if top_seen and logger.isEnabledFor(logging.DEBUG):
            competitors = "  ".join(f"#{pos} {url}" for pos, url in top_seen)
            logger.debug("Top results for term=%r: %s", term, competitors)
        return RankResult(term=term, found=False, total_results_scanned=scanned)

    def find_ranks(self, terms: list[str], target_domain: str) -> list[RankResult]:
        """Run :meth:`find_rank` for each term, isolating per-term errors."""
        logger.info(
            "Starting rank check (Serper): %d term(s) against target=%r",
            len(terms),
            target_domain,
        )
        results: list[RankResult] = []
        for raw_term in terms:
            term = raw_term.strip()
            if not term:
                continue
            try:
                results.append(self.find_rank(term, target_domain))
            except SearchError as exc:
                logger.warning("Term %r failed: %s", term, exc)
                results.append(RankResult(term=term, found=False, error=str(exc)))

        found = sum(1 for r in results if r.found)
        errored = sum(1 for r in results if r.error)
        logger.info(
            "Rank check complete: %d checked, %d found, %d error(s)",
            len(results),
            found,
            errored,
        )
        return results
