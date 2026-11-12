from src.reporting.changes import compute_changes, summary_line


def row(t, rank=None, action="WATCH"):
    return {"ticker": t, "rank": rank, "action": action}


def snap(rows, date="2026-11-10 22:01 UTC"):
    return {"generated_at": date, "rows": rows}


TODAY = [
    row("A", 1, "ADD SIGNAL"),
    row("B", 2, "ADD SIGNAL"),
    row("C", 3, "STARTER SIGNAL"),
    row("SPY", None, "BENCHMARK"),
]
YESTERDAY = snap([
    row("A", 2, "ADD SIGNAL"),
    row("C", 1, "ADD SIGNAL"),
    row("B", 3, "STARTER SIGNAL"),
    row("SPY", None, "BENCHMARK"),
])


def test_detects_what_entered_and_left():
    c = compute_changes(TODAY, YESTERDAY)
    assert c["entered"] == ["B"]
    assert c["left"] == ["C"]


def test_rank_delta_is_positive_when_a_name_moves_up():
    c = compute_changes(TODAY, YESTERDAY)
    assert c["deltas"]["A"] == 1     # was 2, now 1
    assert c["deltas"]["B"] == 1     # was 3, now 2
    assert c["deltas"]["C"] == -2    # was 1, now 3


def test_benchmarks_have_no_rank_and_no_delta():
    assert "SPY" not in compute_changes(TODAY, YESTERDAY)["deltas"]


def test_a_newly_listed_name_has_no_delta():
    today = TODAY + [{"ticker": "NEW", "rank": None, "action": "NOT ENOUGH HISTORY"}]
    assert "NEW" not in compute_changes(today, YESTERDAY)["deltas"]


def test_records_which_date_it_compared_against():
    assert compute_changes(TODAY, YESTERDAY)["previous_date"] == "2026-11-10"


def test_no_history_is_not_the_same_as_no_change():
    """The distinction matters: a broken pipeline must not read as 'all calm'."""
    for missing in (None, {}, {"rows": []}, {"rows": "nonsense"}):
        c = compute_changes(TODAY, missing)
        assert c["comparable"] is False
        assert c["entered"] == [] and c["left"] == []


def test_identical_days_are_comparable_and_quiet():
    c = compute_changes(TODAY, snap(TODAY))
    assert c["comparable"] is True
    assert c["entered"] == [] and c["left"] == []
    assert all(v == 0 for v in c["deltas"].values())


# --- summary line --------------------------------------------------------------

def test_summary_names_the_movers():
    s = summary_line(TODAY, compute_changes(TODAY, YESTERDAY))
    assert "2 in the portfolio" in s
    assert "1 in (B)" in s and "1 out (C)" in s


def test_summary_says_unchanged_when_nothing_moved():
    s = summary_line(TODAY, compute_changes(TODAY, snap(TODAY)))
    assert "unchanged since" in s


def test_summary_is_explicit_when_there_is_no_history():
    s = summary_line(TODAY, compute_changes(TODAY, None))
    assert "no earlier report" in s
