"""Fetch macro proxy series and compute change-over-lookback for regime checks.

Reuses the price fetcher — macro proxies (oil CL=F, gold GC=F, VIX ^VIX,
10-yr ^TNX) are just tickers as far as the data source is concerned.
"""

from __future__ import annotations

import logging

from src.data_sources import prices

logger = logging.getLogger(__name__)


def fetch_macro_changes(regimes_config: list[dict], period: str = "3mo") -> dict:
    """Return ``{series: percent_change_over_its_lookback}`` for each regime series.

    Series that fail to fetch or lack enough history are simply omitted, so the
    corresponding regime is treated as inactive (no tilt) rather than erroring.
    """
    changes: dict[str, float] = {}
    # One regime series may appear more than once; fetch each only as needed.
    for regime in regimes_config:
        series = regime.get("series")
        lookback = regime.get("lookback_days", 20)
        if not series or series in changes:
            continue
        closes = prices.fetch_closes(series, period=period)
        if not closes or len(closes) <= lookback:
            logger.warning("Insufficient macro history for %s", series)
            continue
        past = closes[-1 - lookback]
        if not past:
            continue
        changes[series] = (closes[-1] - past) / past * 100.0
    return changes
