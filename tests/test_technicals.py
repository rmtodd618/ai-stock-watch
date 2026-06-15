from src.scoring.technicals import compute_metrics


def test_empty_returns_none():
    assert compute_metrics([]) is None
    assert compute_metrics([None, None]) is None


def test_basic_metrics():
    closes = [float(i) for i in range(1, 251)]  # 1..250, steadily rising
    m = compute_metrics(closes)
    assert m["current_price"] == 250.0
    assert m["data_points"] == 250
    assert m["high_52w"] == 250.0
    assert m["pct_below_52w_high"] == 0.0
    # 5-day change: from 245 -> 250
    assert m["change_5d"] == (250 - 245) / 245 * 100


def test_moving_averages_need_enough_history():
    closes = [100.0] * 60  # flat
    m = compute_metrics(closes)
    assert m["ma50"] == 100.0
    assert m["ma200"] is None  # only 60 points
    assert m["pct_below_52w_high"] == 0.0


def test_pct_below_high_after_pullback():
    closes = [100.0] * 50 + [80.0]  # peaked at 100, now 80
    m = compute_metrics(closes)
    assert m["high_52w"] == 100.0
    assert m["pct_below_52w_high"] == 20.0
