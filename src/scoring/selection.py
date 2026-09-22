"""Turn a scored, sorted watchlist into action tiers.

Two modes:

``threshold`` (v1) asks "is this score above 65?". Because every score falls
together in a drawdown, the size of the flagged set tracks the market's mood
rather than the quality of what is on offer — the report empties out at exactly
the moment the setups it is meant to find are forming.

``rank`` asks "is this one of the best N setups available right now?". The
flagged set is the same size every day, so the report never empties and never
round-trips a fixed line as a score drifts across it.

Pure: takes rows and config, returns actions. No IO, no mutation.
"""

from __future__ import annotations

from typing import Sequence

from src.scoring.actions import Action, action_for_score

DEFAULT_TOP_N = 8
DEFAULT_BENCH_N = 3


def assign_actions(rows: Sequence[dict], scoring_cfg: dict) -> list[Action]:
    """Actions for ``rows``, which must already be sorted by score descending.

    Returns one :class:`Action` per row, in the same order. The caller is
    responsible for any later capping (e.g. the earnings guard).
    """
    thresholds = scoring_cfg.get("thresholds", {}) or {}
    selection = scoring_cfg.get("selection", {}) or {}
    mode = selection.get("mode", "rank")

    if mode != "rank":
        return [
            Action.BENCHMARK
            if r.get("is_benchmark")
            else action_for_score(r["score"], thresholds)
            for r in rows
        ]

    top_n = int(selection.get("top_n", DEFAULT_TOP_N))
    bench_n = int(selection.get("bench_n", DEFAULT_BENCH_N))
    watch_floor = thresholds.get("watch", 50)

    actions: list[Action] = []
    rank = 0
    for row in rows:
        # Benchmarks are scored for context but must never consume a slot.
        if row.get("is_benchmark"):
            actions.append(Action.BENCHMARK)
            continue
        rank += 1
        if rank <= top_n:
            actions.append(Action.ADD)
        elif rank <= top_n + bench_n:
            actions.append(Action.STARTER)
        elif row["score"] >= watch_floor:
            actions.append(Action.WATCH)
        else:
            actions.append(Action.AVOID)
    return actions
