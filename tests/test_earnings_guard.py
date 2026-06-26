from src.scoring.actions import Action
from src.scoring.earnings_guard import apply_earnings_guard

WINDOW = 5


def test_caps_strong_signal_near_earnings():
    action, tag = apply_earnings_guard(Action.ADD, 2, WINDOW)
    assert action is Action.WATCH
    assert "earnings in 2d" in tag


def test_starter_also_capped():
    action, tag = apply_earnings_guard(Action.STARTER, 0, WINDOW)
    assert action is Action.WATCH
    assert tag is not None


def test_outside_window_untouched():
    action, tag = apply_earnings_guard(Action.ADD, 10, WINDOW)
    assert action is Action.ADD
    assert tag is None


def test_unknown_date_passes_through():
    action, tag = apply_earnings_guard(Action.ADD, None, WINDOW)
    assert action is Action.ADD
    assert tag is None


def test_does_not_upgrade_weak_actions():
    # A guard never makes an action *stronger*.
    action, tag = apply_earnings_guard(Action.AVOID, 1, WINDOW)
    assert action is Action.AVOID
    assert tag is not None
