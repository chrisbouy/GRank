"""Client for Google's Custom Search JSON API with rank detection.

This module queries the Custom Search API, pages through the organic
results for a term, and reports where a target domain first appears:
its absolute position (1-based) and which "page" of results that maps
to (10 results per page by convention, matching Google.com numbering).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlparse

import requests

from grank.logging_config import get_logger, redact

logger = get_logger("grank.search")

CUSTOM_SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# The Custom Search API hard-caps at 100 total results (start index 1..91)
# and at most 10 results per request.
API_MAX_RESULTS = 100
API_MAX_PER_PAGE = 10


class SearchError(Exception):
    """Raised when the Custom Search API returns an error or is misconfigured."""


@dataclass
class RankResult:
    """Outcome of checking one search term against a target domain."""

    term: str
    found: bool
    page: Optional[int] = None
    position: Optional[int] = None
    url: Optional[str] = None
    title: Optional[str] = None
    total_results_scanned: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_domain(value: str) -> str:
    """Reduce a URL or domain string to a bare, lowercase host.

    Strips scheme, path, and a leading "www." so that
    "https://www.Example.com/page" and "example.com" compare equal.
    """
    if not value:
        return ""
    value = value.strip().lower()
    # If it has a scheme, let urlparse pull the host; otherwise treat the
    # whole thing as a host (possibly with a trailing path we discard).
    if "://" in value:
        host = urlparse(value).netloc
    else:
        host = value.split("/")[0]
    host = host.split(":")[0]  # drop any port
    if host.startswith("www."):
        host = host[4:]
    return host


def _link_matches_target(link: str, target_domain: str) -> bool:
    """True if a result URL belongs to the target domain (or a subdomain)."""
    host = normalize_domain(link)
    if not host or not target_domain:
        return False
    return host == target_domain or host.endswith("." + target_domain)


class GoogleSearchClient:
    """Thin wrapper around the Custom Search JSON API."""

    def __init__(
        self,
        api_key: str,
        cse_id: str,
        results_per_page: int = API_MAX_PER_PAGE,
        max_results: int = API_MAX_RESULTS,
        session: Optional[requests.Session] = None,
        timeout: float = 20.0,
    ) -> None:
        if not api_key:
            raise SearchError("Missing GOOGLE_API_KEY.")
        if not cse_id:
            raise SearchError("Missing GOOGLE_CSE_ID.")

        self.api_key = api_key
        self.cse_id = cse_id
        self.results_per_page = max(1, min(results_per_page, API_MAX_PER_PAGE))
        self.max_results = max(1, min(max_results, API_MAX_RESULTS))
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request_page(self, term: str, start_index: int) -> dict:
        """Fetch a single API page starting at 1-based ``start_index``."""
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": term,
            "num": self.results_per_page,
            "start": start_index,
        }

        logger.debug(
            "GET Custom Search API  term=%r  start=%d  cx=%s",
            term,
            start_index,
            self.cse_id,
        )

        started = time.monotonic()
        try:
            resp = self.session.get(
                CUSTOM_SEARCH_ENDPOINT, params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.error("Network error for term=%r start=%d: %s", term, start_index, exc)
            raise SearchError(f"Network error contacting Google: {exc}") from exc

        elapsed_ms = (time.monotonic() - started) * 1000
        logger.debug(
            "Response  term=%r  start=%d  status=%d  %.0fms",
            term,
            start_index,
            resp.status_code,
            elapsed_ms,
        )

        if resp.status_code >= 400:
            # Log the full error body from Google (redacted) so the real
            # cause is visible, then raise a friendly message. The DEBUG line
            # includes the request URL so misconfigured cx/key is obvious.
            logger.error(
                "Google API error  term=%r  start=%d  status=%d  body=%s",
                term,
                start_index,
                resp.status_code,
                redact(resp.text[:1000]),
            )
            logger.debug("Request URL: %s", redact(resp.url))

        if resp.status_code == 429:
            raise SearchError(
                "Google API quota exceeded (HTTP 429). The free tier allows "
                "100 queries/day. Try again later or raise your quota."
            )
        if resp.status_code == 403:
            detail = self._extract_error_message(resp)
            raise SearchError(
                f"Google API rejected the request (HTTP 403): {detail} "
                "Check that the Custom Search API is enabled for your project, "
                "your API key is valid and unrestricted, and your GOOGLE_CSE_ID "
                "is correct."
            )
        if resp.status_code >= 400:
            detail = self._extract_error_message(resp)
            raise SearchError(f"Google API error (HTTP {resp.status_code}): {detail}")

        try:
            return resp.json()
        except ValueError as exc:
            logger.error("Non-JSON response for term=%r: %s", term, redact(resp.text[:300]))
            raise SearchError("Google API returned a non-JSON response.") from exc

    @staticmethod
    def _extract_error_message(resp: requests.Response) -> str:
        try:
            payload = resp.json()
            return payload.get("error", {}).get("message", resp.text[:200])
        except ValueError:
            return resp.text[:200] or "unknown error"

    def find_rank(self, term: str, target_domain: str) -> RankResult:
        """Search ``term`` and locate ``target_domain`` in the results.

        Pages through the API until the target is found or ``max_results``
        is reached. Page numbers use ``results_per_page`` (10 by default),
        so absolute position 34 -> page 4.
        """
        target_domain = normalize_domain(target_domain)
        if not target_domain:
            return RankResult(term=term, found=False, error="No target domain provided.")

        logger.info("Checking term=%r for target=%r", term, target_domain)

        scanned = 0
        position = 0
        start_index = 1

        while scanned < self.max_results and start_index <= API_MAX_RESULTS:
            payload = self._request_page(term, start_index)
            items = payload.get("items", [])
            if not items:
                break  # no more results for this term

            for item in items:
                position += 1
                scanned += 1
                link = item.get("link", "")
                if _link_matches_target(link, target_domain):
                    page = ((position - 1) // self.results_per_page) + 1
                    logger.info(
                        "FOUND term=%r  page=%d  position=%d  url=%s",
                        term,
                        page,
                        position,
                        link,
                    )
                    return RankResult(
                        term=term,
                        found=True,
                        page=page,
                        position=position,
                        url=link,
                        title=item.get("title"),
                        total_results_scanned=scanned,
                    )
                if scanned >= self.max_results:
                    break

            start_index += len(items)
            # Guard: if Google reports fewer results than a full page, stop.
            if len(items) < self.results_per_page:
                break

        logger.info(
            "NOT FOUND term=%r  scanned %d result(s) without a match",
            term,
            scanned,
        )
        return RankResult(
            term=term,
            found=False,
            total_results_scanned=scanned,
        )

    def find_ranks(self, terms: list[str], target_domain: str) -> list[RankResult]:
        """Run :meth:`find_rank` for each term, isolating per-term errors."""
        logger.info(
            "Starting rank check: %d term(s) against target=%r",
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


def parse_terms(raw: str) -> list[str]:
    """Split a pasted block of text into individual, de-duplicated terms.

    Accepts terms separated by newlines or commas. Preserves order while
    dropping blanks and exact duplicates.
    """
    if not raw:
        return []
    pieces = re.split(r"[\n,]+", raw)
    seen: set[str] = set()
    terms: list[str] = []
    for piece in pieces:
        term = piece.strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return terms
