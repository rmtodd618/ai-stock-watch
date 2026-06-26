"""Render the watchlist report as HTML and plain text.

Takes a list of per-ticker result dicts (see ``handler.build_results``) already
sorted by score, and produces email-ready bodies. Pure string building — no IO.
"""

from __future__ import annotations

from typing import Optional

_ACTION_COLORS = {
    "ADD SIGNAL": "#1b7f3b",
    "STARTER SIGNAL": "#2f6fae",
    "WATCH": "#8a6d1f",
    "AVOID FOR NOW": "#9a3b3b",
}

_COMPONENT_ORDER = [
    ("long_term_trend", "LT trend"),
    ("medium_term_trend", "MT trend"),
    ("trend_structure", "Structure"),
    ("pullback", "Pullback"),
    ("momentum", "Momentum"),
]


def _fmt_price(v: Optional[float]) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def _fmt_pct(v: Optional[float]) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.1f}%"


def _fmt_num(v: Optional[float]) -> str:
    return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _notes(r: dict) -> str:
    """Compact notes: regime/earnings tags, tilt deltas, and news summary."""
    parts: list[str] = list(r.get("tags", []))
    m = r.get("macro_tilt") or 0
    s = r.get("sentiment_tilt") or 0
    if m:
        parts.append(f"macro {m:+.0f}")
    if s:
        parts.append(f"news {s:+.0f}")
    if r.get("summary"):
        parts.append(r["summary"])
    return " · ".join(parts)


def render_text(results: list[dict], title: str, generated_at: str, disclaimer: str) -> str:
    lines = [title, generated_at, ""]
    lines.append(f"{'TICKER':<8}{'SCORE':>7}  {'ACTION':<16}{'PRICE':>12}{'5D':>9}{'30D':>9}{'%<52wH':>10}")
    lines.append("-" * 80)
    for r in results:
        m = r["metrics"]
        note = _notes(r)
        lines.append(
            f"{r['ticker']:<8}{r['score']:>7.1f}  {r['action']:<16}"
            f"{_fmt_price(m.get('current_price')):>12}"
            f"{_fmt_pct(m.get('change_5d')):>9}"
            f"{_fmt_pct(m.get('change_30d')):>9}"
            f"{_fmt_pct(m.get('pct_below_52w_high')):>10}"
            f"{('  ' + note) if note else ''}"
        )
    lines += ["", disclaimer.strip()]
    return "\n".join(lines)


def render_html(results: list[dict], title: str, generated_at: str, disclaimer: str) -> str:
    rows = []
    for r in results:
        m = r["metrics"]
        action = r["action"]
        color = _ACTION_COLORS.get(action, "#444")
        breakdown = r.get("breakdown", {})
        bd = " · ".join(
            f"{label} {breakdown.get(key, 0):.0f}" for key, label in _COMPONENT_ORDER
        )
        rows.append(
            f"""
        <tr>
          <td class="tk">{r['ticker']}</td>
          <td class="sc">{r['score']:.0f}</td>
          <td><span class="badge" style="background:{color}">{action}</span></td>
          <td class="num">{_fmt_price(m.get('current_price'))}</td>
          <td class="num {_sign(m.get('change_5d'))}">{_fmt_pct(m.get('change_5d'))}</td>
          <td class="num {_sign(m.get('change_30d'))}">{_fmt_pct(m.get('change_30d'))}</td>
          <td class="num">{_fmt_num(m.get('ma50'))}</td>
          <td class="num">{_fmt_num(m.get('ma200'))}</td>
          <td class="num">{_fmt_pct(m.get('pct_below_52w_high'))}</td>
          <td class="bd">{bd}</td>
          <td class="bd">{_notes(r)}</td>
        </tr>"""
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         color: #1c2330; background: #f4f6f9; margin: 0; padding: 24px; }}
  .wrap {{ max-width: 920px; margin: 0 auto; background: #fff; border-radius: 10px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .head {{ padding: 20px 24px; border-bottom: 1px solid #eef1f5; }}
  .head h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .head .sub {{ color: #6b7585; font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid #f0f2f6; }}
  th {{ background: #fafbfc; color: #6b7585; font-weight: 600; font-size: 11px;
        text-transform: uppercase; letter-spacing: .03em; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.tk {{ font-weight: 700; }}
  td.sc {{ font-weight: 700; text-align: right; }}
  .badge {{ color: #fff; padding: 2px 8px; border-radius: 999px; font-size: 11px;
            font-weight: 600; white-space: nowrap; }}
  .pos {{ color: #1b7f3b; }} .neg {{ color: #9a3b3b; }}
  td.bd {{ color: #8a93a3; font-size: 11px; }}
  .foot {{ padding: 16px 24px; color: #8a93a3; font-size: 11px; line-height: 1.5;
           border-top: 1px solid #eef1f5; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>{title}</h1>
      <div class="sub">{generated_at}</div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th class="num">Score</th><th>Action</th>
          <th class="num">Price</th><th class="num">5D</th><th class="num">30D</th>
          <th class="num">MA50</th><th class="num">MA200</th><th class="num">%&lt;52wH</th>
          <th>Breakdown</th><th>Notes</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}
      </tbody>
    </table>
    <div class="foot">{disclaimer.strip()}</div>
  </div>
</body>
</html>"""


def _sign(v: Optional[float]) -> str:
    if not isinstance(v, (int, float)):
        return ""
    return "pos" if v >= 0 else "neg"
