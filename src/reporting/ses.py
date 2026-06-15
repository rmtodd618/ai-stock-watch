"""Send the report email via Amazon SES."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_email(
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    region: Optional[str] = None,
) -> Optional[str]:
    """Send an HTML+text email. Returns the SES MessageId, or None on failure."""
    import boto3  # lazy import: provided by the Lambda runtime

    if not sender or not recipients:
        logger.error("Missing sender or recipients; skipping send.")
        return None

    try:
        client = boto3.client("ses", region_name=region)
        resp = client.send_email(
            Source=sender,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )
        message_id = resp.get("MessageId")
        logger.info("Sent report to %s (MessageId=%s)", recipients, message_id)
        return message_id
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email via SES: %s", exc)
        return None
