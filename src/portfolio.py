"""Compare what you hold against what the model holds.

The report has always described a model portfolio without knowing anything about
the actual one, which makes it informational rather than actionable: it can say
a name is ranked first, but not whether you own it, how far you have drifted, or
what closing that gap would cost.

The costs are the point. Everything measured about this strategy says the
trading, not the ranking, is what destroys the return — 342 signal episodes at a
35% hit rate, a median trade of -3.0%, and annualised turnover in the hundreds of
percent. So every suggested trade is priced: the spread you pay to make it and
the gain you realise by making it. A move that cannot clear its own cost is not
a move.

``rebalance_band`` exists for the same reason. Drift smaller than the band is
left alone rather than reported as something to fix, because a portfolio nudged
back to target every day is exactly the behaviour the backtest punished.

Pure: holdings, prices and model rows in, arithmetic out. No IO, no advice.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

HELD_ACTION = "ADD SIGNAL"
LONG_TERM_DAYS = 365


def _as_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def market_values(holdings: dict, prices: dict[str, float]) -> dict[str, float]:
    """Current dollar value of each position, skipping anything unpriced."""
    out: dict[str, float] = {}
    for ticker, pos in (holdings.get("positions") or {}).items():
        shares = float(pos.get("shares", 0) or 0)
        price = prices.get(ticker)
        if shares and price:
            out[ticker] = shares * float(price)
    return out


def net_asset_value(holdings: dict, prices: dict[str, float]) -> float:
    """Positions plus cash. The denominator for every weight below."""
    return sum(market_values(holdings, prices).values()) + float(holdings.get("cash", 0) or 0)


def current_weights(holdings: dict, prices: dict[str, float]) -> dict[str, float]:
    nav = net_asset_value(holdings, prices)
    if nav <= 0:
        return {}
    return {t: v / nav for t, v in market_values(holdings, prices).items()}


def target_weights(results: list[dict]) -> dict[str, float]:
    """Equal weight across the flagged names, matching how the model is scored."""
    held = [
        r["ticker"] for r in results
        if r.get("action") == HELD_ACTION and r.get("ticker")
    ]
    return {t: 1.0 / len(held) for t in held} if held else {}


def realised_gain(ticker: str, dollars: float, holdings: dict, prices: dict,
                  today: Optional[date] = None) -> tuple[float, str]:
    """Gain released by selling ``dollars`` of ``ticker``, and its holding period.

    Returns ``(gain, "short"|"long"|"unknown")``. Without a cost basis the gain
    cannot be computed, and guessing it would be worse than saying so.
    """
    pos = (holdings.get("positions") or {}).get(ticker) or {}
    basis = pos.get("cost_basis")
    price = prices.get(ticker)
    if basis is None or not price or dollars <= 0:
        return 0.0, "unknown"
    shares_sold = dollars / float(price)
    gain = shares_sold * (float(price) - float(basis))

    acquired = _as_date(pos.get("acquired"))
    if acquired is None:
        return gain, "unknown"
    held_days = ((today or date.today()) - acquired).days
    return gain, ("long" if held_days >= LONG_TERM_DAYS else "short")


def rebalance(
    holdings: dict,
    results: list[dict],
    prices: dict[str, float],
    *,
    band: float = 0.02,
    spread_bps: float = 20.0,
    today: Optional[date] = None,
) -> dict:
    """What it would take to match the model, and what that would cost.

    ``band`` is the drift below which a position is left alone. Trades are
    reported, never recommended: the caller decides, and the cost is shown
    beside each one so that decision is made with the price attached.
    """
    nav = net_asset_value(holdings, prices)
    cur, tgt = current_weights(holdings, prices), target_weights(results)

    rows = []
    for ticker in sorted(set(cur) | set(tgt)):
        c, t = cur.get(ticker, 0.0), tgt.get(ticker, 0.0)
        drift = c - t
        dollars = -drift * nav          # positive -> buy, negative -> sell
        actionable = abs(drift) >= band
        gain, term = (0.0, "unknown")
        if dollars < 0:
            gain, term = realised_gain(ticker, -dollars, holdings, prices, today)
        rows.append({
            "ticker": ticker,
            "current": c,
            "target": t,
            "drift": drift,
            "dollars": dollars,
            "shares": (dollars / prices[ticker]) if prices.get(ticker) else None,
            "actionable": actionable,
            "realised_gain": gain,
            "term": term,
        })

    acting = [r for r in rows if r["actionable"]]
    traded = sum(abs(r["dollars"]) for r in acting)
    return {
        "nav": nav,
        "rows": rows,
        "actionable": acting,
        "turnover_dollars": traded,
        "spread_cost": traded * spread_bps / 1e4,
        "realised_short": sum(r["realised_gain"] for r in acting if r["term"] == "short"),
        "realised_long": sum(r["realised_gain"] for r in acting if r["term"] == "long"),
        "band": band,
        "largest_drift": max((abs(r["drift"]) for r in rows), default=0.0),
    }


def summary_line(plan: dict) -> str:
    """One sentence, and usually it says to do nothing."""
    n = len(plan["actionable"])
    if not plan["nav"]:
        return "No holdings recorded — nothing to compare against."
    if n == 0:
        return (
            f"No position has drifted past {plan['band']:.0%}; "
            f"largest gap is {plan['largest_drift']:.1%}. Nothing to do."
        )
    cost = plan["spread_cost"]
    bits = [f"{n} position(s) past the {plan['band']:.0%} band",
            f"${plan['turnover_dollars']:,.0f} to trade",
            f"~${cost:,.0f} in spread"]
    for amount, term in ((plan["realised_short"], "short"), (plan["realised_long"], "long")):
        if amount:
            # A negative "gain" is a loss, and the two have opposite tax
            # consequences — printing one as the other would be worse than
            # printing nothing.
            word = "gain" if amount > 0 else "loss"
            bits.append(f"${abs(amount):,.0f} {term}-term {word} realised")
    return " · ".join(bits)
