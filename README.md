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
git-ignored) for local overrides. `infra/samconfig.toml` is git-ignored too, so
it exists only on the machine that created it — CI therefore passes the stack
name and region explicitly and supplies no parameter overrides, letting
CloudFormation keep the live value of every parameter it is not given. That is
also why the sender and recipient addresses never need to be stored in GitHub. **No secrets or personal data live in the config.**
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
| `snapshots/YYYY-MM-DD.json` | The structured rows — ticker, rank, action, score, and the metrics behind it — plus the config that produced them and which tickers actually downloaded. Kept indefinitely. |

### When the data source fails

The price feed is an unofficial Yahoo scraper, and it will sometimes return
nothing for some tickers. That used to pass unnoticed: failed tickers were
simply absent from the dict, so a run that lost half its universe still ranked
whatever survived, picked a "top 8" from it, and wrote a snapshot that looked
like a valid observation.

Each run now records `coverage` — requested, fetched, and missing — so a ticker
that failed can never be confused with one that was not on the watchlist that
day. Below `data.min_coverage` the report still goes out but is clearly marked
incomplete, an ERROR is logged so the CloudWatch alarm fires, and
`evaluate_snapshots.py` skips those sessions unless you pass
`--include-incomplete`. If nothing downloads at all the run raises rather than
publishing a report with no universe.

`curl_cffi` is pinned for the same reason: without it yfinance falls back to
plain requests and Yahoo throttles the client, which is what production was
quietly doing.

The snapshots are the point. An archived email is not data you can analyse; the
JSON accumulates into a genuine out-of-sample record of what the tool actually
said on each day, which is the only way to judge it without re-deriving scores
from prices with hindsight. The rules block is stored beside the rows because a
score is uninterpretable later without the weights and smoothing window behind it.

### Backfilling the record

The technical score is a pure function of its trailing price window, so past
sessions can be recomputed exactly:

```bash
python scripts/backfill_snapshots.py --start 2022-01-01 --dry-run   # preview
python scripts/backfill_snapshots.py --start 2022-01-01 --out ./snapshots
python scripts/backfill_snapshots.py --start 2022-01-01 --bucket my-report-bucket
```

Roughly 1,200 sessions take about 25 seconds. Two things the script is careful
about, both of which are easy to get wrong:

- **Sessions come from one equity benchmark's calendar** (`--benchmark`, default
  `SPY`), never the union of every ticker's dates. Futures and index series trade
  on days the stock market is shut, and a union calendar produces sessions where
  no stock has a price — which the scorer reads as "nothing qualifies".
- **Rows are stamped `"source": "backfill"`.** A reconstructed row restates what
  *today's* rules would have said, on a watchlist chosen knowing how these names
  turned out. It is not out-of-sample evidence, and must never be pooled with
  live rows as though it were.

The v2 layers cannot be reconstructed — news sentiment depends on headlines as
published, the earnings guard on a forward calendar as it stood, the macro
overlay on a regime read at the time. The script refuses to run while any of them
is enabled rather than emit rows that quietly differ in meaning from live ones.
Those only accumulate going forward.

### Your portfolio vs the model

Optional. Copy `holdings.example.yaml` to `holdings.yaml` (git-ignored), or
upload the same file to the report bucket as `holdings.yaml` for the scheduled
run. Without it the report behaves exactly as before and says it has nothing to
compare against.

With it, the report adds what it would take to match the model — and what that
would cost:

```
TICKER     YOU   MODEL   DRIFT    TO MATCH           REALISES
NVDA     21.5%    0.0%  +21.5%      -6,648   $-1,012 short-term
PLTR     33.3%   14.3%  +19.0%      -5,877   $+1,835 short-term
ANET      0.0%   14.3%  -14.3%      +4,418
```

Two deliberate choices. Every suggested trade is priced, in spread and in
realised gain or loss, because the measurements say the trading rather than the
ranking is what costs money — a move that cannot clear its own cost is not a
move. And `rebalance_band` (default 5%) means drift smaller than the band is
left alone rather than reported as something to fix, since a portfolio nudged
back to target daily is the exact behaviour the backtest punished.

The report describes trades; it never recommends them. `cost_basis` and
`acquired` are optional, but without them it cannot tell you whether a sale
realises a short- or long-term result, which is usually the number most likely
to change your mind.

### The dashboard

`scripts/build_dashboard.py` regenerates the live-record page's data from the
archived snapshots:

```bash
python scripts/build_dashboard.py --bucket my-report-bucket --out dash.json
```

The page itself is static — it carries its data inline, so it shows whatever was
true when it was last built, and the header states the window it covers. The
weekly Evaluate workflow rebuilds `dash.json` and keeps it as a build artifact;
republishing the page is a separate manual step.

### Measuring whether it works

```bash
python scripts/evaluate_snapshots.py --snapshots ./snapshots
python scripts/evaluate_snapshots.py --bucket my-report-bucket --source live
```

Three measures, in increasing order of how much they can flatter you:

| Measure | Answers |
|---------|---------|
| **Rank IC** | Did the score order the names correctly? Cross-sectional, so a rising market cannot inflate it. |
| **Tier returns** | Are the tiers ordered at all — and in particular, is `AVOID` actually worse than the baseline? |
| **Portfolio** | What the flagged set returned, against *holding the whole watchlist* and against SPY. |

The watchlist comparison is the one that decides whether the tool earned its
keep. Beating SPY while trailing your own watchlist means the watchlist did the
work and the scoring added nothing.

Use `--source live` to exclude reconstructed rows. Backfilled rows restate what
today's rules would have said on a watchlist picked knowing the outcomes; they
measure the machinery, not skill. Only the live population answers the real
question, and it grows one session per day.

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
  backfill.py           # pure: price history -> reconstructed past snapshots
  portfolio.py          # pure: holdings + model -> drift, trades, costs
  evaluate.py           # pure: snapshots + prices -> IC, tier returns, portfolio
  scripts/
    build-lambda.sh       # Docker-free Lambda artifact
    backfill_snapshots.py # CLI: reconstruct and write historical snapshots
    evaluate_snapshots.py # CLI: score the record against what actually happened
    build_dashboard.py    # CLI: regenerate the dashboard data from snapshots
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
