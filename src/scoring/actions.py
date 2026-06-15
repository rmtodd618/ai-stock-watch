"""Pure score -> action-tier mapping.

Deliberately framed as research signals, not buy/sell orders.
"""

from __future__ import annotations

from enum import Enum


class Action(Enum):
    ADD = "ADD SIGNAL"
    STARTER = "STARTER SIGNAL"
    WATCH = "WATCH"
    AVOID = "AVOID FOR NOW"

    @property
    def label(self) -> str:
        return self.value


def action_for_score(score: float, thresholds: dict) -> Action:
    """Map a 0..100 score to an action tier using configured thresholds."""
    if score >= thresholds.get("add", 80):
        return Action.ADD
    if score >= thresholds.get("starter", 65):
        return Action.STARTER
    if score >= thresholds.get("watch", 50):
        return Action.WATCH
    return Action.AVOID
