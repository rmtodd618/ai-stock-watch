from datetime import date

import pytest

from src.portfolio import (
    current_weights,
    net_asset_value,
    realised_gain,
    rebalance,
    summary_line,
    target_weights,
)

PRICES = {"AAA": 100.0, "BBB": 50.0, "CCC": 25.0, "DDD": 10.0}
TODAY = date(2026, 11, 13)


def holdings(**kw):
    base = {
        "cash": 1000.0,
        "positions": {
            "AAA": {"shares": 40, "cost_basis": 80.0, "acquired": "2026-09-01"},
            "BBB": {"shares": 40, "cost_basis": 60.0, "acquired": "2024-01-02"},
        },
    }
    base.update(kw)
    return base


def model(*tickers):
    return [{"ticker": t, "action": "ADD SIGNAL"} for t in tickers] + [
        {"ticker": "ZZZ", "action": "AVOID FOR NOW"},
        {"ticker": "SPY", "action": "BENCHMARK"},
    ]


# --- valuation -----------------------------------------------------------------

def test_nav_is_positions_plus_cash():
    assert net_asset_value(holdings(), PRICES) == 40 * 100 + 40 * 50 + 1000


def test_weights_are_fractions_of_nav():
    w = current_weights(holdings(), PRICES)
    assert w["AAA"] == pytest.approx(4000 / 7000)
    assert w["BBB"] == pytest.approx(2000 / 7000)


def test_cash_is_not_a_position():
    assert "cash" not in current_weights(holdings(), PRICES)


def test_unpriced_position_is_skipped_not_valued_at_zero():
    h = holdings(positions={"AAA": {"shares": 10}, "NOPRICE": {"shares": 99}})
    assert set(current_weights(h, PRICES)) == {"AAA"}


def test_empty_portfolio_has_no_weights():
    assert current_weights({"cash": 0, "positions": {}}, PRICES) == {}


# --- the model side -------------------------------------------------------------

def test_target_is_equal_weight_across_flagged_names_only():
    assert target_weights(model("AAA", "BBB", "CCC")) == {
        "AAA": pytest.approx(1 / 3), "BBB": pytest.approx(1 / 3), "CCC": pytest.approx(1 / 3)
    }


def test_benchmarks_and_avoids_are_not_targets():
    t = target_weights(model("AAA"))
    assert "SPY" not in t and "ZZZ" not in t


def test_no_flagged_names_means_no_targets():
    assert target_weights(model()) == {}


# --- realised gains --------------------------------------------------------------

def test_recent_purchase_is_short_term():
    gain, term = realised_gain("AAA", 1000.0, holdings(), PRICES, TODAY)
    assert term == "short"
    assert gain == pytest.approx(10 * (100 - 80))     # $1000 / $100 = 10 shares


def test_old_purchase_is_long_term():
    _, term = realised_gain("BBB", 500.0, holdings(), PRICES, TODAY)
    assert term == "long"


def test_missing_cost_basis_is_unknown_not_zero_gain():
    h = holdings(positions={"AAA": {"shares": 10}})
    gain, term = realised_gain("AAA", 500.0, h, PRICES, TODAY)
    assert term == "unknown" and gain == 0.0


# --- rebalancing ------------------------------------------------------------------

def test_drift_inside_the_band_is_not_actionable():
    """The whole point of the band: small gaps are noise, and trading them is the
    behaviour the backtest punished."""
    h = {"cash": 0.0, "positions": {"AAA": {"shares": 50}, "BBB": {"shares": 100}}}
    # 5000 / 5000 -> exactly 50/50, which is the target
    plan = rebalance(h, model("AAA", "BBB"), PRICES, band=0.02)
    assert plan["actionable"] == []
    assert "Nothing to do" in summary_line(plan)


def test_a_missing_name_shows_as_a_buy():
    plan = rebalance(holdings(), model("AAA", "CCC"), PRICES, band=0.02, today=TODAY)
    ccc = next(r for r in plan["rows"] if r["ticker"] == "CCC")
    assert ccc["current"] == 0.0
    assert ccc["dollars"] > 0 and ccc["actionable"]
    assert ccc["shares"] == pytest.approx(ccc["dollars"] / 25.0)


def test_a_name_the_model_dropped_shows_as_a_full_sell():
    plan = rebalance(holdings(), model("AAA"), PRICES, band=0.02, today=TODAY)
    bbb = next(r for r in plan["rows"] if r["ticker"] == "BBB")
    assert bbb["target"] == 0.0
    assert bbb["dollars"] < 0


def test_sells_carry_the_gain_they_realise():
    """BBB is underwater in the fixture (basis 60, price 50), so selling it
    realises a loss. A sign error here would quietly misreport the tax effect
    of every exit, so the sign is the thing worth asserting."""
    plan = rebalance(holdings(), model("AAA"), PRICES, band=0.02, today=TODAY)
    bbb = next(r for r in plan["rows"] if r["ticker"] == "BBB")
    assert bbb["realised_gain"] < 0
    assert bbb["term"] == "long"
    assert plan["realised_long"] < 0


def test_a_profitable_sell_realises_a_gain():
    h = holdings(positions={"AAA": {"shares": 40, "cost_basis": 80.0,
                                    "acquired": "2026-09-01"}})
    plan = rebalance(h, model("CCC"), PRICES, band=0.02, today=TODAY)
    aaa = next(r for r in plan["rows"] if r["ticker"] == "AAA")
    assert aaa["realised_gain"] > 0
    assert aaa["term"] == "short"
    assert plan["realised_short"] > 0


def test_cost_scales_with_what_you_trade():
    plan = rebalance(holdings(), model("CCC", "DDD"), PRICES, band=0.0, spread_bps=20.0,
                     today=TODAY)
    assert plan["spread_cost"] == pytest.approx(plan["turnover_dollars"] * 20 / 1e4)
    assert plan["spread_cost"] > 0


def test_summary_prices_the_move_rather_than_urging_it():
    plan = rebalance(holdings(), model("CCC"), PRICES, band=0.02, today=TODAY)
    s = summary_line(plan)
    assert "to trade" in s and "spread" in s
    for word in ("buy", "sell", "should", "recommend"):
        assert word not in s.lower()


def test_no_holdings_says_so_plainly():
    plan = rebalance({"cash": 0, "positions": {}}, model("AAA"), PRICES)
    assert "No holdings recorded" in summary_line(plan)


def test_a_negative_gain_is_called_a_loss():
    """Short- and long-term losses have the opposite tax effect of gains;
    printing one as the other is worse than printing nothing."""
    h = holdings(positions={"BBB": {"shares": 40, "cost_basis": 60.0,
                                    "acquired": "2024-01-02"}})
    plan = rebalance(h, model("CCC"), PRICES, band=0.02, today=TODAY)
    s = summary_line(plan)
    assert "long-term loss realised" in s
    assert "gain" not in s


def test_a_positive_gain_is_called_a_gain():
    h = holdings(positions={"AAA": {"shares": 40, "cost_basis": 80.0,
                                    "acquired": "2026-09-01"}})
    plan = rebalance(h, model("CCC"), PRICES, band=0.02, today=TODAY)
    assert "short-term gain realised" in summary_line(plan)
