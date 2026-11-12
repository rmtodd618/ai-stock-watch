"""What moved since the last report.

A daily email that looks identical every day teaches you to stop reading it.
The useful content is not the table — it is the handful of rows that changed:
what entered the flagged set, what dropped out, and which way the rest moved.

Pure: today's rows and yesterday's snapshot in, a summary out. No IO.
"""

from __future__ import annotations

from typing import Optional

HELD = "ADD SIGNAL"


def _ranked(rows: list[dict]) -> dict[str, int]:
    """Ticker -> rank, for rows that carry one (benchmarks and new listings do not)."""
    return {
        r["ticker"]: r["rank"]
        for r in rows
        if r.get("rank") is not None and r.get("ticker")
    }


def _held(rows: list[dict]) -> set[str]:
    return {r["ticker"] for r in rows if r.get("action") == HELD and r.get("ticker")}


def compute_changes(results: list[dict], previous: Optional[dict]) -> dict:
    """Compare today's rows against the previous snapshot.

    Returns ``{"entered", "left", "deltas", "previous_date", "comparable"}``.
    ``deltas`` maps ticker -> rank improvement (positive means moved up the
    board). ``comparable`` is False when there is no usable history, which the
    caller should treat as "say nothing" rather than "nothing changed" — those
    are different claims and conflating them is how a broken pipeline looks calm.
    """
    empty = {
        "entered": [],
        "left": [],
        "deltas": {},
        "previous_date": None,
        "comparable": False,
    }
    if not previous or not isinstance(previous.get("rows"), list):
        return empty

    prev_rows = previous["rows"]
    if not prev_rows:
        return empty

    today_rank, prev_rank = _ranked(results), _ranked(prev_rows)
    today_held, prev_held = _held(results), _held(prev_rows)

    deltas: dict[str, int] = {}
    for ticker, rank in today_rank.items():
        was = prev_rank.get(ticker)
        if was is not None:
            # A smaller rank number is better, so improvement is was - now.
            deltas[ticker] = was - rank

    return {
        "entered": sorted(today_held - prev_held),
        "left": sorted(prev_held - today_held),
        "deltas": deltas,
        "previous_date": (previous.get("generated_at") or "")[:10] or None,
        "comparable": True,
    }


def summary_line(results: list[dict], changes: dict) -> str:
    """One sentence for the top of the report and the email subject."""
    held = len(_held(results))
    if not changes.get("comparable"):
        return f"{held} in the portfolio · no earlier report to compare against"

    entered, left = changes["entered"], changes["left"]
    if not entered and not left:
        return f"{held} in the portfolio · unchanged since {changes['previous_date']}"

    parts = []
    if entered:
        parts.append(f"{len(entered)} in ({', '.join(entered)})")
    if left:
        parts.append(f"{len(left)} out ({', '.join(left)})")
    return f"{held} in the portfolio · " + " · ".join(parts)
