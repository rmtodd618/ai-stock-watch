"""Shared test fixtures."""

import pytest


@pytest.fixture
def config():
    """A minimal config mirroring config.example.yaml's scoring block."""
    return {
        "scoring": {
            "thresholds": {"add": 80, "starter": 65, "watch": 50},
            "weights": {
                "long_term_trend": 25,
                "medium_term_trend": 15,
                "trend_structure": 15,
                "pullback": 25,
                "momentum": 20,
            },
            "pullback": {"ideal_min": 8, "ideal_max": 20, "broken_below": 45},
            "momentum": {"tolerance_pct": 12},
        }
    }
