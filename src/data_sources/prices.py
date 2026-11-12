"""Price history via yfinance — the single network boundary of the app.

Everything downstream operates on plain lists of closing prices, so this module
can be swapped for a paid data provider without touching the scoring code.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, Optional

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


class FetchResult(NamedTuple):
    """What came back, and just as importantly what did not.

    The previous version returned a bare dict, so a ticker that failed to
    download simply was not in it. Nothing downstream could tell a rate-limited
    fetch from a ticker that was never requested, which meant a run with half
    the universe missing produced a normal-looking report and a snapshot that
    looked like a valid observation.
    """

    closes: dict[str, list[float]]
    requested: list[str]
    failed: list[str]

    @property
    def coverage(self) -> float:
        """Fraction of requested tickers that actually returned data."""
        return len(self.closes) / len(self.requested) if self.requested else 0.0


def fetch_many(tickers: list[str], period: str = "1y") -> FetchResult:
    """Fetch closes for several tickers, reporting which ones failed."""
    out: dict[str, list[float]] = {}
    failed: list[str] = []
    for ticker in tickers:
        closes = fetch_closes(ticker, period=period)
        if closes:
            out[ticker] = closes
        else:
            failed.append(ticker)
    if failed:
        logger.error(
            "Price fetch failed for %d of %d tickers: %s",
            len(failed), len(tickers), ", ".join(failed),
        )
    return FetchResult(closes=out, requested=list(tickers), failed=failed)
