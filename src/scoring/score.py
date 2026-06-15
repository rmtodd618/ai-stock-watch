"""Pure scoring engine: metrics -> score (0..100) + component breakdown.

The score is a weighted sum of four interpretable components, each normalized to
0..1. Weights come from config and are expected to sum to 100, but the result is
rescaled by the actual weight total so a misconfigured set of weights still
yields a 0..100 score.

Design intent: reward *quality dips in established uptrends* and penalize both
broken-down charts and over-extended/falling-knife short-term action.
"""

from __future__ import annotations

from typing import Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ramp(x: float, x0: float, x1: float) -> float:
    """Linear ramp: 0 at x0, 1 at x1, clamped to [0, 1]."""
    if x1 == x0:
        return 1.0 if x >= x1 else 0.0
    return _clamp((x - x0) / (x1 - x0))


def _pullback_component(
    pct_below_high: Optional[float],
    ideal_min: float,
    ideal_max: float,
    broken_below: float,
) -> float:
    """Tent function over '% below 52-week high'.

    - At/above the high (<=0): 0.5 — strong, but little fresh opportunity / extended.
    - 0 .. ideal_min: ramps 0.5 -> 1.0 (a developing dip).
    - ideal_min .. ideal_max: 1.0 — the healthy-pullback sweet spot.
    - ideal_max .. broken_below: ramps 1.0 -> 0.0 (deepening / questionable).
    - >= broken_below: 0.0 — treated as a broken setup.
    """
    if pct_below_high is None:
        return 0.5
    pbh = pct_below_high
    if pbh <= 0:
        return 0.5
    if pbh < ideal_min:
        return 0.5 + 0.5 * (pbh / ideal_min)
    if pbh <= ideal_max:
        return 1.0
    if pbh < broken_below:
        return _clamp(1.0 - (pbh - ideal_max) / (broken_below - ideal_max))
    return 0.0


def score_metrics(metrics: dict, config: dict) -> dict:
    """Score a single ticker's metrics.

    Returns ``{"score": float, "components": {...0..1}, "breakdown": {...points}}``
    where ``breakdown`` is each component's points contribution to the final score.
    """
    scoring = config.get("scoring", {})
    weights = scoring.get("weights", {})
    pb = scoring.get("pullback", {})
    mom = scoring.get("momentum", {})

    current = metrics.get("current_price")
    ma50 = metrics.get("ma50")
    ma200 = metrics.get("ma200")

    components: dict[str, float] = {}

    # Long-term trend: price vs 200-day MA. 5% below -> 0, 5% above -> 1.
    components["long_term_trend"] = (
        _ramp(current / ma200, 0.95, 1.05) if (ma200 and current) else 0.5
    )

    # Medium-term trend: price vs 50-day MA. 3% below -> 0, 3% above -> 1.
    components["medium_term_trend"] = (
        _ramp(current / ma50, 0.97, 1.03) if (ma50 and current) else 0.5
    )

    # Trend structure: 50-day vs 200-day MA (golden-cross posture).
    components["trend_structure"] = (
        _ramp(ma50 / ma200, 0.98, 1.02) if (ma50 and ma200) else 0.5
    )

    # Pullback quality.
    components["pullback"] = _pullback_component(
        metrics.get("pct_below_52w_high"),
        ideal_min=pb.get("ideal_min", 8),
        ideal_max=pb.get("ideal_max", 20),
        broken_below=pb.get("broken_below", 45),
    )

    # Momentum: calm short-term action. |5d move| beyond tolerance -> 0.
    ch5 = metrics.get("change_5d")
    tol = mom.get("tolerance_pct", 12)
    components["momentum"] = _clamp(1.0 - abs(ch5) / tol) if ch5 is not None else 0.5

    total_weight = sum(weights.values()) or 1.0
    points = {k: weights.get(k, 0) * components.get(k, 0.0) for k in weights}
    raw = sum(points.values())
    score = raw / total_weight * 100.0

    return {
        "score": round(score, 1),
        "components": {k: round(v, 3) for k, v in components.items()},
        "breakdown": {k: round(v, 1) for k, v in points.items()},
    }
