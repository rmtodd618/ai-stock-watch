import pytest

from src.backfill import (
    BackfillError,
    check_features,
    closes_as_of,
    reconstruct,
    trading_calendar,
)

DATES = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
CLOSES = [10.0, 11.0, 12.0, 13.0]


def _config():
    return {
        "scoring": {
            "smoothing_days": 5,
            "selection": {"mode": "rank", "top_n": 1, "bench_n": 0},
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
        },
        "benchmarks": ["SPY"],
    }


def _series(n, start=100.0):
    return [start + i for i in range(n)]


def _history(n=80):
    days = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return {
        "AAA": (days, _series(n)),
        "SPY": (days, _series(n, start=400.0)),
    }


# --- calendar -----------------------------------------------------------------

def test_calendar_uses_the_benchmark_not_the_union():
    """A futures row on a market holiday must not become a session."""
    hist = {
        "AAA": ["2026-01-02", "2026-01-05"],
        "CL=F": ["2026-01-02", "2026-01-03", "2026-01-05"],  # trades the holiday
        "SPY": ["2026-01-02", "2026-01-05"],
    }
    assert trading_calendar(hist, "SPY") == ["2026-01-02", "2026-01-05"]


def test_calendar_falls_back_to_longest_series():
    hist = {"AAA": ["2026-01-02"], "BBB": ["2026-01-02", "2026-01-05"]}
    assert trading_calendar(hist, benchmark="MISSING") == ["2026-01-02", "2026-01-05"]


def test_calendar_of_nothing_is_empty():
    assert trading_calendar({}, "SPY") == []


# --- point-in-time slicing ----------------------------------------------------

def test_closes_as_of_includes_the_session_itself():
    assert closes_as_of(DATES, CLOSES, "2026-01-06") == [10.0, 11.0, 12.0]


def test_closes_as_of_never_sees_the_future():
    """The whole point: a past snapshot must not contain a later close."""
    assert closes_as_of(DATES, CLOSES, "2026-01-05") == [10.0, 11.0]


def test_closes_as_of_before_the_series_starts_is_empty():
    assert closes_as_of(DATES, CLOSES, "2025-12-31") == []


def test_closes_as_of_handles_a_non_trading_date():
    # 2026-01-04 is a Sunday and not in the series. Everything up to it means
    # Friday's close only — Monday the 5th has not happened yet.
    assert closes_as_of(DATES, CLOSES, "2026-01-04") == [10.0]


# --- feature guard ------------------------------------------------------------

@pytest.mark.parametrize("feature", ["news_sentiment", "earnings_guard", "macro_overlay"])
def test_refuses_to_reconstruct_point_in_time_layers(feature):
    with pytest.raises(BackfillError, match=feature):
        check_features({"features": {feature: True}})


def test_allows_plain_technical_config():
    check_features({"features": {"news_sentiment": False}})
    check_features({})


# --- reconstruction -----------------------------------------------------------

def test_yields_one_snapshot_per_session_in_range():
    hist = _history()
    sessions = [
        s
        for s, _ in reconstruct(
            _config(), hist, start="2026-02-05", benchmark="SPY", min_sessions=1
        )
    ]
    assert sessions == [d for d in hist["SPY"][0] if d >= "2026-02-05"]


def test_a_session_with_no_usable_history_is_skipped_entirely():
    """Early sessions, before any ticker has enough closes, produce no snapshot."""
    hist = _history()
    sessions = [
        s
        for s, _ in reconstruct(
            _config(), hist, end="2026-01-20", benchmark="SPY", min_sessions=30
        )
    ]
    assert sessions == []


def test_snapshots_are_stamped_as_reconstructed():
    """A backfilled row must never pass for a live observation."""
    _, snap = next(iter(reconstruct(_config(), _history(), start="2026-02-05", benchmark="SPY")))
    assert snap["source"] == "backfill"


def test_generated_at_is_the_session_being_reconstructed():
    session, snap = next(iter(reconstruct(_config(), _history(), start="2026-02-05", benchmark="SPY")))
    assert snap["generated_at"] == session


def test_min_sessions_excludes_a_barely_listed_ticker():
    days, closes = _history()["AAA"]
    hist = {
        "AAA": (days, closes),
        "NEW": (days[-3:], closes[-3:]),  # three sessions of history
        "SPY": _history()["SPY"],
    }
    _, snap = next(iter(reconstruct(_config(), hist, start=days[-1], benchmark="SPY")))
    assert "NEW" not in [r["ticker"] for r in snap["rows"]]


def test_reconstruction_refuses_when_a_v2_layer_is_on():
    cfg = _config()
    cfg["features"] = {"news_sentiment": True}
    with pytest.raises(BackfillError):
        list(reconstruct(cfg, _history(), benchmark="SPY"))
