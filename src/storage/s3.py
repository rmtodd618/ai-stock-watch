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


def build_snapshot(results: list[dict], config: dict, generated_at: str) -> dict:
    """Structured record of one run: the rows plus the rules that produced them.

    The rules are stored alongside the rows on purpose. A year from now the
    config will have moved on, and a score with no record of the weights,
    smoothing window or selection mode behind it cannot be interpreted.
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
