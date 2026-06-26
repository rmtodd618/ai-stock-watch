"""Pure earnings-proximity guard.

Buying right before a scheduled binary event is the fastest way to get hurt on a
volatile name, so within the guard window we cap the action at WATCH regardless
of how good the chart looks. Pure function: takes days-until-earnings as an int
(the impure date lookup lives in ``data_sources/earnings.py``).
"""

from __future__ import annotations

from typing import Optional

from src.scoring.actions import Action


def apply_earnings_guard(
    action: Action,
    days_to_earnings: Optional[int],
    window: int,
) -> tuple[Action, Optional[str]]:
    """Cap ``action`` at WATCH if earnings fall within ``window`` days.

    Returns ``(action, tag)`` where ``tag`` is a human note when the guard fires,
    else None. Unknown/None/past dates pass through untouched.
    """
    if days_to_earnings is None or days_to_earnings < 0:
        return action, None
    if days_to_earnings <= window:
        capped = action if action in (Action.WATCH, Action.AVOID) else Action.WATCH
        return capped, f"earnings in {days_to_earnings}d"
    return action, None
