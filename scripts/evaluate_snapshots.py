#!/usr/bin/env python3
"""Score the accumulated snapshots against what the market actually did.

    python scripts/evaluate_snapshots.py --snapshots ./snapshots
    python scripts/evaluate_snapshots.py --bucket my-report-bucket --since 2025-01-01
    python scripts/evaluate_snapshots.py --snapshots ./snapshots --source live

By default this reads every snapshot it finds. Use --source to separate the two
populations, which matter very differently:

    backfill  what today's rules WOULD have said, reconstructed from prices on a
              watchlist chosen knowing how these names turned out. Useful for
              sanity-checking the machinery. Not evidence.
    live      what the tool actually said on the day, before the outcome was
              known. This is the only population that can answer "does it work",
              and it only grows one session at a time.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.config import env, load_config  # noqa: E402
from src.data_sources import prices as price_source  # noqa: E402
from src.evaluate import portfolio, rank_ic, tier_returns  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("evaluate")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshots", help="Local directory of snapshot JSON files.")
    src.add_argument("--bucket", help="S3 bucket holding them under --prefix.")
    p.add_argument("--prefix", default="snapshots", help="S3 key prefix (default: snapshots).")
    p.add_argument("--since", help="Ignore snapshots before this date (YYYY-MM-DD).")
    p.add_argument("--until", help="Ignore snapshots after this date (YYYY-MM-DD).")
    p.add_argument("--source", choices=("live", "backfill"), help="Only score one population.")
    p.add_argument("--horizons", default="5,21,63", help="Forward horizons in sessions.")
    p.add_argument("--cost-bps", type=float, default=20.0, help="Round-trip cost assumption.")
    p.add_argument("--benchmark", default="SPY", help="Ticker whose calendar defines sessions.")
    return p.parse_args()


def load_local(directory: str) -> list[dict]:
    out = []
    for path in sorted(pathlib.Path(directory).glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            logger.warning("Skipping unreadable snapshot %s", path.name)
    return out


def load_s3(bucket: str, prefix: str) -> list[dict]:
    import boto3

    client = boto3.client("s3", region_name=env("AWS_REGION"))
    out = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix.rstrip("/") + "/"
    ):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".json"):
                continue
            body = client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            try:
                out.append(json.loads(body))
            except json.JSONDecodeError:
                logger.warning("Skipping unreadable snapshot %s", obj["Key"])
    return out


def main() -> int:
    args = parse_args()
    config = load_config()

    snaps = load_local(args.snapshots) if args.snapshots else load_s3(args.bucket, args.prefix)
    if args.source:
        snaps = [s for s in snaps if s.get("source", "live") == args.source]
    if args.since:
        snaps = [s for s in snaps if s.get("generated_at", "")[:10] >= args.since]
    if args.until:
        snaps = [s for s in snaps if s.get("generated_at", "")[:10] <= args.until]
    snaps.sort(key=lambda s: s.get("generated_at", ""))

    if len(snaps) < 2:
        logger.error("Only %d snapshot(s) after filtering — nothing to measure.", len(snaps))
        return 1

    populations = {s.get("source", "live") for s in snaps}
    tickers = sorted(
        {r["ticker"] for s in snaps for r in s.get("rows", []) if r.get("ticker")}
    )
    logger.info("Fetching prices for %d tickers …", len(tickers))
    prices: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        fetched = price_source.fetch_history(ticker, period="max")
        if fetched:
            dates, closes = fetched
            prices[ticker] = dict(zip(dates, closes))
    if args.benchmark not in prices:
        logger.error("Benchmark %s unavailable — cannot build a session calendar.", args.benchmark)
        return 1
    sessions = sorted(prices[args.benchmark])

    first = snaps[0].get("generated_at", "")[:10]
    last = snaps[-1].get("generated_at", "")[:10]
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]

    print()
    print("=" * 72)
    print(f"  {len(snaps)} snapshots   {first} .. {last}")
    print(f"  population: {', '.join(sorted(populations))}")
    if populations == {"backfill"}:
        print("  NOTE: reconstructed rows only. This measures the machinery,")
        print("        not out-of-sample skill.")
    print("=" * 72)

    print("\nRANK IC — does the score order the names correctly?")
    print(f"  {'horizon':>9} {'mean IC':>9} {'t-stat':>8} {'% days +':>10} {'sessions':>9}")
    for h in horizons:
        r = rank_ic(snaps, prices, sessions, horizon=h)
        if r["mean_ic"] is None:
            print(f"  {h:>7}d  {'n/a':>9} {'—':>8} {'—':>10} {r['sessions']:>9}")
            continue
        t = f"{r['t_stat']:+.1f}" if r["t_stat"] is not None else "—"
        print(
            f"  {h:>7}d  {r['mean_ic']:>+9.3f} {t:>8} "
            f"{r['pct_positive']:>9.0f}% {r['sessions']:>9}"
        )
    print("  (|IC| below ~0.03 is indistinguishable from noise at this sample size)")

    mid = horizons[len(horizons) // 2]
    print(f"\nTIER RETURNS — average {mid}-session forward return by action")
    for action, stats in tier_returns(snaps, prices, sessions, horizon=mid).items():
        print(f"  {action:<18} {stats['mean_return']:>+7.2f}%   n={stats['n']:>6}")
    print("  (AVOID should trail the baseline. If it does not, the bottom of the")
    print("   score carries no information and sitting out those names costs you.)")

    print(f"\nPORTFOLIO — holding the ADD names, {args.cost_bps:.0f} bps per unit turnover")
    p = portfolio(snaps, prices, sessions, cost_bps=args.cost_bps)
    if not p.get("sessions"):
        print("  not enough consecutive sessions to simulate")
    else:
        print(f"  {'the tool':<28} {p['strategy_return']:>+9.1f}%")
        print(f"  {'whole watchlist, untouched':<28} {p['watchlist_return']:>+9.1f}%   <- the benchmark that matters")
        print(f"  {'SPY':<28} {p['spy_return']:>+9.1f}%")
        print(f"  {'excess vs watchlist':<28} {p['excess_vs_watchlist']:>+9.1f}%")
        print(f"  {'avg names held':<28} {p['avg_held']:>9.1f}")
        print(f"  {'annualised turnover':<28} {p['annualised_turnover']:>9.0f}%")
        if p["excess_vs_watchlist"] <= 0:
            print("\n  The tool did not beat simply holding the same names.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
