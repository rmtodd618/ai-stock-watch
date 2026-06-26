"""Next-earnings-date lookup via yfinance.

yfinance exposes earnings dates inconsistently across versions, so this tolerates
several shapes and always degrades to None (no guard) rather than raising.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


def days_until_earnings(ticker: str, today: Optional[date] = None) -> Optional[int]:
    """Days until the next earnings date, or None if it can't be determined."""
    import yfinance as yf

    today = today or date.today()

    try:
        tk = yf.Ticker(ticker)
        candidates: list[date] = []

        # Newer yfinance: get_earnings_dates() -> DataFrame indexed by Timestamp.
        try:
            df = tk.get_earnings_dates(limit=8)
            if df is not None and not df.empty:
                candidates += [d for d in (_to_date(i) for i in df.index) if d]
        except Exception:  # noqa: BLE001 - fall through to calendar
            pass

        # Fallback: .calendar (dict or DataFrame depending on version).
        cal = getattr(tk, "calendar", None)
        if isinstance(cal, dict):
            val = cal.get("Earnings Date")
            vals = val if isinstance(val, (list, tuple)) else [val]
            candidates += [d for d in (_to_date(v) for v in vals) if d]

        future = sorted(d for d in candidates if d >= today)
        if not future:
            return None
        return (future[0] - today).days
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve earnings date for %s: %s", ticker, exc)
        return None
