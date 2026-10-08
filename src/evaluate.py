"""Score the tool against what actually happened.

Every snapshot records what the report said on a given session. Joined to the
prices that followed, that becomes an answer to the only question worth asking:
did the ranking carry information, and did acting on it beat not acting?

Three measures, in increasing order of how much they can flatter you:

``rank_ic``
    Spearman correlation between the day's scores and the forward returns that
    followed, averaged over sessions. This is the cleanest read — it is
    cross-sectional, so it cannot be inflated by the whole watchlist going up.

``tier_returns``
    Average forward return per action tier. Useful for seeing whether the tiers
    are ordered at all, and in particular whether AVOID really is worse than
    WATCH (in backtest it was not).

``portfolio``
    What the flagged set actually returned, against the two benchmarks that
    matter: holding the entire watchlist equally, and holding SPY. The first is
    the one people skip, and it is the one that decides whether the tool earned
    its keep. Beating SPY while trailing your own watchlist means the watchlist
    did the work, not the scoring.

Pure except for the caller handing in snapshots and prices.
"""

from __future__ import annotations

import logging
import math
from statistics import mean
from typing import Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

HELD_ACTIONS = ("ADD SIGNAL",)


# --- small stats helpers (kept local so the package needs no scipy) ----------

def _rank(values: Sequence[float]) -> list[float]:
    """Ranks, averaging ties — the standard competition-with-ties handling."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman correlation, or None when it is undefined (constant input)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


# --- forward returns ---------------------------------------------------------

def forward_return(
    closes_by_date: dict[str, float],
    sessions: Sequence[str],
    start: str,
    horizon: int,
) -> Optional[float]:
    """Return over ``horizon`` sessions after ``start``, as a fraction.

    ``sessions`` is the master trading calendar. Returns None when the window
    runs past the end of the data, so an unfinished horizon is never silently
    scored as zero.
    """
    try:
        i = sessions.index(start)
    except ValueError:
        return None
    j = i + horizon
    if j >= len(sessions):
        return None
    a, b = closes_by_date.get(sessions[i]), closes_by_date.get(sessions[j])
    if a is None or b is None or a == 0:
        return None
    return b / a - 1.0


# --- the three measures ------------------------------------------------------

def rank_ic(
    snapshots: Iterable[dict],
    prices: dict[str, dict[str, float]],
    sessions: Sequence[str],
    horizon: int = 21,
    min_names: int = 6,
) -> dict:
    """Mean cross-sectional rank IC of score vs forward return."""
    per_session: list[float] = []
    for snap in snapshots:
        session = snap.get("generated_at", "")[:10]
        scores, rets = [], []
        for row in snap.get("rows", []):
            if row.get("is_benchmark"):
                continue
            score = row.get("score")
            series = prices.get(row.get("ticker", ""))
            if score is None or not series:
                continue
            fwd = forward_return(series, sessions, session, horizon)
            if fwd is None:
                continue
            scores.append(float(score))
            rets.append(fwd)
        if len(scores) >= min_names:
            ic = spearman(scores, rets)
            if ic is not None:
                per_session.append(ic)

    if not per_session:
        return {"horizon": horizon, "sessions": 0, "mean_ic": None, "t_stat": None}

    m = mean(per_session)
    n = len(per_session)
    sd = math.sqrt(sum((x - m) ** 2 for x in per_session) / (n - 1)) if n > 1 else 0.0
    return {
        "horizon": horizon,
        "sessions": n,
        "mean_ic": m,
        "t_stat": (m / sd * math.sqrt(n)) if sd else None,
        "pct_positive": sum(1 for x in per_session if x > 0) / n * 100.0,
    }


def tier_returns(
    snapshots: Iterable[dict],
    prices: dict[str, dict[str, float]],
    sessions: Sequence[str],
    horizon: int = 21,
) -> dict[str, dict]:
    """Average forward return per action tier, plus the universe baseline."""
    buckets: dict[str, list[float]] = {}
    everything: list[float] = []
    for snap in snapshots:
        session = snap.get("generated_at", "")[:10]
        for row in snap.get("rows", []):
            if row.get("is_benchmark"):
                continue
            series = prices.get(row.get("ticker", ""))
            if not series:
                continue
            fwd = forward_return(series, sessions, session, horizon)
            if fwd is None:
                continue
            buckets.setdefault(row.get("action", "?"), []).append(fwd)
            everything.append(fwd)

    out = {
        action: {"n": len(v), "mean_return": mean(v) * 100.0}
        for action, v in sorted(buckets.items())
    }
    if everything:
        out["ALL (baseline)"] = {
            "n": len(everything),
            "mean_return": mean(everything) * 100.0,
        }
    return out


def portfolio(
    snapshots: Sequence[dict],
    prices: dict[str, dict[str, float]],
    sessions: Sequence[str],
    *,
    held_actions: Sequence[str] = HELD_ACTIONS,
    cost_bps: float = 20.0,
) -> dict:
    """Simulate holding the flagged set, against two benchmarks.

    The snapshot is produced after the close, so its weights earn the *next*
    session's return. Equal weight across the flagged names, rebalanced whenever
    the flagged set changes, charged ``cost_bps`` per unit of turnover.
    """
    by_session = {s.get("generated_at", "")[:10]: s for s in snapshots}
    ordered = [d for d in sessions if d in by_session]
    if len(ordered) < 2:
        return {"sessions": 0}

    weights: dict[str, float] = {}
    strat: list[float] = []
    bench: list[float] = []
    turnovers: list[float] = []
    held_counts: list[int] = []

    for prev, today in zip(ordered, ordered[1:]):
        snap = by_session[prev]
        rows = [r for r in snap.get("rows", []) if not r.get("is_benchmark")]

        def ret(ticker: str) -> Optional[float]:
            series = prices.get(ticker)
            return forward_return(series, sessions, prev, 1) if series else None

        # realise yesterday's weights over today's move
        day = 0.0
        for ticker, w in weights.items():
            r = ret(ticker)
            if r is not None:
                day += w * r
        # the do-nothing comparison: every name in the watchlist, equally
        universe = [r_ for r_ in (ret(x["ticker"]) for x in rows) if r_ is not None]
        bench.append(mean(universe) if universe else 0.0)

        selected = [r["ticker"] for r in rows if r.get("action") in held_actions]
        target = {t: 1.0 / len(selected) for t in selected} if selected else {}
        turnover = sum(
            abs(target.get(t, 0.0) - weights.get(t, 0.0))
            for t in set(target) | set(weights)
        )
        strat.append(day - turnover * cost_bps / 1e4)
        turnovers.append(turnover)
        held_counts.append(len(selected))
        weights = target

    def compound(xs: Sequence[float]) -> float:
        total = 1.0
        for x in xs:
            total *= 1.0 + x
        return total - 1.0

    years = len(strat) / 252.0
    spy = [
        forward_return(prices.get("SPY", {}), sessions, d, 1) or 0.0
        for d in ordered[:-1]
    ]
    return {
        "sessions": len(strat),
        "strategy_return": compound(strat) * 100.0,
        "watchlist_return": compound(bench) * 100.0,
        "spy_return": compound(spy) * 100.0,
        "excess_vs_watchlist": (compound(strat) - compound(bench)) * 100.0,
        "avg_held": mean(held_counts) if held_counts else 0.0,
        "annualised_turnover": (sum(turnovers) / years * 100.0) if years else 0.0,
    }
