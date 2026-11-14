"""Render the watchlist report as HTML and plain text.

Takes a list of per-ticker result dicts (see ``handler.build_results``) already
sorted by score, and produces email-ready bodies. Pure string building — no IO.

Deliberately plain HTML. This is read in Gmail, which strips ``<svg>``, ignores
CSS custom properties and never runs JavaScript, so none of the techniques the
dashboard uses survive here. Layout is a table, colours are literals, and the
score bars are nested divs with a background — the one chart email allows.
Everything stays readable if the ``<style>`` block is dropped entirely.
"""

from __future__ import annotations

from typing import Optional

from src.portfolio import summary_line as plan_summary
from src.reporting.changes import compute_changes, summary_line

_ACTION_COLORS = {
    "ADD SIGNAL": "#1b7f3b",
    "STARTER SIGNAL": "#2f6fae",
    "WATCH": "#8a6d1f",
    "AVOID FOR NOW": "#9a3b3b",
    "BENCHMARK": "#6b7585",
    "NOT ENOUGH HISTORY": "#6b7585",
}

def _fmt_price(v: Optional[float]) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def _fmt_pct(v: Optional[float]) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.1f}%"


def _fmt_rank(v: Optional[int]) -> str:
    """Benchmark rows carry no rank — they are not part of the ranked field."""
    return str(v) if isinstance(v, int) else "—"


def _delta_text(delta: Optional[int]) -> str:
    """Rank movement in plain text. Positive means it climbed the board."""
    if delta is None:
        return ""
    if delta == 0:
        return "="
    return f"{'+' if delta > 0 else '-'}{abs(delta)}"


def _delta_html(delta: Optional[int]) -> str:
    if delta is None:
        return '<span style="color:#b9c0cb">&middot;</span>'
    if delta == 0:
        return '<span style="color:#b9c0cb">&ndash;</span>'
    up = delta > 0
    return (
        f'<span style="color:{"#1b7f3b" if up else "#9a3b3b"}">'
        f'{"&#9650;" if up else "&#9660;"}{abs(delta)}</span>'
    )


def _score_bar(score: Optional[float], color: str) -> str:
    """A bar drawn with nested divs — no SVG, no canvas, works in Gmail."""
    if not isinstance(score, (int, float)):
        return ""
    width = max(2, min(100, int(round(score))))
    return (
        '<div style="background:#eef1f5;border-radius:2px;height:5px;width:58px">'
        f'<div style="background:{color};border-radius:2px;height:5px;'
        f'width:{width}%"></div></div>'
    )


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


def render_text(
    results: list[dict],
    title: str,
    generated_at: str,
    disclaimer: str,
    previous: Optional[dict] = None,
    dashboard_url: Optional[str] = None,
    coverage: Optional[dict] = None,
    plan: Optional[dict] = None,
) -> str:
    changes = compute_changes(results, previous)
    lines = [title, generated_at, "", summary_line(results, changes), ""]

    missing = (coverage or {}).get("missing") or []
    if missing:
        lines += [
            f"!! INCOMPLETE RUN — no price data for {len(missing)} ticker(s): "
            + ", ".join(missing),
            "   The ranking below was computed without them.",
            "",
        ]

    if changes["comparable"] and (changes["entered"] or changes["left"]):
        if changes["entered"]:
            lines.append("ENTERED: " + ", ".join(changes["entered"]))
        if changes["left"]:
            lines.append("LEFT:    " + ", ".join(changes["left"]))
        lines.append("")

    header = (
        f"{'#':>3} {'D':>4}  {'TICKER':<8}{'SCORE':>7}  {'ACTION':<20}"
        f"{'PRICE':>12}{'5D':>9}{'30D':>9}{'%<52wH':>10}"
    )
    lines.append(header)
    lines.append("-" * 92)
    for r in results:
        m = r["metrics"]
        note = _notes(r)
        delta = _delta_text(changes["deltas"].get(r["ticker"]))
        lines.append(
            f"{_fmt_rank(r.get('rank')):>3} {delta:>4}  "
            f"{r['ticker']:<8}{r['score']:>7.1f}  {r['action']:<20}"
            f"{_fmt_price(m.get('current_price')):>12}"
            f"{_fmt_pct(m.get('change_5d')):>9}"
            f"{_fmt_pct(m.get('change_30d')):>9}"
            f"{_fmt_pct(m.get('pct_below_52w_high')):>10}"
            f"{('  ' + note) if note else ''}"
        )
    if plan and plan.get("nav"):
        lines += ["", "YOUR PORTFOLIO vs THE MODEL", plan_summary(plan)]
        act = plan.get("actionable") or []
        if act:
            lines.append(
                f"{'TICKER':<8}{'YOU':>8}{'MODEL':>8}{'DRIFT':>8}{'TO MATCH':>14}{'REALISES':>14}"
            )
            for r in sorted(act, key=lambda r: -abs(r["drift"])):
                realised = ""
                if r["dollars"] < 0 and r["term"] != "unknown":
                    realised = f"{r['realised_gain']:+,.0f} {r['term']}"
                lines.append(
                    f"{r['ticker']:<8}{r['current']*100:>7.1f}%{r['target']*100:>7.1f}%"
                    f"{r['drift']*100:>+7.1f}%{r['dollars']:>+13,.0f}{realised:>14}"
                )

    if dashboard_url:
        lines += ["", f"Full record: {dashboard_url}"]
    lines += ["", disclaimer.strip()]
    return "\n".join(lines)


def render_html(
    results: list[dict],
    title: str,
    generated_at: str,
    disclaimer: str,
    previous: Optional[dict] = None,
    dashboard_url: Optional[str] = None,
    coverage: Optional[dict] = None,
    plan: Optional[dict] = None,
) -> str:
    changes = compute_changes(results, previous)
    summary = summary_line(results, changes)

    missing = (coverage or {}).get("missing") or []
    warning = ""
    if missing:
        warning = (
            '<div style="padding:12px 24px;background:#fdf2f2;'
            'border-bottom:1px solid #f3dcdc;font-size:13px;color:#9a3b3b">'
            f'<b>Incomplete run</b> &mdash; no price data for {len(missing)} '
            f'ticker(s): {", ".join(missing)}. '
            'The ranking below was computed without them.</div>'
        )

    moved = ""
    if changes["comparable"] and (changes["entered"] or changes["left"]):
        bits = []
        if changes["entered"]:
            bits.append(
                '<span style="color:#1b7f3b;font-weight:700">&#9650; IN</span> '
                + ", ".join(changes["entered"])
            )
        if changes["left"]:
            bits.append(
                '<span style="color:#9a3b3b;font-weight:700">&#9660; OUT</span> '
                + ", ".join(changes["left"])
            )
        moved = (
            '<div style="padding:11px 24px;background:#fbfaf4;'
            'border-bottom:1px solid #eef1f5;font-size:13px;color:#1c2330">'
            + " &nbsp;&middot;&nbsp; ".join(bits)
            + "</div>"
        )

    rows = []
    for r in results:
        m = r["metrics"]
        action = r["action"]
        color = _ACTION_COLORS.get(action, "#444")
        quiet = r.get("is_benchmark") or r.get("insufficient_history")
        rows.append(
            f"""
        <tr{' style="background:#fafbfc"' if quiet else ''}>
          <td class="rk">{_fmt_rank(r.get('rank'))}</td>
          <td class="dl">{_delta_html(changes['deltas'].get(r['ticker']))}</td>
          <td class="tk"{' style="color:#6b7585"' if quiet else ''}>{r['ticker']}</td>
          <td class="sc">{r['score']:.0f}</td>
          <td class="br">{_score_bar(r.get('score'), color)}</td>
          <td><span class="badge" style="background:{color}">{action}</span></td>
          <td class="num">{_fmt_price(m.get('current_price'))}</td>
          <td class="num {_sign(m.get('change_5d'))}">{_fmt_pct(m.get('change_5d'))}</td>
          <td class="num {_sign(m.get('change_30d'))}">{_fmt_pct(m.get('change_30d'))}</td>
          <td class="num">{_fmt_pct(m.get('pct_below_52w_high'))}</td>
          <td class="bd">{_notes(r)}</td>
        </tr>"""
        )

    pf = ""
    if plan and plan.get("nav"):
        act = sorted(plan.get("actionable") or [], key=lambda r: -abs(r["drift"]))
        if act:
            trs = ""
            for r in act:
                realised = "&mdash;"
                if r["dollars"] < 0 and r["term"] != "unknown":
                    col = "#1b7f3b" if r["realised_gain"] >= 0 else "#9a3b3b"
                    realised = (f'<span style="color:{col}">${r["realised_gain"]:+,.0f} '
                                f'{r["term"]}-term</span>')
                side = "#1b7f3b" if r["dollars"] > 0 else "#9a3b3b"
                trs += (
                    f'<tr><td class="tk">{r["ticker"]}</td>'
                    f'<td class="num">{r["current"]*100:.1f}%</td>'
                    f'<td class="num">{r["target"]*100:.1f}%</td>'
                    f'<td class="num">{r["drift"]*100:+.1f}%</td>'
                    f'<td class="num" style="color:{side};font-weight:700">'
                    f'${r["dollars"]:+,.0f}</td>'
                    f'<td class="num">{realised}</td></tr>'
                )
            body = (
                '<table style="margin-top:8px"><thead><tr>'
                '<th>Ticker</th><th class="num">You</th><th class="num">Model</th>'
                '<th class="num">Drift</th><th class="num">To match</th>'
                '<th class="num">Realises</th></tr></thead><tbody>'
                + trs + "</tbody></table>"
            )
        else:
            body = ""
        pf = (
            '<div style="padding:14px 24px;border-top:1px solid #eef1f5;'
            'background:#fbfcfd">'
            '<div style="font-weight:700;font-size:13px;margin-bottom:4px">'
            'Your portfolio vs the model</div>'
            f'<div style="font-size:12px;color:#6b7585">{plan_summary(plan)}</div>'
            f"{body}</div>"
        )

    link = (
        f'<div class="lk"><a href="{dashboard_url}" style="color:#2f6fae;'
        'text-decoration:none;font-weight:600">View the full record &rarr;</a></div>'
        if dashboard_url
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         color: #1c2330; background: #f4f6f9; margin: 0; padding: 24px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; background: #fff; border-radius: 10px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .head {{ padding: 20px 24px 16px; border-bottom: 1px solid #eef1f5; }}
  .head h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .head .sub {{ color: #6b7585; font-size: 12px; }}
  .head .sum {{ margin-top: 11px; font-size: 14px; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid #f0f2f6; }}
  th {{ background: #fafbfc; color: #6b7585; font-weight: 600; font-size: 11px;
        text-transform: uppercase; letter-spacing: .03em; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.tk {{ font-weight: 700; }}
  td.rk, th.rk {{ color: #8a93a3; text-align: right; width: 26px;
                  font-variant-numeric: tabular-nums; }}
  td.dl, th.dl {{ text-align: left; width: 34px; font-size: 11px;
                  font-variant-numeric: tabular-nums; }}
  td.sc {{ font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }}
  td.br {{ width: 58px; padding-left: 0; }}
  .badge {{ color: #fff; padding: 2px 8px; border-radius: 999px; font-size: 11px;
            font-weight: 600; white-space: nowrap; }}
  .pos {{ color: #1b7f3b; }} .neg {{ color: #9a3b3b; }}
  td.bd {{ color: #8a93a3; font-size: 11px; }}
  td, th {{ white-space: nowrap; }}
  .wrap {{ max-width: 760px; }}
  .foot {{ padding: 16px 24px; color: #8a93a3; font-size: 11px; line-height: 1.5;
           border-top: 1px solid #eef1f5; }}
  .foot .lk {{ margin-bottom: 10px; font-size: 13px; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>{title}</h1>
      <div class="sub">{generated_at}</div>
      <div class="sum">{summary}</div>
    </div>
    {warning}
    {moved}
    <table>
      <thead>
        <tr>
          <th class="rk">#</th><th class="dl">&Delta;</th><th>Ticker</th>
          <th class="num">Score</th><th></th><th>Action</th>
          <th class="num">Price</th><th class="num">5D</th><th class="num">30D</th>
          <th class="num">%&lt;52wH</th><th>Notes</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}
      </tbody>
    </table>
    {pf}
    <div class="foot">
      {link}
      {disclaimer.strip()}
    </div>
  </div>
</body>
</html>"""


def _sign(v: Optional[float]) -> str:
    if not isinstance(v, (int, float)):
        return ""
    return "pos" if v >= 0 else "neg"
