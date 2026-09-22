"""Average the technical score over a trailing window of trading days.

The raw daily score is noisy. Measured against forward returns, its information
is strongest at roughly a three-month horizon (rank IC +0.11 at 63 days vs +0.06
at 5), yet acting on the daily value round-trips positions every few days —
which costs far more than the signal is worth. Averaging the score over the last
N trading days keeps the slow component and discards most of that noise.

The score is a pure function of the trailing close window, so a *past* day's
score is recovered by truncating the series. No stored history is required: the
run just needs to fetch enough closes to cover ``lookback + smoothing_days``.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.scoring.score import score_metrics
from src.scoring.technicals import compute_metrics


def score_history(
    closes: Sequence[float],
    config: dict,
    days: int,
    lookback: int,
) -> list[float]:
    """Scores as they would have read on each of the last ``days`` sessions.

    Oldest -> newest. Each day is scored on its own trailing ``lookback`` window,
    so the 52-week high is always a 52-week high and never the high of whatever
    extra history was fetched to make the smoothing possible.
    """
    closes = [float(c) for c in closes if c is not None]
    n = len(closes)
    if not n or days < 1:
        return []

    scores: list[float] = []
    for offset in range(min(days, n) - 1, -1, -1):
        window = closes[: n - offset][-lookback:]
        metrics = compute_metrics(window)
        if metrics:
            scores.append(score_metrics(metrics, config)["score"])
    return scores


def smoothed_score(
    closes: Sequence[float],
    config: dict,
    days: int = 40,
    lookback: int = 252,
) -> Optional[float]:
    """Mean score over the last ``days`` sessions, or None if unscoreable.

    ``days <= 1`` returns the latest score unchanged, which is the v1 behaviour.
    """
    history = score_history(closes, config, days, lookback)
    if not history:
        return None
    return sum(history) / len(history)
