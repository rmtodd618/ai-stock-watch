"""Pure technical-metric computation.

Input is a plain sequence of closing prices (oldest -> newest). No pandas, no
network — this keeps the math trivially unit-testable. The data source
(``data_sources/prices.py``) is responsible for turning an API response into a
list of closes and calling :func:`compute_metrics`.
"""

from __future__ import annotations

from typing import Optional, Sequence


def _sma(closes: Sequence[float], window: int) -> Optional[float]:
    """Simple moving average of the last ``window`` closes, or None if too short."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _pct_change(closes: Sequence[float], lookback: int) -> Optional[float]:
    """Percent change over ``lookback`` trading days, or None if too short."""
    if len(closes) <= lookback:
        return None
    past = closes[-1 - lookback]
    if not past:
        return None
    return (closes[-1] - past) / past * 100.0


def compute_metrics(closes: Sequence[float]) -> Optional[dict]:
    """Compute the watchlist metrics from a series of closing prices.

    Returns a dict of metrics, or None if there is no usable data. Fields that
    cannot be computed from the available history (e.g. a 200-day MA with only
    120 data points) are returned as None rather than raising.
    """
    closes = [float(c) for c in closes if c is not None]
    if not closes:
        return None

    current = closes[-1]
    high_52w = max(closes)
    pct_below_high = (high_52w - current) / high_52w * 100.0 if high_52w else None

    return {
        "current_price": current,
        "change_5d": _pct_change(closes, 5),
        "change_30d": _pct_change(closes, 30),
        "ma50": _sma(closes, 50),
        "ma200": _sma(closes, 200),
        "high_52w": high_52w,
        "pct_below_52w_high": pct_below_high,
        "data_points": len(closes),
    }
