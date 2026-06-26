"""Pure news-sentiment aggregation -> bounded tilt + report blurb.

The LLM call lives in ``llm/claude.py``; this turns its structured result into a
score adjustment. A material catalyst nudges the tilt magnitude up a little so a
genuine news event counts for more than ambient chatter. Always clamped to cap.
"""

from __future__ import annotations

from typing import Optional


def sentiment_tilt(result: Optional[dict], cap: float) -> tuple[float, Optional[str]]:
    """Map a sentiment result to ``(tilt_points, summary)``.

    ``result`` shape (from the LLM): ``{"sentiment": -1.0..1.0,
    "material_catalyst": bool, "summary": str}``. None/empty -> no tilt.
    """
    if not result:
        return 0.0, None

    sentiment = result.get("sentiment")
    if sentiment is None:
        return 0.0, result.get("summary")

    sentiment = max(-1.0, min(1.0, float(sentiment)))
    # A material catalyst gets the full cap; ambient sentiment is dampened.
    weight = 1.0 if result.get("material_catalyst") else 0.6
    tilt = sentiment * cap * weight
    tilt = max(-cap, min(cap, tilt))
    return round(tilt, 2), result.get("summary")
