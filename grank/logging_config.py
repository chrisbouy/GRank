"""Centralized logging setup for GRank.

Call :func:`configure_logging` once at startup. Log level is controlled
by the ``LOG_LEVEL`` environment variable (default INFO). Set
``LOG_LEVEL=DEBUG`` to see every request URL (with the API key redacted)
and the raw error bodies Google returns.
"""

from __future__ import annotations

import logging
import os
import re

_CONFIGURED = False

# Matches "key=..." in a URL/query string so we never write the API key to logs.
_KEY_RE = re.compile(r"(key=)[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Replace any Google API key in ``text`` with a placeholder."""
    if not text:
        return text
    return _KEY_RE.sub(r"\1REDACTED", text)


def configure_logging() -> None:
    """Configure root logging once, honoring the LOG_LEVEL env var."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring logging is configured first."""
    configure_logging()
    return logging.getLogger(name)
