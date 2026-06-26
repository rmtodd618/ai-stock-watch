"""Combine the technical base score with bounded context tilts."""

from __future__ import annotations


def composite_score(base: float, macro_tilt: float = 0.0, sentiment_tilt: float = 0.0) -> float:
    """base (0..100) + tilts, clamped back into 0..100."""
    return max(0.0, min(100.0, base + macro_tilt + sentiment_tilt))
