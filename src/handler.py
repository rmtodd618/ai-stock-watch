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
from src.data_sources import earnings, macro, news, prices
from src.llm import claude
from src.reporting import email_template, ses
from src.scoring import regimes
from src.scoring.actions import action_for_score
from src.scoring.composite import composite_score
from src.scoring.earnings_guard import apply_earnings_guard
from src.scoring.score import score_metrics
from src.scoring.sentiment import sentiment_tilt
from src.scoring.technicals import compute_metrics
from src.storage import s3

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-stock-watch")


def build_results(
    config: dict,
    closes_by_ticker: dict[str, list[float]],
    *,
    active_regimes: list[dict] | None = None,
    earnings_days: dict[str, int | None] | None = None,
    sentiment: dict[str, dict | None] | None = None,
) -> list[dict]:
    """Turn raw closes (+ optional context overlays) into scored, sorted rows.

    The overlay inputs are pre-fetched by ``run()`` based on feature flags, so
    this stays pure and unit-testable (no network).
    """
    scoring = config.get("scoring", {})
    thresholds = scoring.get("thresholds", {})
    tilts = scoring.get("tilts", {})
    macro_cap = tilts.get("macro_max", 8)
    sentiment_cap = tilts.get("sentiment_max", 10)
    themes_map = config.get("themes", {})
    guard_window = config.get("earnings", {}).get("guard_window_days", 5)

    active_regimes = active_regimes or []
    earnings_days = earnings_days or {}
    sentiment = sentiment or {}

    results: list[dict] = []
    for ticker, closes in closes_by_ticker.items():
        metrics = compute_metrics(closes)
        if not metrics:
            logger.warning("Skipping %s: no usable metrics", ticker)
            continue

        scored = score_metrics(metrics, config)
        base = scored["score"]

        m_tilt, m_tags = regimes.macro_tilt(ticker, active_regimes, themes_map, macro_cap)
        s_tilt, s_summary = sentiment_tilt(sentiment.get(ticker), sentiment_cap)

        final = composite_score(base, m_tilt, s_tilt)
        action = action_for_score(final, thresholds)

        action, earnings_tag = apply_earnings_guard(
            action, earnings_days.get(ticker), guard_window
        )

        tags = list(m_tags)
        if earnings_tag:
            tags.append(earnings_tag)

        results.append(
            {
                "ticker": ticker,
                "score": round(final, 1),
                "base_score": base,
                "action": action.label,
                "metrics": metrics,
                "components": scored["components"],
                "breakdown": scored["breakdown"],
                "macro_tilt": m_tilt,
                "sentiment_tilt": s_tilt,
                "tags": tags,
                "summary": s_summary,
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def run(config: dict, send: bool | None = None) -> dict:
    """Fetch data, build the report, and optionally email/archive it.

    Returns a dict with the rendered bodies and per-ticker results.
    """
    report_cfg = config.get("report", {})
    features = config.get("features", {})
    period = config.get("data", {}).get("history_period", "1y")
    watchlist = config.get("watchlist", [])

    logger.info("Fetching %d tickers (%s history)", len(watchlist), period)
    closes_by_ticker = prices.fetch_many(watchlist, period=period)
    tickers = list(closes_by_ticker)

    # --- v2 context overlays (each gated by a feature flag) ---
    active = None
    if features.get("macro_overlay"):
        macro_cfg = config.get("macro", {})
        regimes_cfg = macro_cfg.get("regimes", [])
        changes = macro.fetch_macro_changes(
            regimes_cfg, period=macro_cfg.get("history_period", "3mo")
        )
        active = regimes.active_regimes(changes, regimes_cfg)
        if active:
            logger.info("Active macro regimes: %s", [r.get("name") for r in active])

    earnings_days = None
    if features.get("earnings_guard"):
        earnings_days = {t: earnings.days_until_earnings(t) for t in tickers}

    sentiment = None
    if features.get("news_sentiment"):
        news_cfg = config.get("news", {})
        model = news_cfg.get("model")
        api_key = env(news_cfg.get("api_key_env_var"))
        limit = news_cfg.get("max_headlines", 8)
        sentiment = {}
        for t in tickers:
            headlines = news.fetch_headlines(t, limit=limit)
            sentiment[t] = claude.score_headlines(t, headlines, model, api_key)

    results = build_results(
        config,
        closes_by_ticker,
        active_regimes=active,
        earnings_days=earnings_days,
        sentiment=sentiment,
    )

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
    # EMAIL_ENABLED (set by the SAM template) overrides the config default so the
    # send behaviour is controlled by infra, not a value baked into the package.
    email_enabled = env("EMAIL_ENABLED")
    send = email_enabled.strip().lower() == "true" if email_enabled is not None else None
    report = run(config, send=send)
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
