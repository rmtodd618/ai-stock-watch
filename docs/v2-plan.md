# v2 plan — catalysts beyond price

v1 scores **setup quality** from price alone. v2 adds three context layers so the
tool reads more like a disciplined research analyst: *what's in an uptrend, what
catalyst is coming, what macro regime we're in, and why a name is moving.*

## What this does and does not do

- **Does:** flag scheduled risk (earnings), tilt scores by persistent macro
  regimes (e.g. oil ripping → energy tailwind), and attach news context.
- **Does not:** make us faster than the market. Discrete headlines are priced in
  instantly — we cannot and do not try to front-run them. The news layer is
  *context, not alpha.*

## Architecture: bounded overlays on the technical base

The technical score stays the base. New layers tilt it within hard caps, so the
chart still drives the call and a sentiment blip can't rescue a broken setup.

```
final = clamp( technical_base(0-100)  +  macro_tilt(±8)  +  sentiment_tilt(±10), 0, 100 )
action = action_for_score(final)
action, flag = earnings_guard(action, days_to_earnings)   # caps at WATCH near earnings
```

Discipline preserved from v1: **network/LLM at the edges (`data_sources/`,
`llm/`), pure + unit-tested logic in `scoring/`.** Every layer is gated by a
feature flag (default `false`) so v1 behaviour, CI, and dry runs need no keys.

## Phase 1 — Earnings-date guard

- `data_sources/earnings.py` — next earnings date (yfinance), days-until as int.
- `scoring/earnings_guard.py` — pure: within the window → cap action at `WATCH`,
  tag `⚠ earnings in Nd`.
- Honest limit: yfinance earnings dates can be estimated/missing → degrade to
  "no guard," never crash.

## Phase 2 — Macro / theme overlay

- `themes` config: theme → [tickers]. `macro.regimes`: series + lookback +
  threshold + direction + affected themes + tilt + tag.
- `data_sources/macro.py` — fetch macro proxies (oil `CL=F`, gold `GC=F`,
  VIX `^VIX`, 10-yr `^TNX`) and compute change over lookback.
- `scoring/regimes.py` — pure: detect active regimes, map to per-ticker tilt+tags.
- Honest limit: thresholds are heuristics, not predictions; themes are a
  hand-maintained map. Tilt capped at ±8.

## Phase 3 — News + Claude sentiment

- `data_sources/news.py` — recent headlines per ticker (yfinance/RSS free;
  Finnhub/NewsAPI as paid upgrades).
- `llm/claude.py` — Claude **Haiku 4.5** (cheap, high-volume classification)
  scores headlines via structured output → `{sentiment:-1..1, material_catalyst,
  summary}`.
- `scoring/sentiment.py` — pure: aggregate to bounded tilt + report blurb.
- Honest limit: context, not alpha. Cost/latency/coverage gaps are real.

## Cross-cutting

- Feature flags in config (`features.*`), all default `false`.
- Infra (mostly Phase 3): `ANTHROPIC_API_KEY` + optional news key via SSM/env;
  likely bump Lambda timeout/memory; run per-ticker LLM calls concurrently.
- Report grows a breakdown: `base → ±macro → ±sentiment → final`, plus
  regime/earnings/sentiment tags.
