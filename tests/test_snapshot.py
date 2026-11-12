from src.storage.s3 import build_snapshot

RESULTS = [
    {
        "ticker": "ANET",
        "rank": 1,
        "action": "ADD SIGNAL",
        "score": 87.1,
        "base_score": 87.1,
        "latest_score": 91.4,
        "is_benchmark": False,
        "tags": ["earnings in 3d"],
        "metrics": {
            "current_price": 205.42,
            "change_5d": 9.4,
            "change_30d": 8.9,
            "ma50": 190.0,
            "ma200": 170.0,
            "pct_below_52w_high": 2.4,
            "high_52w": 210.0,
            "data_points": 252,
        },
    },
    {
        "ticker": "SPY",
        "rank": None,
        "action": "BENCHMARK",
        "score": 83.8,
        "base_score": 83.8,
        "latest_score": 84.0,
        "is_benchmark": True,
        "tags": [],
        "metrics": {"current_price": 773.5, "change_5d": 1.9},
    },
]

CONFIG = {
    "scoring": {
        "smoothing_days": 40,
        "selection": {"mode": "rank", "top_n": 8, "bench_n": 3},
        "weights": {"long_term_trend": 25},
        "thresholds": {"watch": 50},
    },
    "features": {"macro_overlay": False},
}


def _snap():
    return build_snapshot(RESULTS, CONFIG, "2026-09-22 22:00 UTC")


def test_one_row_per_ticker():
    snap = _snap()
    assert [r["ticker"] for r in snap["rows"]] == ["ANET", "SPY"]


def test_row_carries_decision_and_inputs():
    row = _snap()["rows"][0]
    assert row["rank"] == 1
    assert row["action"] == "ADD SIGNAL"
    assert row["score"] == 87.1
    assert row["latest_score"] == 91.4       # raw, alongside the smoothed value
    assert row["current_price"] == 205.42
    assert row["pct_below_52w_high"] == 2.4
    assert row["tags"] == ["earnings in 3d"]


def test_benchmarks_are_kept_and_marked():
    """Benchmarks are the comparison series — dropping them loses the yardstick."""
    row = _snap()["rows"][1]
    assert row["is_benchmark"] is True
    assert row["rank"] is None


def test_rules_are_recorded_with_the_rows():
    """A score is uninterpretable later without the config that produced it."""
    rules = _snap()["rules"]
    assert rules["smoothing_days"] == 40
    assert rules["selection"]["top_n"] == 8
    assert rules["weights"] == {"long_term_trend": 25}
    assert rules["features"] == {"macro_overlay": False}


def test_missing_metrics_become_null_not_an_error():
    row = _snap()["rows"][1]
    assert row["ma200"] is None


def test_snapshot_is_json_serialisable():
    import json

    assert json.loads(json.dumps(_snap()))["schema"] == 2


def test_coverage_is_recorded_so_missing_cannot_be_mistaken_for_unrequested():
    cov = {
        "requested": ["ANET", "SPY", "MU"],
        "fetched": ["ANET", "SPY"],
        "missing": ["MU"],
        "complete": False,
        "degraded": True,
    }
    snap = build_snapshot(RESULTS, CONFIG, "2026-11-12 22:00 UTC", coverage=cov)
    assert snap["coverage"]["missing"] == ["MU"]
    assert snap["coverage"]["complete"] is False


def test_coverage_defaults_to_complete_when_not_supplied():
    snap = build_snapshot(RESULTS, CONFIG, "2026-11-12 22:00 UTC")
    assert snap["coverage"]["complete"] is True
    assert snap["coverage"]["missing"] == []
