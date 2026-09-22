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

It then produces a **score (0–100)** from four weighted components, averages that
score over the last 40 sessions, and ranks the watchlist on the result:

| Tier | Meaning |
|------|---------|
| `ADD SIGNAL` | One of the `top_n` best setups on offer today |
| `STARTER SIGNAL` | Next in line — first to rotate in |
| `WATCH` | Below the flagged set but still above the `watch` floor |
| `AVOID FOR NOW` | Below the `watch` floor |
| `BENCHMARK` | An index/ETF row, shown for comparison and never ranked |

### Why rank, and why smooth

Both choices come out of backtesting the v1 rules, and both address the same
failure: the v1 report traded far more than its signal justified.

**Ranking instead of thresholding.** A fixed cutoff ("score ≥ 65") makes the size
of the flagged set depend on the market's mood rather than on what is on offer. In
a drawdown every score falls together, the report empties out, and the strategy
sits in cash at precisely the moment the setups it exists to find are forming. Rank
mode asks "which are the best `top_n` right now?", so the flagged set is the same
size every day and no position round-trips a fixed line as its score drifts across
it. Set `scoring.selection.mode: threshold` to restore the v1 behaviour.

**Smoothing the score.** Measured against forward returns, the score's information
is strongest at roughly a three-month horizon (rank IC +0.11 at 63 sessions versus
+0.06 at 5). Acting on the raw daily value therefore trades mostly noise. Averaging
the score over `scoring.smoothing_days` sessions keeps the slow component and cut
simulated turnover by about 5× without giving up return. Set `smoothing_days: 1`
for the v1 behaviour.

No state is needed for this: the score is a pure function of its trailing close
window, so a past session's score is recovered by truncating the series. The run
just fetches enough history (`data.history_period`) to cover
`lookback_days + smoothing_days`.

> These are engineering fixes to a noisy rule, not evidence that the strategy beats
> buying and holding the same list. In backtest it does not reliably do so.

Thresholds, weights, `top_n` and `smoothing_days` are all configurable in
`config.yaml`.

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
| `SAVE_TO_S3` | `true`/`false` — overrides `report.save_to_s3` |
| `EMAIL_ENABLED` | `true`/`false` — overrides `report.email_enabled` |
| `AWS_REGION` | AWS region for SES / S3 |

Only `config.example.yaml` ships in the Lambda package, so anything the infra
needs to control has to have an env override here — a value that only exists in
the YAML is frozen at whatever the committed file says.

### What gets archived

With archiving on, each run writes two objects:

| Key | What it is |
|-----|------------|
| `reports/YYYY/MM/DD.html` | The rendered email, for reading back. Expires after 90 days. |
| `snapshots/YYYY-MM-DD.json` | The structured rows — ticker, rank, action, score, and the metrics behind it — plus the config that produced them. Kept indefinitely. |

The snapshots are the point. An archived email is not data you can analyse; the
JSON accumulates into a genuine out-of-sample record of what the tool actually
said on each day, which is the only way to judge it without re-deriving scores
from prices with hindsight. The rules block is stored beside the rows because a
score is uninterpretable later without the weights and smoothing window behind it.

Copy `.env.example` to `.env` for local use (git-ignored). In Lambda these come from
the SAM template parameters / function environment.

---

## Deploy to AWS (SAM)

One Lambda, one schedule, SES send permission, optional S3 bucket.

```bash
sam build --use-container -t infra/template.yaml
sam deploy --guided \
  --parameter-overrides \
    ReportSender=you@verified-domain.com \
    ReportRecipient=you@example.com
```

Requirements:
- The **sender** address/domain must be verified in SES.
- If your SES account is in the sandbox, the **recipient** must also be verified.
- The schedule defaults to weekdays at 22:00 UTC; change `Schedule` in the template.

### Enabling the v2 context layers

All v2 features are off by default and toggled via deploy parameters (which map
to env vars the function reads — no `config.yaml` is baked into the package):

```bash
sam deploy \
  --parameter-overrides \
    ReportSender=you@verified-domain.com \
    ReportRecipient=you@example.com \
    EarningsGuardEnabled=true \
    MacroOverlayEnabled=true \
    NewsSentimentEnabled=true
```

- **Earnings guard** and **macro overlay** are free — no key required.
- **News sentiment** needs an Anthropic API key. The key never goes in the
  template, CloudFormation, or the Lambda environment — it lives in **SSM
  Parameter Store** as a `SecureString`, and the function reads + decrypts it at
  runtime. Create it once before enabling the feature:

  ```bash
  aws ssm put-parameter \
    --name /ai-stock-watch/anthropic-api-key \
    --type SecureString \
    --value sk-ant-...
  ```

  The deploy grants the function a scoped `ssm:GetParameter` + `kms:Decrypt`
  (via-SSM only) policy for exactly that parameter. Override the parameter name
  with `AnthropicApiKeySsmParam=...` if you use a different path. For local
  testing, set `ANTHROPIC_API_KEY` in `.env` instead (the function falls back to
  it when no SSM parameter name is configured).

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
      smoothing.py        # pure: closes -> score averaged over N sessions
      selection.py        # pure: sorted rows -> action tier (rank or threshold)
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

- Fundamentals component (valuation, growth, profitability) — the five current
  components correlate 0.49–0.75 with each other, so they are close to one signal
  measured four ways; genuinely new information has to come from outside the price
  series
- Per-ticker notes in DynamoDB (score history is no longer needed for smoothing —
  it is recomputed from prices)

## License

MIT
