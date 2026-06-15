"""Optional S3 archival of generated reports."""

from __future__ import annotations

import logging
from typing import Optional

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
