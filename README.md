# ai-stock-watch

A rules-based watchlist reporter. It pulls daily price history for a configurable
list of tickers, computes a small set of technical signals, scores each setup
0–100, maps the score to an action tier, and emails a daily summary.

Runs locally as a plain Python script, or on AWS Lambda on a schedule
(EventBridge → Lambda → SES email, optional S3 archive).

> **Disclaimer:** This project generates a rules-based market watchlist report for
> educational and personal research purposes only. It is **not** financial advice
> and **not** a recommendation to buy or sell any security. The scoring is a
> deterministic heuristic, not a prediction.

---

## What it does

For each ticker it computes:

| Metric | Meaning |
|--------|---------|
| `current_price` | Latest close |
| `change_5d` / `change_30d` | Percent change over the last 5 / 30 trading days |
| `ma50` / `ma200` | 50- and 200-day simple moving averages |
| `pct_below_52w_high` | How far the price sits below its 52-week high |

It then produces a **score (0–100)** from four weighted components and maps it to
an **action tier**:

| Tier | Default score | Meaning |
|------|---------------|---------|
| `ADD SIGNAL` | ≥ 80 | Strong uptrend + healthy setup |
| `STARTER SIGNAL` | ≥ 65 | Constructive setup, partial conviction |
| `WATCH` | ≥ 50 | Mixed signals, keep on radar |
| `AVOID FOR NOW` | < 50 | Weak trend / broken setup |

Thresholds and weights are all configurable in `config.yaml`.

### The score

The score is a weighted sum of four interpretable components (default weights):

| Component | Weight | Rewards |
|-----------|--------|---------|
| Long-term trend | 25 | Price above the 200-day MA |
| Medium-term trend | 15 | Price above the 50-day MA |
| Trend structure | 15 | 50-day MA above 200-day MA (golden-cross posture) |
| Pullback quality | 25 | A *healthy* dip off the 52-week high (not at highs, not broken) |
| Momentum | 20 | Calm short-term action (penalizes falling knives and blow-off spikes) |

Each component is normalized to 0–1 and multiplied by its weight, so the weights
sum to 100 and the score lands in 0–100. The email shows the per-component
breakdown so every score is auditable.

---

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Copy the example config; edit the watchlist if you like
cp config.example.yaml config.yaml

# Dry run: fetches data, scores, writes report.html, prints a summary table.
# No email is sent unless report.email_enabled is true.
python -m src.handler
```

Open `report.html` in a browser to preview the email.

Run the tests (no network needed — the scoring core is pure):

```bash
pytest
```

---

## Configuration

`config.example.yaml` is the committed template. Copy it to `config.yaml` (which is
git-ignored) for local overrides. **No secrets or personal data live in the config.**
Email addresses and the S3 bucket are read from environment variables, named by the
`*_env_var` keys in the config:

| Env var | Used for |
|---------|----------|
| `REPORT_RECIPIENT` | Email recipient(s), comma-separated |
| `REPORT_SENDER` | Verified SES sender address |
| `REPORT_BUCKET` | S3 bucket for archived reports (optional) |
| `AWS_REGION` | AWS region for SES / S3 |

Copy `.env.example` to `.env` for local use (git-ignored). In Lambda these come from
the SAM template parameters / function environment.

---

## Deploy to AWS (SAM)

One Lambda, one schedule, SES send permission, optional S3 bucket.

```bash
sam build -t infra/template.yaml
sam deploy --guided \
  --parameter-overrides \
    ReportSender=you@verified-domain.com \
    ReportRecipient=you@example.com
```

Requirements:
- The **sender** address/domain must be verified in SES.
- If your SES account is in the sandbox, the **recipient** must also be verified.
- The schedule defaults to weekdays at 22:00 UTC; change `Schedule` in the template.

---

## Project layout

```
ai-stock-watch/
  src/
    handler.py            # Lambda entrypoint + local CLI (run + main)
    config.py             # YAML + env config loader
    data_sources/
      prices.py           # yfinance price history (the one network boundary)
    scoring/
      technicals.py       # pure: closes -> metrics
      score.py            # pure: metrics -> score + component breakdown
      actions.py          # pure: score -> action tier
    reporting/
      email_template.py   # render HTML + text report
      ses.py              # send via SES
    storage/
      s3.py               # archive report to S3 (optional)
  infra/template.yaml     # AWS SAM: Lambda + EventBridge + SES + S3
  tests/                  # pytest, no network
  config.example.yaml
  .env.example
```

---

## Roadmap

- Fundamentals component (valuation, growth, profitability)
- Earnings-proximity flag (avoid initiating right before earnings)
- News/sentiment signal
- Per-ticker notes and historical score tracking in DynamoDB

## License

MIT
