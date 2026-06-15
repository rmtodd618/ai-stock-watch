from src.scoring.score import _pullback_component, _ramp, score_metrics


def test_ramp_clamps():
    assert _ramp(0.90, 0.95, 1.05) == 0.0
    assert _ramp(1.10, 0.95, 1.05) == 1.0
    assert _ramp(1.00, 0.95, 1.05) == 0.5


def test_pullback_tent():
    # at highs -> 0.5, sweet spot -> 1.0, broken -> 0.0
    assert _pullback_component(0, 8, 20, 45) == 0.5
    assert _pullback_component(12, 8, 20, 45) == 1.0
    assert _pullback_component(50, 8, 20, 45) == 0.0
    # developing dip ramps up; deep dip ramps down
    assert 0.5 < _pullback_component(4, 8, 20, 45) < 1.0
    assert 0.0 < _pullback_component(35, 8, 20, 45) < 1.0


def test_strong_uptrend_scores_high(config):
    # Price above both MAs, golden-cross posture, healthy ~12% dip, calm momentum.
    metrics = {
        "current_price": 110.0,
        "change_5d": -1.0,
        "change_30d": 5.0,
        "ma50": 105.0,
        "ma200": 95.0,
        "high_52w": 125.0,
        "pct_below_52w_high": 12.0,
    }
    result = score_metrics(metrics, config)
    assert result["score"] >= 80
    # breakdown points sum (approximately) to the score
    assert abs(sum(result["breakdown"].values()) - result["score"]) < 1.0


def test_broken_downtrend_scores_low(config):
    metrics = {
        "current_price": 50.0,
        "change_5d": -15.0,      # falling knife
        "change_30d": -40.0,
        "ma50": 70.0,            # price well below 50MA
        "ma200": 90.0,           # and below 200MA; 50<200 (death cross)
        "high_52w": 120.0,
        "pct_below_52w_high": 58.0,  # broken
    }
    result = score_metrics(metrics, config)
    assert result["score"] < 25


def test_missing_long_history_is_neutral_not_crash(config):
    # No MA200 yet (short history) -> trend components fall back to neutral.
    metrics = {
        "current_price": 100.0,
        "change_5d": 0.0,
        "change_30d": None,
        "ma50": 100.0,
        "ma200": None,
        "high_52w": 105.0,
        "pct_below_52w_high": 4.76,
    }
    result = score_metrics(metrics, config)
    assert 0 <= result["score"] <= 100
    assert result["components"]["long_term_trend"] == 0.5
