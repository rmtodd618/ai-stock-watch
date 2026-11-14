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
from pathlib import Path
from typing import Optional

from src.config import env, load_config, resolve_recipients
from src.data_sources import earnings, macro, news, prices
from src.llm import claude
from src.reporting import email_template, ses
from src import portfolio as portfolio_mod
from src.scoring import regimes, selection
from src.scoring.composite import composite_score
from src.scoring.earnings_guard import apply_earnings_guard
from src.scoring.score import score_metrics
from src.scoring.sentiment import sentiment_tilt
from src.scoring.smoothing import smoothed_score
from src.scoring.technicals import compute_metrics
from src.storage import s3, ssm

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

    Scoring happens in two passes: every ticker is scored independently, then
    actions are assigned across the sorted field, because rank mode can only
    decide a tier once it knows what else is on offer.
    """
    scoring = config.get("scoring", {})
    tilts = scoring.get("tilts", {})
    macro_cap = tilts.get("macro_max", 8)
    sentiment_cap = tilts.get("sentiment_max", 10)
    themes_map = config.get("themes", {})
    guard_window = config.get("earnings", {}).get("guard_window_days", 5)
    data_cfg = config.get("data", {})
    lookback = int(data_cfg.get("lookback_days", 252))
    smoothing_days = int(scoring.get("smoothing_days", 40))
    # Below this many sessions the score is mostly placeholders: compute_metrics
    # returns None for a moving average it cannot form, which score_metrics reads
    # as the neutral 0.5. A recent IPO therefore scores ~50 on no information,
    # and under rank selection a ~50 can take a real slot. Flag instead.
    min_sessions = int(data_cfg.get("min_sessions", 200))

    benchmarks = set(config.get("benchmarks", []) or [])

    active_regimes = active_regimes or []
    earnings_days = earnings_days or {}
    sentiment = sentiment or {}

    results: list[dict] = []
    for ticker, closes in closes_by_ticker.items():
        # Metrics always describe the most recent `lookback` sessions, never the
        # extra history fetched to make smoothing possible — otherwise the
        # "52-week high" would silently become an 18-month high.
        metrics = compute_metrics(closes[-lookback:])
        if not metrics:
            logger.warning("Skipping %s: no usable metrics", ticker)
            continue

        scored = score_metrics(metrics, config)
        base = smoothed_score(closes, config, smoothing_days, lookback)
        if base is None:
            base = scored["score"]

        m_tilt, m_tags = regimes.macro_tilt(ticker, active_regimes, themes_map, macro_cap)
        s_tilt, s_summary = sentiment_tilt(sentiment.get(ticker), sentiment_cap)

        results.append(
            {
                "ticker": ticker,
                "is_benchmark": ticker in benchmarks,
                "insufficient_history": metrics["data_points"] < min_sessions,
                "score": round(composite_score(base, m_tilt, s_tilt), 1),
                "base_score": round(base, 1),
                "latest_score": scored["score"],
                "metrics": metrics,
                "components": scored["components"],
                "breakdown": scored["breakdown"],
                "macro_tilt": m_tilt,
                "sentiment_tilt": s_tilt,
                "tags": list(m_tags),
                "summary": s_summary,
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)

    rank = 0
    for row, action in zip(results, selection.assign_actions(results, scoring)):
        action, earnings_tag = apply_earnings_guard(
            action, earnings_days.get(row["ticker"]), guard_window
        )
        if earnings_tag:
            row["tags"].append(earnings_tag)
        if row["is_benchmark"] or row["insufficient_history"]:
            row["rank"] = None
        else:
            rank += 1
            row["rank"] = rank
        row["action"] = action.label

    return results


def _load_holdings(pf_cfg: dict, bucket: Optional[str], region: Optional[str]) -> Optional[dict]:
    """Local file first so a developer can try it without touching S3."""
    import yaml

    local = pf_cfg.get("holdings_file")
    if local:
        path = Path(local)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / local
        if path.exists():
            try:
                return yaml.safe_load(path.read_text(encoding="utf-8")) or None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read %s: %s", path, exc)
    return s3.load_holdings(bucket, pf_cfg.get("holdings_s3_key", "holdings.yaml"), region)


def _resolve_anthropic_key(news_cfg: dict, region: str | None) -> str | None:
    """Resolve the Anthropic API key: SSM SecureString first, then env var.

    In Lambda the key lives only in SSM — the env var holds the *parameter name*.
    For local dev, set ANTHROPIC_API_KEY directly and leave the SSM var unset.
    """
    ssm_param = env(news_cfg.get("api_key_ssm_param_env_var"))
    if ssm_param:
        key = ssm.get_secure_parameter(ssm_param, region=region)
        if key:
            return key
        logger.warning(
            "No usable key in SSM param %s; falling back to env var", ssm_param
        )
    return env(news_cfg.get("api_key_env_var"))


def run(config: dict, send: bool | None = None) -> dict:
    """Fetch data, build the report, and optionally email/archive it.

    Returns a dict with the rendered bodies and per-ticker results.
    """
    report_cfg = config.get("report", {})
    features = config.get("features", {})
    period = config.get("data", {}).get("history_period", "1y")
    watchlist = config.get("watchlist", [])
    benchmarks = config.get("benchmarks", []) or []
    region = env("AWS_REGION")

    # Benchmarks ride along so the report can show them, but selection excludes
    # them from the ranked field.
    to_fetch = list(dict.fromkeys(list(watchlist) + list(benchmarks)))
    logger.info(
        "Fetching %d tickers (%d watchlist + %d benchmarks, %s history)",
        len(to_fetch), len(watchlist), len(benchmarks), period,
    )
    fetched = prices.fetch_many(to_fetch, period=period)
    closes_by_ticker = fetched.closes
    tickers = list(closes_by_ticker)

    # A run that quietly lost half its universe still produces a plausible
    # report: it ranks whatever survived and picks a "top N" from that. Decide
    # explicitly what to do rather than letting the gap pass unremarked.
    min_coverage = float(config.get("data", {}).get("min_coverage", 0.9))
    if not closes_by_ticker:
        raise RuntimeError(
            f"No price data for any of {len(to_fetch)} tickers — refusing to "
            "publish a report with no universe."
        )
    degraded = fetched.coverage < min_coverage
    if degraded:
        logger.error(
            "Only %d of %d tickers returned data (%.0f%% < %.0f%% required); "
            "the report and snapshot will be marked incomplete. Missing: %s",
            len(closes_by_ticker), len(to_fetch), fetched.coverage * 100,
            min_coverage * 100, ", ".join(fetched.failed),
        )

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
        api_key = _resolve_anthropic_key(news_cfg, region)
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
    dashboard_url = env(report_cfg.get("dashboard_url_env_var"))

    # Yesterday's archived snapshot, so the report can lead with what moved
    # rather than a table that looks identical every day. Read before today's
    # is written, and never allowed to fail the run.
    bucket = env(report_cfg.get("s3_bucket_env_var"))
    previous = None
    if bucket:
        previous = s3.load_previous_snapshot(
            bucket,
            prefix="snapshots",
            exclude_key=f"snapshots/{datetime.now(timezone.utc):%Y-%m-%d}.json",
            region=region,
        )

    coverage = {
        "requested": fetched.requested,
        "fetched": sorted(closes_by_ticker),
        "missing": fetched.failed,
        "complete": not fetched.failed,
        "degraded": degraded,
    }

    # Optional: what the model holds versus what you hold, and what closing the
    # gap would cost. Never load-bearing — a missing holdings file just means
    # the report has nothing to compare against.
    plan = None
    pf_cfg = config.get("portfolio", {}) or {}
    if pf_cfg.get("enabled"):
        holdings = _load_holdings(pf_cfg, bucket, region)
        if holdings:
            prices_now = {
                r["ticker"]: r["metrics"].get("current_price")
                for r in results
                if r.get("metrics", {}).get("current_price")
            }
            plan = portfolio_mod.rebalance(
                holdings, results, prices_now,
                band=float(pf_cfg.get("rebalance_band", 0.05)),
                spread_bps=float(pf_cfg.get("spread_bps", 20)),
            )

    html = email_template.render_html(
        results, title, generated_at, disclaimer, previous, dashboard_url,
        coverage, plan
    )
    text = email_template.render_text(
        results, title, generated_at, disclaimer, previous, dashboard_url,
        coverage, plan
    )

    should_send = report_cfg.get("email_enabled", False) if send is None else send
    message_id = None
    if should_send:
        recipients = resolve_recipients(report_cfg)
        sender = env(report_cfg.get("sender_env_var"))
        subject = f"{title} — {generated_at}"
        message_id = ses.send_email(sender, recipients, subject, html, text, region)

    if report_cfg.get("save_to_s3", False):
        if bucket:
            stamp = datetime.now(timezone.utc)
            # The rendered email, for reading back.
            s3.save_report(
                bucket, f"reports/{stamp.strftime('%Y/%m/%d')}.html", html, region=region
            )
            # The structured rows, for analysing later. This is the one that
            # accumulates into a genuine out-of-sample record — an archived
            # email is not data you can regress against forward returns.
            s3.save_snapshot(
                bucket,
                f"snapshots/{stamp.strftime('%Y-%m-%d')}.json",
                s3.build_snapshot(results, config, generated_at, coverage=coverage),
                region=region,
            )
        else:
            logger.warning(
                "save_to_s3 is on but %s is unset — nothing archived",
                report_cfg.get("s3_bucket_env_var"),
            )

    return {
        "generated_at": generated_at,
        "count": len(results),
        "coverage": coverage,
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
