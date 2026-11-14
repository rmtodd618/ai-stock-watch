#!/usr/bin/env python3
"""Build the live-record page and upload it to the bucket CloudFront serves.

The page carries its data inline, so "publishing" means regenerating the HTML
and replacing one object. Running this on a schedule is what stops the page
quietly going stale — a dashboard titled "Live Signal Record" that has stopped
updating is worse than no dashboard, because it looks current.

    python scripts/publish_dashboard.py --bucket my-report-bucket
    python scripts/publish_dashboard.py --bucket my-report-bucket --out-file page.html

Writes to ``dashboard/index.html``. Nothing else in the bucket is touched, and
nothing is made public — CloudFront reads that prefix through an Origin Access
Control (see infra/dashboard.yaml).
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import env  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("publish")

TEMPLATE = ROOT / "src" / "reporting" / "templates" / "dashboard.html"
PLACEHOLDER = "__DATA__"
KEY = "dashboard/index.html"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bucket", help="Report bucket (defaults to $REPORT_BUCKET).")
    p.add_argument("--prefix", default="snapshots", help="Where the snapshots live.")
    p.add_argument("--out-file", help="Also write the rendered page here.")
    p.add_argument("--dry-run", action="store_true", help="Build but do not upload.")
    p.add_argument("--invalidate", action="store_true",
                   help="Invalidate the CloudFront cache for / after uploading.")
    p.add_argument("--distribution-id", help="Needed with --invalidate.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    bucket = args.bucket or env("REPORT_BUCKET")
    if not bucket and not args.dry_run:
        logger.error("No bucket: pass --bucket or set REPORT_BUCKET.")
        return 1
    if not TEMPLATE.exists():
        logger.error("Missing page template at %s", TEMPLATE)
        return 1

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        data_path = tmp.name
    build = [sys.executable, str(ROOT / "scripts" / "build_dashboard.py"), "--out", data_path]
    build += ["--bucket", bucket, "--prefix", args.prefix] if bucket else []
    result = subprocess.run(build, cwd=ROOT)
    if result.returncode != 0:
        logger.error("Could not build the page data; leaving the published page alone.")
        return result.returncode

    data = pathlib.Path(data_path).read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        logger.error("Template has no %s placeholder — refusing to publish.", PLACEHOLDER)
        return 1
    page = template.replace(PLACEHOLDER, data)

    meta = json.loads(data)
    logger.info("Built page: %d live sessions, %s .. %s (%d KB)",
                meta["sessions"], meta["first"], meta["asof"], len(page) // 1024)

    if args.out_file:
        pathlib.Path(args.out_file).write_text(page, encoding="utf-8")
        logger.info("Wrote %s", args.out_file)

    if args.dry_run:
        logger.info("Dry run — nothing uploaded.")
        return 0

    import boto3

    client = boto3.client("s3", region_name=env("AWS_REGION"))
    client.put_object(
        Bucket=bucket, Key=KEY, Body=page.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        # The page is rebuilt daily and is only ever a few sessions old; a short
        # TTL means a reader never sees yesterday's numbers behind today's date.
        CacheControl="public, max-age=300",
    )
    logger.info("Uploaded s3://%s/%s", bucket, KEY)

    if args.invalidate:
        if not args.distribution_id:
            logger.warning("--invalidate needs --distribution-id; skipping.")
        else:
            cf = boto3.client("cloudfront")
            cf.create_invalidation(
                DistributionId=args.distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": 2, "Items": ["/", "/index.html"]},
                    "CallerReference": meta["asof"] + "-" + str(meta["sessions"]),
                },
            )
            logger.info("Invalidated / on %s", args.distribution_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
