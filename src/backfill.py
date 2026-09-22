"""Reconstruct historical snapshots from price history.

The technical score is a pure function of its trailing close window, so every
past session's score can be recomputed exactly — feed the scorer the series as
it stood that day and it returns what the report would have said. That makes the
v1 record recoverable rather than lost.

**A reconstructed row is not out-of-sample evidence.** It is a restatement of
what *today's* rules would have said, using today's watchlist — which was itself
chosen knowing how these names turned out. Snapshots produced here are stamped
``"source": "backfill"`` so they can never be mistaken for rows observed live.

The v2 context layers cannot be reconstructed at all: news sentiment depends on
headlines as they were published, and the earnings guard on a forward calendar
as it stood that day. Neither is recoverable from prices, so backfilling refuses
to run with those features enabled rather than silently emit rows that differ in
meaning from the live ones.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from typing import Iterator, Optional, Sequence

from src.handler import build_results
from src.storage.s3 import build_snapshot

logger = logging.getLogger(__name__)

# The layers that depend on point-in-time data the price series cannot recover.
UNRECONSTRUCTABLE_FEATURES = ("news_sentiment", "earnings_guard", "macro_overlay")


class BackfillError(RuntimeError):
    """Raised when a backfill would produce rows that differ from live ones."""


def check_features(config: dict) -> None:
    """Refuse to backfill while a non-reconstructable layer is on."""
    features = config.get("features", {}) or {}
    enabled = [f for f in UNRECONSTRUCTABLE_FEATURES if features.get(f)]
    if enabled:
        raise BackfillError(
            "Cannot reconstruct "
            + ", ".join(enabled)
            + " from price history — these depend on what was knowable that day. "
            "Disable them for the backfill; they will accumulate from live runs."
        )


def trading_calendar(
    dates_by_ticker: dict[str, Sequence[str]],
    benchmark: Optional[str] = None,
) -> list[str]:
    """The sessions to reconstruct, taken from one instrument's own calendar.

    Deliberately *not* the union of every ticker's dates. Futures and index rows
    trade on days the equity market is shut (Labor Day, 4 July); a union calendar
    therefore contains sessions on which no stock has a price, which the scorer
    reads as "nothing qualifies" — an artificial liquidation. Anchoring to a
    single liquid equity benchmark avoids that whole class of bug.
    """
    if benchmark and benchmark in dates_by_ticker:
        return list(dates_by_ticker[benchmark])
    if not dates_by_ticker:
        return []
    # Fall back to the ticker with the most sessions — the best calendar on offer.
    return list(max(dates_by_ticker.values(), key=len))


def closes_as_of(dates: Sequence[str], closes: Sequence[float], asof: str) -> list[float]:
    """Closes up to and including ``asof``. Empty if the series starts later."""
    return list(closes[: bisect_right(dates, asof)])


def reconstruct(
    config: dict,
    history: dict[str, tuple[Sequence[str], Sequence[float]]],
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_sessions: int = 30,
    benchmark: Optional[str] = None,
) -> Iterator[tuple[str, dict]]:
    """Yield ``(session, snapshot)`` for each session in range, oldest first.

    ``min_sessions`` drops a ticker from a given day if it had barely any history
    then — a name three days past its IPO has no meaningful trend to score, and
    including it would let it take a portfolio slot on noise.
    """
    check_features(config)

    dates_by_ticker = {t: d for t, (d, _) in history.items()}
    calendar = trading_calendar(dates_by_ticker, benchmark)
    sessions = [
        d for d in calendar if (start is None or d >= start) and (end is None or d <= end)
    ]

    for session in sessions:
        closes_by_ticker: dict[str, list[float]] = {}
        for ticker, (dates, closes) in history.items():
            series = closes_as_of(dates, closes, session)
            if len(series) >= min_sessions:
                closes_by_ticker[ticker] = series
        if not closes_by_ticker:
            logger.debug("No ticker has usable history at %s — skipping", session)
            continue

        results = build_results(config, closes_by_ticker)
        if not results:
            continue
        yield session, build_snapshot(results, config, session, source="backfill")
