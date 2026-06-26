"""Recent headlines per ticker via yfinance.

yfinance's ``.news`` shape has changed across versions (flat ``title`` vs a
nested ``content.title``); this tolerates both and returns plain strings.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_title(item: dict) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    if item.get("title"):
        return item["title"]
    content = item.get("content")
    if isinstance(content, dict) and content.get("title"):
        return content["title"]
    return None


def fetch_headlines(ticker: str, limit: int = 8) -> list[str]:
    """Return up to ``limit`` recent headline strings for ``ticker`` (may be empty)."""
    import yfinance as yf

    try:
        items = yf.Ticker(ticker).news or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch news for %s: %s", ticker, exc)
        return []

    titles = []
    for item in items:
        title = _extract_title(item)
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles
