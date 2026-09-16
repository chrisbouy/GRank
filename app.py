"""GRank Flask web app.

Serves a small UI for pasting search terms + a target domain, and a
JSON endpoint (/api/rank) that returns the Google result page each term
ranks on, using the Custom Search JSON API.

Run:
    python app.py
Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from grank.logging_config import get_logger
from grank.results_log import DEFAULT_LOG_PATH, append_run
from grank.search_client import SearchError, parse_terms
from grank.serper_client import DEFAULT_MAX_PAGES, SerperSearchClient

load_dotenv()

logger = get_logger("grank.app")

app = Flask(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


_PLACEHOLDER_KEY = "your_serper_api_key_here"


def _serper_key() -> str:
    """Return the configured Serper key, treating the placeholder as unset."""
    key = (os.environ.get("SERPER_API_KEY") or "").strip()
    return "" if key == _PLACEHOLDER_KEY else key


def build_client() -> SerperSearchClient:
    """Construct a Serper search client from environment configuration.

    Raises SearchError if the API key is missing so callers can surface
    a clear setup message.
    """
    return SerperSearchClient(
        api_key=_serper_key(),
        max_pages=_int_env("MAX_PAGES", DEFAULT_MAX_PAGES),
        gl=os.environ.get("SEARCH_COUNTRY") or None,
        hl=os.environ.get("SEARCH_LANGUAGE") or None,
    )


@app.route("/")
def index():
    credentials_ok = bool(_serper_key())
    return render_template("index.html", credentials_ok=credentials_ok)


@app.route("/api/rank", methods=["POST"])
def api_rank():
    data = request.get_json(silent=True) or {}
    raw_terms = data.get("terms", "")
    target = (data.get("target") or "").strip()

    # Accept either a pasted block of text or a JSON list of terms.
    if isinstance(raw_terms, list):
        terms = parse_terms("\n".join(str(t) for t in raw_terms))
    else:
        terms = parse_terms(str(raw_terms))

    if not target:
        logger.info("Rejected /api/rank: no target provided")
        return jsonify({"error": "Please provide a target domain or URL."}), 400
    if not terms:
        logger.info("Rejected /api/rank: no search terms provided")
        return jsonify({"error": "Please provide at least one search term."}), 400

    logger.info("/api/rank request: target=%r terms=%d", target, len(terms))

    try:
        client = build_client()
    except SearchError as exc:
        logger.error("Client configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    results = client.find_ranks(terms, target)

    # Append this run to the persistent results log (best-effort).
    try:
        log_path = os.environ.get("RESULTS_LOG", DEFAULT_LOG_PATH)
        append_run(target, results, path=log_path)
    except OSError as exc:
        logger.warning("Could not append to results log: %s", exc)

    return jsonify(
        {
            "target": target,
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
    )


if __name__ == "__main__":
    port = _int_env("PORT", 5000)
    app.run(host="127.0.0.1", port=port, debug=True)
