"""Entrypoint: build the report, then email/archive it.

Two ways in:
- ``lambda_handler(event, context)`` for AWS Lambda (EventBridge schedule).
- ``main()`` for local runs: ``python -m src.handler`` (dry run by default —
  writes report.html and prints a summary; only emails if config enables it).
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from src.config import env, load_config, resolve_recipients
from src.data_sources import prices
from src.reporting import email_template, ses
from src.scoring.actions import action_for_score
from src.scoring.score import score_metrics
from src.scoring.technicals import compute_metrics
from src.storage import s3

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-stock-watch")


def build_results(config: dict, closes_by_ticker: dict[str, list[float]]) -> list[dict]:
    """Turn raw closes into scored, sorted result rows."""
    thresholds = config.get("scoring", {}).get("thresholds", {})
    results: list[dict] = []
    for ticker, closes in closes_by_ticker.items():
        metrics = compute_metrics(closes)
        if not metrics:
            logger.warning("Skipping %s: no usable metrics", ticker)
            continue
        scored = score_metrics(metrics, config)
        action = action_for_score(scored["score"], thresholds)
        results.append(
            {
                "ticker": ticker,
                "score": scored["score"],
                "action": action.label,
                "metrics": metrics,
                "components": scored["components"],
                "breakdown": scored["breakdown"],
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def run(config: dict, send: bool | None = None) -> dict:
    """Fetch data, build the report, and optionally email/archive it.

    Returns a dict with the rendered bodies and per-ticker results.
    """
    report_cfg = config.get("report", {})
    period = config.get("data", {}).get("history_period", "1y")
    watchlist = config.get("watchlist", [])

    logger.info("Fetching %d tickers (%s history)", len(watchlist), period)
    closes_by_ticker = prices.fetch_many(watchlist, period=period)
    results = build_results(config, closes_by_ticker)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = report_cfg.get("title", "AI Stock Watch")
    disclaimer = config.get("disclaimer", "")

    html = email_template.render_html(results, title, generated_at, disclaimer)
    text = email_template.render_text(results, title, generated_at, disclaimer)

    region = env("AWS_REGION")
    should_send = report_cfg.get("email_enabled", False) if send is None else send
    message_id = None
    if should_send:
        recipients = resolve_recipients(report_cfg)
        sender = env(report_cfg.get("sender_env_var"))
        subject = f"{title} — {generated_at}"
        message_id = ses.send_email(sender, recipients, subject, html, text, region)

    if report_cfg.get("save_to_s3", False):
        bucket = env(report_cfg.get("s3_bucket_env_var"))
        if bucket:
            key = f"reports/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}.html"
            s3.save_report(bucket, key, html, region=region)

    return {
        "generated_at": generated_at,
        "count": len(results),
        "results": results,
        "html": html,
        "text": text,
        "message_id": message_id,
    }


def lambda_handler(event, context):  # noqa: ARG001 - Lambda signature
    config = load_config()
    report = run(config)
    return {
        "statusCode": 200,
        "count": report["count"],
        "message_id": report["message_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ai-stock-watch report.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the email (overrides config email_enabled).",
    )
    parser.add_argument(
        "--out",
        default="report.html",
        help="Where to write the rendered HTML report (default: report.html).",
    )
    args = parser.parse_args()

    config = load_config()
    report = run(config, send=True if args.send else None)

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report["html"])

    print()
    print(report["text"])
    print()
    print(f"Wrote {args.out} ({report['count']} tickers).")
    if report["message_id"]:
        print(f"Email sent (MessageId={report['message_id']}).")
    elif config.get("report", {}).get("email_enabled") or args.send:
        print("Email send was attempted but failed — check logs above.")
    else:
        print("Dry run — no email sent (set report.email_enabled or pass --send).")


if __name__ == "__main__":
    main()
