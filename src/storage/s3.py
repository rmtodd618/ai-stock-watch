"""Optional S3 archival of generated reports and score snapshots."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def save_report(
    bucket: str,
    key: str,
    body: str,
    content_type: str = "text/html",
    region: Optional[str] = None,
) -> bool:
    """Upload a report body to S3. Returns True on success, False on failure."""
    import boto3  # lazy import: provided by the Lambda runtime

    try:
        client = boto3.client("s3", region_name=region)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType=content_type,
        )
        logger.info("Archived report to s3://%s/%s", bucket, key)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to archive report to S3: %s", exc)
        return False


# Fields worth keeping per ticker per day. Deliberately narrow: this is the
# record you will regress against forward returns later, not a copy of the email.
_SNAPSHOT_FIELDS = (
    "ticker",
    "rank",
    "action",
    "score",
    "base_score",
    "latest_score",
    "is_benchmark",
)
_SNAPSHOT_METRICS = (
    "current_price",
    "change_5d",
    "change_30d",
    "ma50",
    "ma200",
    "pct_below_52w_high",
)


def build_snapshot(
    results: list[dict],
    config: dict,
    generated_at: str,
    source: str = "live",
) -> dict:
    """Structured record of one run: the rows plus the rules that produced them.

    The rules are stored alongside the rows on purpose. A year from now the
    config will have moved on, and a score with no record of the weights,
    smoothing window or selection mode behind it cannot be interpreted.

    ``source`` is ``"live"`` for a row observed on the day, or ``"backfill"``
    for one reconstructed afterwards from price history. Keep the distinction:
    a reconstructed row is not out-of-sample evidence, it is a restatement of
    what the current rules would have said.
    """
    scoring = config.get("scoring", {}) or {}
    rows: list[dict[str, Any]] = []
    for r in results:
        row = {k: r.get(k) for k in _SNAPSHOT_FIELDS}
        metrics = r.get("metrics", {}) or {}
        row.update({k: metrics.get(k) for k in _SNAPSHOT_METRICS})
        row["tags"] = list(r.get("tags", []))
        rows.append(row)

    return {
        "schema": 1,
        "source": source,
        "generated_at": generated_at,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules": {
            "selection": scoring.get("selection", {}),
            "smoothing_days": scoring.get("smoothing_days"),
            "weights": scoring.get("weights", {}),
            "thresholds": scoring.get("thresholds", {}),
            "features": config.get("features", {}),
        },
        "rows": rows,
    }


def save_snapshot(
    bucket: str,
    key: str,
    snapshot: dict,
    region: Optional[str] = None,
) -> bool:
    """Write one run's structured snapshot as JSON."""
    return save_report(
        bucket,
        key,
        json.dumps(snapshot, indent=2, sort_keys=True, default=str),
        content_type="application/json",
        region=region,
    )


def load_previous_snapshot(
    bucket: str,
    prefix: str = "snapshots",
    exclude_key: Optional[str] = None,
    region: Optional[str] = None,
) -> Optional[dict]:
    """The most recent archived snapshot, so a report can say what changed.

    Keys are ``snapshots/YYYY-MM-DD.json``, which sort lexicographically in date
    order, so the newest is simply the last key. ``exclude_key`` skips today's
    own snapshot when a run is re-executed after already archiving.

    Returns None on any failure. A missing history is the normal state on the
    first run and must never take the report down.
    """
    import boto3

    try:
        client = boto3.client("s3", region_name=region)
        newest = None
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".json") or key == exclude_key:
                    continue
                if newest is None or key > newest:
                    newest = key
        if newest is None:
            logger.info("No earlier snapshot under s3://%s/%s", bucket, prefix)
            return None
        body = client.get_object(Bucket=bucket, Key=newest)["Body"].read()
        snapshot = json.loads(body)
        logger.info("Loaded previous snapshot %s", newest)
        return snapshot
    except Exception as exc:  # noqa: BLE001 - never fail the report over history
        logger.warning("Could not load previous snapshot: %s", exc)
        return None
