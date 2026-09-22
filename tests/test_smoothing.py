from src.scoring.score import score_metrics
from src.scoring.smoothing import score_history, smoothed_score
from src.scoring.technicals import compute_metrics

# A long, steady uptrend: every day's score should be similar, so the mean of the
# window lands close to the latest reading.
TREND = [float(i) for i in range(100, 500)]


def test_history_returns_one_score_per_session(config):
    history = score_history(TREND, config, days=10, lookback=252)
    assert len(history) == 10


def test_history_is_oldest_to_newest(config):
    history = score_history(TREND, config, days=5, lookback=252)
    latest = score_metrics(compute_metrics(TREND[-252:]), config)["score"]
    assert history[-1] == latest


def test_each_day_uses_its_own_lookback_not_all_history(config):
    """Extra history must not leak into a past day's 52-week high."""
    # Day -1 scored directly on a 252-session window...
    expected = score_metrics(compute_metrics(TREND[:-1][-252:]), config)["score"]
    # ...must match what score_history produces for that same session.
    history = score_history(TREND, config, days=2, lookback=252)
    assert history[0] == expected


def test_smoothing_averages_the_window(config):
    history = score_history(TREND, config, days=20, lookback=252)
    assert smoothed_score(TREND, config, days=20) == sum(history) / len(history)


def test_smoothing_damps_a_one_day_spike(config):
    """A single violent session moves the smoothed score far less than the raw one."""
    spiked = TREND + [TREND[-1] * 1.5]
    raw_before = score_metrics(compute_metrics(TREND[-252:]), config)["score"]
    raw_after = score_metrics(compute_metrics(spiked[-252:]), config)["score"]
    smooth_before = smoothed_score(TREND, config, days=40)
    smooth_after = smoothed_score(spiked, config, days=40)
    assert abs(raw_after - raw_before) > abs(smooth_after - smooth_before)


def test_days_of_one_is_the_raw_latest_score(config):
    latest = score_metrics(compute_metrics(TREND[-252:]), config)["score"]
    assert smoothed_score(TREND, config, days=1) == latest


def test_short_history_uses_what_exists(config):
    short = TREND[:12]
    history = score_history(short, config, days=40, lookback=252)
    assert len(history) == 12
    assert smoothed_score(short, config, days=40) is not None


def test_empty_series_returns_none(config):
    assert smoothed_score([], config) is None
    assert score_history([], config, days=10, lookback=252) == []
