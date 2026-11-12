#!/usr/bin/env python3
"""Regenerate the live-record dashboard data from the archived snapshots.

The dashboard is a static page: it carries its data inline, so it shows
whatever was true when it was last built. A page titled "Live Signal Record"
that has quietly stopped updating is worse than no page at all, so this script
exists to make rebuilding it one command rather than a manual exercise.

    python scripts/build_dashboard.py --bucket my-report-bucket --out dash.json
    python scripts/build_dashboard.py --snapshots ./snapshots --out dash.json

It writes the JSON the page expects. Publishing the page itself is a separate
step — see the README.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.config import env  # noqa: E402
from src.data_sources import prices as price_source  # noqa: E402
from src.evaluate import drop_incomplete, forward_return, portfolio, rank_ic  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dashboard")

# Measured over the 2022-2026 backfill; used to size the noise band the live
# result has to clear before it means anything.
TRACKING_ERROR_ANNUAL = 0.229
BACKFILL = {"ic21": 0.103, "ic63": 0.129, "turn": 735, "ir": 0.03}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshots", help="Local directory of snapshot JSON files.")
    src.add_argument("--bucket", help="S3 bucket holding them under --prefix.")
    p.add_argument("--prefix", default="snapshots")
    p.add_argument("--out", default="dash.json", help="Where to write the page data.")
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--cost-bps", type=float, default=20.0)
    return p.parse_args()


def load(args) -> list[dict]:
    if args.snapshots:
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(pathlib.Path(args.snapshots).glob("*.json"))
        ]
    import boto3

    client = boto3.client("s3", region_name=env("AWS_REGION"))
    out = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=args.bucket, Prefix=args.prefix.rstrip("/") + "/"
    ):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                out.append(json.loads(
                    client.get_object(Bucket=args.bucket, Key=obj["Key"])["Body"].read()
                ))
    return out


def main() -> int:
    args = parse_args()
    snaps = [s for s in load(args) if s.get("source", "live") == "live"]
    snaps.sort(key=lambda s: s.get("generated_at", ""))
    snaps, dropped = drop_incomplete(snaps)
    if dropped:
        logger.warning("Excluded %d incomplete session(s): %s",
                       len(dropped), ", ".join(dropped))
    if len(snaps) < 2:
        logger.error("Only %d usable live snapshot(s) — nothing to chart.", len(snaps))
        return 1

    tickers = sorted({r["ticker"] for s in snaps for r in s["rows"] if r.get("ticker")})
    logger.info("Fetching prices for %d tickers …", len(tickers))
    px: dict[str, dict[str, float]] = {}
    for t in tickers:
        got = price_source.fetch_history(t, period="2y")
        if got:
            px[t] = dict(zip(*got))
    if args.benchmark not in px:
        logger.error("Benchmark %s unavailable.", args.benchmark)
        return 1
    sessions = sorted(px[args.benchmark])

    dates = [s["generated_at"][:10] for s in snaps]
    by = {d: s for d, s in zip(dates, snaps)}
    ordered = [d for d in sessions if d in by]

    # Cumulative curves, matching evaluate.portfolio's convention: the weights a
    # snapshot implies earn the following session's return.
    w: dict[str, float] = {}
    cs = cb = cp = 1.0
    curve = [{"d": ordered[0], "tool": 1.0, "watch": 1.0, "spy": 1.0}]
    for prev, today in zip(ordered, ordered[1:]):
        rows = [r for r in by[prev]["rows"] if not r.get("is_benchmark")]
        ret = lambda t: forward_return(px.get(t, {}), sessions, prev, 1)  # noqa: E731
        day = sum(wt * (ret(t) or 0.0) for t, wt in w.items())
        uni = [v for v in (ret(x["ticker"]) for x in rows) if v is not None]
        sel = [r["ticker"] for r in rows if r.get("action") == "ADD SIGNAL"]
        tgt = {t: 1 / len(sel) for t in sel} if sel else {}
        turn = sum(abs(tgt.get(t, 0) - w.get(t, 0)) for t in set(tgt) | set(w))
        cs *= 1 + day - turn * args.cost_bps / 1e4
        cb *= 1 + (sum(uni) / len(uni) if uni else 0.0)
        cp *= 1 + (forward_return(px.get("SPY", {}), sessions, prev, 1) or 0.0)
        w = tgt
        curve.append({"d": today, "tool": round(cs, 5),
                      "watch": round(cb, 5), "spy": round(cp, 5)})

    ever = sorted({r["ticker"] for s in snaps for r in s["rows"]
                   if r.get("rank") and r["rank"] <= 8})
    ranks = {t: [] for t in ever}
    for s in snaps:
        m = {r["ticker"]: r for r in s["rows"]}
        for t in ever:
            ranks[t].append(m.get(t, {}).get("rank"))

    latest = snaps[-1]
    standings = [{
        "t": r["ticker"], "rank": r.get("rank"), "score": r["score"],
        "action": r["action"], "px": r.get("current_price"),
        "c5": r.get("change_5d"), "c30": r.get("change_30d"),
        "below": r.get("pct_below_52w_high"),
        "bench": bool(r.get("is_benchmark")),
        "short": bool(r.get("insufficient_history")),
    } for r in latest["rows"]]

    mom = [(s["generated_at"][:10], s["rules"]["weights"].get("momentum")) for s in snaps]
    switch = next((b[0] for a, b in zip(mom, mom[1:]) if a[1] != b[1]), None)

    perf = portfolio(snaps, px, sessions, cost_bps=args.cost_bps)
    n = perf["sessions"]
    te_window = TRACKING_ERROR_ANNUAL * math.sqrt(n / 252) if n else 0.0

    out = {
        "asof": dates[-1], "first": dates[0], "sessions": len(snaps),
        "curve": curve, "ranks": ranks, "ever": ever, "standings": standings,
        "switch": switch,
        "regime_counts": {"old": sum(1 for _, m_ in mom if m_ == 20),
                          "new": sum(1 for _, m_ in mom if m_ == 0)},
        "perf": {k: (round(v, 2) if isinstance(v, float) else v)
                 for k, v in perf.items()},
        "te_window_pct": round(te_window * 100, 1),
        "te_ann_pct": round(TRACKING_ERROR_ANNUAL * 100, 1),
        "sigma": round(perf["excess_vs_watchlist"] / (te_window * 100), 2)
                 if te_window else 0.0,
        "ic": [{"h": h, **{k: v for k, v in rank_ic(snaps, px, sessions, horizon=h).items()
                           if k in ("mean_ic", "t_stat", "sessions")}}
               for h in (5, 21)],
        "years_to_sig": {"ir05": round((2 / 0.5) ** 2), "ir03": round((2 / 0.3) ** 2)},
        "backfill": BACKFILL,
        "excluded_sessions": dropped,
    }
    # the page expects ic entries keyed ic/t/n
    out["ic"] = [{"h": e["h"], "ic": e.get("mean_ic"), "t": e.get("t_stat"),
                  "n": e.get("sessions", 0)} for e in out["ic"]]

    pathlib.Path(args.out).write_text(json.dumps(out), encoding="utf-8")
    logger.info("Wrote %s — %d live sessions, %s .. %s",
                args.out, out["sessions"], out["first"], out["asof"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
