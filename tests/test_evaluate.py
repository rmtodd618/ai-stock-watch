import pytest

from src.evaluate import (
    forward_return,
    portfolio,
    rank_ic,
    spearman,
    tier_returns,
)

SESSIONS = [f"2026-01-{d:02d}" for d in range(1, 11)]


def _flat(start=100.0, step=0.0):
    return {d: start + i * step for i, d in enumerate(SESSIONS)}


# --- spearman -----------------------------------------------------------------

def test_perfect_agreement_is_one():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_perfect_disagreement_is_minus_one():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_constant_input_is_undefined_not_zero():
    """A flat series has no ordering; returning 0 would look like a real result."""
    assert spearman([5, 5, 5, 5], [1, 2, 3, 4]) is None


def test_too_few_points_is_undefined():
    assert spearman([1, 2], [2, 1]) is None


def test_ties_are_averaged():
    assert spearman([1, 1, 2], [1, 1, 2]) == pytest.approx(1.0)


# --- forward returns -----------------------------------------------------------

def test_forward_return_spans_the_horizon():
    prices = {d: 100.0 + i for i, d in enumerate(SESSIONS)}
    assert forward_return(prices, SESSIONS, "2026-01-01", 5) == pytest.approx(5 / 100)


def test_forward_return_past_the_end_is_none_not_zero():
    """An unfinished horizon must not be scored as a flat return."""
    prices = {d: 100.0 for d in SESSIONS}
    assert forward_return(prices, SESSIONS, "2026-01-09", 5) is None


def test_forward_return_for_unknown_session_is_none():
    assert forward_return({}, SESSIONS, "1999-01-01", 1) is None


# --- rank IC -------------------------------------------------------------------

def _snap(session, scored):
    return {
        "generated_at": session,
        "rows": [
            {"ticker": t, "score": s, "action": "ADD SIGNAL", "is_benchmark": False}
            for t, s in scored.items()
        ],
    }


def test_rank_ic_detects_a_perfect_signal():
    """Scores that rank forward returns exactly should give IC = 1."""
    tickers = list("ABCDEF")
    prices = {
        t: {d: 100.0 * (1 + 0.01 * i) ** j for j, d in enumerate(SESSIONS)}
        for i, t in enumerate(tickers)
    }
    snaps = [_snap("2026-01-01", {t: float(i) for i, t in enumerate(tickers)})]
    out = rank_ic(snaps, prices, SESSIONS, horizon=5)
    assert out["mean_ic"] == pytest.approx(1.0)
    assert out["sessions"] == 1


def test_rank_ic_detects_an_inverted_signal():
    tickers = list("ABCDEF")
    prices = {
        t: {d: 100.0 * (1 + 0.01 * i) ** j for j, d in enumerate(SESSIONS)}
        for i, t in enumerate(tickers)
    }
    snaps = [_snap("2026-01-01", {t: float(-i) for i, t in enumerate(tickers)})]
    assert rank_ic(snaps, prices, SESSIONS, horizon=5)["mean_ic"] == pytest.approx(-1.0)


def test_rank_ic_ignores_benchmarks():
    """SPY must not be ranked against the names it exists to benchmark."""
    tickers = list("ABCDEF")
    # Distinct trajectories — identical ones leave the returns constant, which
    # is genuinely undefined for a rank correlation.
    prices = {t: _flat(100.0, float(i + 1)) for i, t in enumerate(tickers)}
    prices["SPY"] = _flat(400.0, 1.0)
    snap = _snap("2026-01-01", {t: float(i) for i, t in enumerate(tickers)})
    snap["rows"].append(
        {"ticker": "SPY", "score": 99.0, "action": "BENCHMARK", "is_benchmark": True}
    )
    # 6 real names remain, so the session still counts
    assert rank_ic([snap], prices, SESSIONS, horizon=2)["sessions"] == 1


def test_rank_ic_skips_sessions_with_too_few_names():
    prices = {t: _flat(100.0, 1.0) for t in "AB"}
    snaps = [_snap("2026-01-01", {"A": 1.0, "B": 2.0})]
    assert rank_ic(snaps, prices, SESSIONS, horizon=2)["sessions"] == 0


def test_rank_ic_with_no_usable_data_reports_none():
    assert rank_ic([], {}, SESSIONS)["mean_ic"] is None


# --- tier returns ---------------------------------------------------------------

def test_tier_returns_separates_actions_and_keeps_a_baseline():
    prices = {"UP": _flat(100.0, 10.0), "DOWN": _flat(100.0, -5.0)}
    snap = {
        "generated_at": "2026-01-01",
        "rows": [
            {"ticker": "UP", "action": "ADD SIGNAL", "is_benchmark": False},
            {"ticker": "DOWN", "action": "AVOID FOR NOW", "is_benchmark": False},
        ],
    }
    out = tier_returns([snap], prices, SESSIONS, horizon=2)
    assert out["ADD SIGNAL"]["mean_return"] > 0
    assert out["AVOID FOR NOW"]["mean_return"] < 0
    assert out["ALL (baseline)"]["n"] == 2


# --- portfolio -------------------------------------------------------------------

def _portfolio_snaps(action_for):
    return [
        {
            "generated_at": d,
            "rows": [
                {"ticker": t, "action": action_for(t), "is_benchmark": False}
                for t in ("UP", "DOWN")
            ],
        }
        for d in SESSIONS
    ]


def test_portfolio_holding_the_winner_beats_the_watchlist():
    prices = {
        "UP": {d: 100.0 * (1.02 ** i) for i, d in enumerate(SESSIONS)},
        "DOWN": {d: 100.0 * (0.98 ** i) for i, d in enumerate(SESSIONS)},
        "SPY": _flat(400.0),
    }
    snaps = _portfolio_snaps(lambda t: "ADD SIGNAL" if t == "UP" else "AVOID FOR NOW")
    out = portfolio(snaps, prices, SESSIONS, cost_bps=0)
    assert out["strategy_return"] > out["watchlist_return"]
    assert out["excess_vs_watchlist"] > 0
    assert out["avg_held"] == 1.0


def test_portfolio_holding_the_loser_trails_the_watchlist():
    prices = {
        "UP": {d: 100.0 * (1.02 ** i) for i, d in enumerate(SESSIONS)},
        "DOWN": {d: 100.0 * (0.98 ** i) for i, d in enumerate(SESSIONS)},
        "SPY": _flat(400.0),
    }
    snaps = _portfolio_snaps(lambda t: "ADD SIGNAL" if t == "DOWN" else "AVOID FOR NOW")
    out = portfolio(snaps, prices, SESSIONS, cost_bps=0)
    assert out["excess_vs_watchlist"] < 0


def test_portfolio_charges_turnover():
    """Flipping the held name every session must cost more than holding it."""
    prices = {
        "UP": {d: 100.0 * (1.01 ** i) for i, d in enumerate(SESSIONS)},
        "DOWN": {d: 100.0 * (1.01 ** i) for i, d in enumerate(SESSIONS)},
        "SPY": _flat(400.0),
    }
    steady = _portfolio_snaps(lambda t: "ADD SIGNAL" if t == "UP" else "WATCH")
    flipping = [
        {
            "generated_at": d,
            "rows": [
                {
                    "ticker": t,
                    "action": "ADD SIGNAL"
                    if t == ("UP" if i % 2 == 0 else "DOWN")
                    else "WATCH",
                    "is_benchmark": False,
                }
                for t in ("UP", "DOWN")
            ],
        }
        for i, d in enumerate(SESSIONS)
    ]
    a = portfolio(steady, prices, SESSIONS, cost_bps=50)
    b = portfolio(flipping, prices, SESSIONS, cost_bps=50)
    assert b["strategy_return"] < a["strategy_return"]
    assert b["annualised_turnover"] > a["annualised_turnover"]


def test_portfolio_with_nothing_held_is_flat():
    prices = {"UP": _flat(100.0, 5.0), "DOWN": _flat(100.0, -5.0), "SPY": _flat(400.0)}
    snaps = _portfolio_snaps(lambda t: "AVOID FOR NOW")
    out = portfolio(snaps, prices, SESSIONS, cost_bps=0)
    assert out["strategy_return"] == pytest.approx(0.0)


def test_portfolio_needs_two_sessions():
    assert portfolio([], {}, SESSIONS)["sessions"] == 0


# --- coverage gating -----------------------------------------------------------

from src.evaluate import drop_incomplete, is_complete  # noqa: E402


def test_a_session_missing_part_of_its_universe_is_not_an_observation():
    bad = {"generated_at": "2026-11-12", "coverage": {"complete": False}}
    assert is_complete(bad) is False


def test_a_full_session_is_usable():
    good = {"generated_at": "2026-11-12", "coverage": {"complete": True}}
    assert is_complete(good) is True


def test_snapshots_predating_coverage_are_kept():
    """Schema 1 rows cannot say; discarding the whole existing record is worse."""
    assert is_complete({"generated_at": "2026-10-08"}) is True
    assert is_complete({"generated_at": "2026-10-08", "coverage": None}) is True


def test_drop_incomplete_reports_which_dates_went():
    snaps = [
        {"generated_at": "2026-11-10", "coverage": {"complete": True}},
        {"generated_at": "2026-11-11", "coverage": {"complete": False}},
        {"generated_at": "2026-11-12"},
    ]
    keep, dropped = drop_incomplete(snaps)
    assert [s["generated_at"] for s in keep] == ["2026-11-10", "2026-11-12"]
    assert dropped == ["2026-11-11"]
