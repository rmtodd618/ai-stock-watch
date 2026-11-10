from src.scoring.actions import Action
from src.scoring.selection import assign_actions


def _rows(*scores):
    """Rows sorted by score descending, as build_results hands them over."""
    return [{"ticker": f"T{i}", "score": s} for i, s in enumerate(scores)]


def _cfg(mode="rank", top_n=3, bench_n=1, watch=50):
    return {
        "selection": {"mode": mode, "top_n": top_n, "bench_n": bench_n},
        "thresholds": {"add": 80, "starter": 65, "watch": watch},
    }


def test_rank_mode_flags_the_top_n_regardless_of_level():
    # Every score is far below the v1 "add" threshold of 80.
    actions = assign_actions(_rows(41, 39, 37, 35, 20), _cfg())
    assert actions[:3] == [Action.ADD, Action.ADD, Action.ADD]


def test_rank_mode_bench_then_watch_then_avoid():
    actions = assign_actions(_rows(90, 85, 80, 70, 55, 30), _cfg())
    assert actions == [
        Action.ADD, Action.ADD, Action.ADD,   # top_n = 3
        Action.STARTER,                        # bench_n = 1
        Action.WATCH,                          # >= watch floor
        Action.AVOID,                          # below it
    ]


def test_rank_mode_never_empties_in_a_drawdown():
    """The whole field collapsing must not empty the portfolio — that is the bug."""
    crashed = _rows(12, 10, 9, 8, 4)
    actions = assign_actions(crashed, _cfg())
    assert sum(a is Action.ADD for a in actions) == 3


def test_rank_mode_handles_fewer_names_than_top_n():
    actions = assign_actions(_rows(70, 60), _cfg(top_n=8))
    assert actions == [Action.ADD, Action.ADD]


def test_threshold_mode_preserves_v1_behaviour():
    actions = assign_actions(_rows(90, 70, 55, 30), _cfg(mode="threshold"))
    assert actions == [Action.ADD, Action.STARTER, Action.WATCH, Action.AVOID]


def test_threshold_mode_can_flag_nothing():
    actions = assign_actions(_rows(12, 10, 9), _cfg(mode="threshold"))
    assert all(a is Action.AVOID for a in actions)


def test_defaults_apply_when_selection_block_missing():
    actions = assign_actions(_rows(*range(90, 70, -1)), {"thresholds": {"watch": 50}})
    assert sum(a is Action.ADD for a in actions) == 8  # DEFAULT_TOP_N


def test_benchmarks_never_take_a_slot():
    rows = [
        {"ticker": "SPY", "score": 95, "is_benchmark": True},
        {"ticker": "A", "score": 90},
        {"ticker": "QQQ", "score": 88, "is_benchmark": True},
        {"ticker": "B", "score": 70},
        {"ticker": "C", "score": 60},
        {"ticker": "D", "score": 55},
    ]
    actions = assign_actions(rows, _cfg(top_n=2, bench_n=1))
    assert actions == [
        Action.BENCHMARK,  # SPY outscores everything and is still skipped
        Action.ADD,        # A is rank 1
        Action.BENCHMARK,
        Action.ADD,        # B is rank 2, not rank 4
        Action.STARTER,    # C is rank 3
        Action.WATCH,
    ]


def test_benchmarks_are_labelled_in_threshold_mode_too():
    rows = [{"ticker": "SPY", "score": 95, "is_benchmark": True}, {"ticker": "A", "score": 90}]
    actions = assign_actions(rows, _cfg(mode="threshold"))
    assert actions == [Action.BENCHMARK, Action.ADD]


def test_recent_listings_never_take_a_slot():
    """A six-session-old IPO scores ~50 on placeholders; rank mode must skip it."""
    rows = [
        {"ticker": "NEWCO", "score": 90, "insufficient_history": True},
        {"ticker": "A", "score": 70},
        {"ticker": "B", "score": 60},
        {"ticker": "C", "score": 55},
    ]
    actions = assign_actions(rows, _cfg(top_n=2, bench_n=0))
    assert actions == [Action.INSUFFICIENT, Action.ADD, Action.ADD, Action.WATCH]


def test_recent_listings_are_flagged_in_threshold_mode_too():
    rows = [{"ticker": "NEWCO", "score": 90, "insufficient_history": True}]
    assert assign_actions(rows, _cfg(mode="threshold")) == [Action.INSUFFICIENT]
