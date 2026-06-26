from src.scoring.regimes import active_regimes, macro_tilt, ticker_themes

REGIMES = [
    {
        "name": "energy_tailwind",
        "series": "CL=F",
        "change_pct": 10,
        "direction": "up",
        "themes": ["energy"],
        "tilt": 8,
        "tag": "Energy regime",
    },
    {
        "name": "risk_off",
        "series": "^VIX",
        "change_pct": 30,
        "direction": "up",
        "themes": ["*"],
        "tilt": -6,
        "tag": "Risk-off",
    },
]
THEMES = {"energy": ["XOM", "OXY"], "ai_memory": ["MU"]}


def test_active_regimes_threshold():
    # Oil up 14% triggers energy; VIX flat does not trigger risk-off.
    active = active_regimes({"CL=F": 14.0, "^VIX": 5.0}, REGIMES)
    assert [r["name"] for r in active] == ["energy_tailwind"]


def test_missing_series_is_inactive():
    assert active_regimes({}, REGIMES) == []


def test_ticker_themes():
    assert ticker_themes("XOM", THEMES) == {"energy"}
    assert ticker_themes("AAPL", THEMES) == set()


def test_macro_tilt_themed_and_wildcard():
    active = active_regimes({"CL=F": 20.0, "^VIX": 40.0}, REGIMES)
    # XOM is energy (gets +8) and everything gets risk-off (-6) => +2
    tilt, tags = macro_tilt("XOM", active, THEMES, cap=8)
    assert tilt == 2
    assert "Energy regime" in tags and "Risk-off" in tags
    # MU is not energy, only the wildcard risk-off applies => -6
    tilt_mu, tags_mu = macro_tilt("MU", active, THEMES, cap=8)
    assert tilt_mu == -6
    assert tags_mu == ["Risk-off"]


def test_macro_tilt_clamped_to_cap():
    big = [{"series": "X", "change_pct": 1, "direction": "up", "themes": ["*"], "tilt": 50}]
    active = active_regimes({"X": 5}, big)
    tilt, _ = macro_tilt("ANY", active, {}, cap=8)
    assert tilt == 8
