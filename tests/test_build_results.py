from src.handler import build_results


def _config():
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
            "tilts": {"macro_max": 8, "sentiment_max": 10},
        },
        "themes": {"energy": ["XOM"]},
        "earnings": {"guard_window_days": 5},
    }


# Strong-uptrend-with-healthy-dip series → high base score.
STRONG = [float(i) for i in range(50, 300)] + [330.0] * 5 + [300.0]


def test_overlays_off_is_plain_score():
    results = build_results(_config(), {"XOM": STRONG})
    r = results[0]
    assert r["base_score"] == r["score"]
    assert r["macro_tilt"] == 0
    assert r["tags"] == []


def test_macro_tilt_raises_score_and_tags():
    regime = [{"series": "CL=F", "themes": ["energy"], "tilt": 8, "tag": "Energy regime"}]
    results = build_results(_config(), {"XOM": STRONG}, active_regimes=regime)
    r = results[0]
    assert r["score"] == round(r["base_score"] + 8, 1)
    assert "Energy regime" in r["tags"]


def test_earnings_guard_caps_action_with_tag():
    results = build_results(
        _config(), {"XOM": STRONG}, earnings_days={"XOM": 2}
    )
    r = results[0]
    assert r["action"] == "WATCH"  # capped despite a strong score
    assert any("earnings in 2d" in t for t in r["tags"])


def test_sentiment_summary_attached():
    sent = {"XOM": {"sentiment": 0.5, "material_catalyst": True, "summary": "Big contract win"}}
    results = build_results(_config(), {"XOM": STRONG}, sentiment=sent)
    r = results[0]
    assert r["sentiment_tilt"] == 5.0  # 0.5 * 10 * 1.0
    assert r["summary"] == "Big contract win"
