"""Runtime secret fetch from AWS SSM Parameter Store.

Keeps secrets out of the Lambda's environment variables: the template passes
only the *name* of a SecureString parameter, and the function decrypts it at
runtime. Degrades to None on any failure so the caller can fall back.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_secure_parameter(name: str, region: Optional[str] = None) -> Optional[str]:
    """Fetch and decrypt a SecureString SSM parameter, or None on failure."""
    if not name:
        return None

    import boto3  # lazy import: provided by the Lambda runtime

    try:
        client = boto3.client("ssm", region_name=region)
        resp = client.get_parameter(Name=name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read SSM parameter %s: %s", name, exc)
        return None
