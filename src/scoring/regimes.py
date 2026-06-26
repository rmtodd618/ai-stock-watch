"""Pure macro-regime detection and per-ticker tilt.

A "regime" is a persistent macro condition (oil ripping, VIX spiking) that
trends for weeks — the kind of signal a slow daily tool can actually use. We
detect active regimes from precomputed macro changes, then tilt each ticker that
belongs to an affected theme. All bounded by ``cap`` so the chart stays dominant.
"""

from __future__ import annotations

from typing import Optional


def active_regimes(macro_changes: dict, regimes_config: list[dict]) -> list[dict]:
    """Return the regime configs whose trigger condition is currently met.

    ``macro_changes`` maps a series symbol -> percent change over its lookback,
    e.g. ``{"CL=F": 14.2, "^VIX": 35.0}``.
    """
    active: list[dict] = []
    for regime in regimes_config:
        change = macro_changes.get(regime.get("series"))
        if change is None:
            continue
        threshold = regime.get("change_pct", 0)
        direction = regime.get("direction", "up")
        if direction == "up" and change >= threshold:
            active.append(regime)
        elif direction == "down" and change <= -threshold:
            active.append(regime)
    return active


def ticker_themes(ticker: str, themes_map: dict) -> set[str]:
    """Themes a ticker belongs to."""
    return {theme for theme, members in themes_map.items() if ticker in (members or [])}


def macro_tilt(
    ticker: str,
    active: list[dict],
    themes_map: dict,
    cap: float,
) -> tuple[float, list[str]]:
    """Sum the tilts of active regimes that affect this ticker, clamped to +/-cap.

    A regime with ``themes: ["*"]`` affects every ticker (e.g. risk-off).
    Returns ``(tilt_points, tags)``.
    """
    themes = ticker_themes(ticker, themes_map)
    tilt = 0.0
    tags: list[str] = []
    for regime in active:
        regime_themes = regime.get("themes", [])
        if "*" in regime_themes or themes.intersection(regime_themes):
            tilt += regime.get("tilt", 0)
            tags.append(regime.get("tag", regime.get("name", "regime")))
    return max(-cap, min(cap, tilt)), tags
