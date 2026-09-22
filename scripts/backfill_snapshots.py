#!/usr/bin/env python3
"""Reconstruct historical score snapshots and write them to S3 or a local dir.

The score is a pure function of its trailing price window, so past sessions can
be recomputed exactly. Rows produced here are stamped ``"source": "backfill"`` —
they restate what today's rules would have said, which is not the same thing as
a record observed live. See ``src/backfill.py``.

    # Preview what would be written, no IO
    python scripts/backfill_snapshots.py --start 2024-01-01 --dry-run

    # Write locally, then eyeball a day
    python scripts/backfill_snapshots.py --start 2022-01-01 --out ./snapshots

    # Write to the report bucket the stack created
    python scripts/backfill_snapshots.py --start 2022-01-01 \\
        --bucket "$(aws cloudformation describe-stacks --stack-name ai-stock-watch \\
            --query 'Stacks[0].Outputs[?OutputKey==`ReportBucketName`].OutputValue' \\
            --output text)"
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.backfill import BackfillError, reconstruct  # noqa: E402
from src.config import env, load_config  # noqa: E402
from src.data_sources import prices  # noqa: E402
from src.storage import s3  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", help="First session to reconstruct (YYYY-MM-DD).")
    p.add_argument("--end", help="Last session to reconstruct (YYYY-MM-DD).")
    p.add_argument("--period", default="max", help="History to pull from the data source (default: max).")
    p.add_argument("--out", help="Write JSON files to this directory instead of S3.")
    p.add_argument("--bucket", help="S3 bucket to write to (defaults to $REPORT_BUCKET).")
    p.add_argument("--prefix", default="snapshots", help="Key prefix (default: snapshots).")
    p.add_argument("--benchmark", default="SPY", help="Ticker whose calendar defines the sessions (default: SPY).")
    p.add_argument("--min-sessions", type=int, default=30, help="Skip a ticker on days it had fewer closes than this.")
    p.add_argument("--dry-run", action="store_true", help="Reconstruct and report, but write nothing.")
    p.add_argument("--overwrite", action="store_true", help="Replace local files that already exist.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    watchlist = config.get("watchlist", []) or []
    benchmarks = config.get("benchmarks", []) or []
    tickers = list(dict.fromkeys(list(watchlist) + list(benchmarks)))

    logger.info("Fetching %s history for %d tickers …", args.period, len(tickers))
    history: dict[str, tuple[list[str], list[float]]] = {}
    for ticker in tickers:
        fetched = prices.fetch_history(ticker, period=args.period)
        if fetched:
            history[ticker] = fetched
    if not history:
        logger.error("No price history fetched — nothing to do.")
        return 1
    if args.benchmark not in history:
        logger.warning(
            "Benchmark %s not in the fetched set; falling back to the longest series. "
            "A market-holiday row from a futures series could slip into the calendar.",
            args.benchmark,
        )

    out_dir = pathlib.Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    bucket = args.bucket or env("REPORT_BUCKET")
    if not args.dry_run and not out_dir and not bucket:
        logger.error("Nowhere to write: pass --out, --bucket, or set REPORT_BUCKET.")
        return 1

    region = env("AWS_REGION")
    written = skipped = 0
    first = last = None
    started = time.time()

    try:
        for session, snapshot in reconstruct(
            config,
            history,
            start=args.start,
            end=args.end,
            min_sessions=args.min_sessions,
            benchmark=args.benchmark,
        ):
            first = first or session
            last = session
            key = f"{args.prefix}/{session}.json"

            if args.dry_run:
                written += 1
            elif out_dir:
                path = out_dir / f"{session}.json"
                if path.exists() and not args.overwrite:
                    skipped += 1
                else:
                    path.write_text(
                        json.dumps(snapshot, indent=2, sort_keys=True, default=str),
                        encoding="utf-8",
                    )
                    written += 1
            else:
                s3.save_snapshot(bucket, key, snapshot, region=region)
                written += 1

            if written and written % 100 == 0:
                logger.info("… %d sessions (%s)", written, session)
    except BackfillError as exc:
        logger.error("%s", exc)
        return 2

    if not written and not skipped:
        logger.warning("No sessions matched the requested range.")
        return 1

    where = "(dry run)" if args.dry_run else (str(out_dir) if out_dir else f"s3://{bucket}/{args.prefix}/")
    logger.info(
        "Reconstructed %d sessions %s..%s in %.1fs -> %s%s",
        written, first, last, time.time() - started, where,
        f" ({skipped} already present, left alone)" if skipped else "",
    )
    logger.info("These rows are stamped source=backfill — they are not live observations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
