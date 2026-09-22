"""Price history via yfinance — the single network boundary of the app.

Everything downstream operates on plain lists of closing prices, so this module
can be swapped for a paid data provider without touching the scoring code.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_closes(ticker: str, period: str = "1y") -> Optional[list[float]]:
    """Return a list of daily closing prices (oldest -> newest) for ``ticker``.

    Returns None on failure (network error, unknown symbol, empty history) so the
    caller can skip the ticker rather than abort the whole run.
    """
    import yfinance as yf  # imported lazily so tests don't require the dependency

    try:
        history = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception as exc:  # noqa: BLE001 - third-party can raise broadly
        logger.warning("Failed to fetch %s: %s", ticker, exc)
        return None

    if history is None or history.empty or "Close" not in history:
        logger.warning("No price data returned for %s", ticker)
        return None

    closes = [float(c) for c in history["Close"].dropna().tolist()]
    return closes or None


def fetch_history(ticker: str, period: str = "max") -> Optional[tuple[list[str], list[float]]]:
    """Return ``(dates, closes)`` as parallel lists, oldest -> newest.

    ``fetch_closes`` throws the index away because the live path never needs it.
    Backfilling does: without dates there is no way to slice the series "as of"
    a past session.
    """
    import yfinance as yf

    try:
        history = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception as exc:  # noqa: BLE001 - third-party can raise broadly
        logger.warning("Failed to fetch %s: %s", ticker, exc)
        return None

    if history is None or history.empty or "Close" not in history:
        logger.warning("No price data returned for %s", ticker)
        return None

    closes = history["Close"].dropna()
    if closes.empty:
        return None
    return [d.strftime("%Y-%m-%d") for d in closes.index], [float(c) for c in closes]


def fetch_many(tickers: list[str], period: str = "1y") -> dict[str, list[float]]:
    """Fetch closes for several tickers. Missing/failed tickers are omitted."""
    out: dict[str, list[float]] = {}
    for ticker in tickers:
        closes = fetch_closes(ticker, period=period)
        if closes:
            out[ticker] = closes
    return out
