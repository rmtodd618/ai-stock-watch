"""Claude-backed news sentiment scoring.

A single, cheap classification call per ticker using Claude Haiku 4.5 with a
JSON-schema structured output, so the result is guaranteed parseable. This is a
context layer — it summarizes why a name is moving; it is not an alpha signal.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        # -1.0 (very bearish) .. 1.0 (very bullish). Clamped downstream.
        "sentiment": {"type": "number"},
        "material_catalyst": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["sentiment", "material_catalyst", "summary"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a financial news classifier for a research watchlist tool. "
    "Given recent headlines for one ticker, judge the net near-term sentiment "
    "for the stock. Respond only via the structured schema. Be conservative: "
    "ambient or routine coverage is near 0.0; reserve large magnitudes for "
    "clear, material news. This is for research, not trading advice."
)


def score_headlines(
    ticker: str,
    headlines: list[str],
    model: str,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Score a ticker's headlines. Returns the sentiment dict, or None on failure.

    Returns ``{"sentiment": float, "material_catalyst": bool, "summary": str}``.
    """
    if not headlines:
        return None

    import anthropic  # lazy: only needed when the news layer is enabled

    bullet_list = "\n".join(f"- {h}" for h in headlines)
    user = (
        f"Ticker: {ticker}\n\nRecent headlines:\n{bullet_list}\n\n"
        "Score the net near-term sentiment for this stock and give a one-sentence "
        "summary of the dominant narrative."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
    except Exception as exc:  # noqa: BLE001 - never let sentiment break the run
        logger.warning("Sentiment scoring failed for %s: %s", ticker, exc)
        return None

    if response.stop_reason == "refusal":
        logger.info("Sentiment scoring refused for %s", ticker)
        return None

    import json

    try:
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
    except (StopIteration, ValueError) as exc:
        logger.warning("Could not parse sentiment for %s: %s", ticker, exc)
        return None
