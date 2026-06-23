"""Render the post-close daily review as Markdown (for humans / the daily-review skill) + JSON.

Reuses the weekly report body wholesale (quant/report.py) and adds one thing on top: an
**Abnormal volume & outliers** section — the names whose volume spiked, state flipped, or RSI hit an
extreme today. That section is the skill's entry point: it explains *why* (catalyst), the way the
pretrade-check skill explains a gap. The `.json` carries the same payload as the weekly report plus
an `outliers` list."""
from __future__ import annotations

import json
from dataclasses import asdict

from quant import report
from quant.models import (
    Fundamentals, MarketState, OptionAnalysis, OptionPositioning, Recommendation, RoleView,
)


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _outliers_section(outliers: list[dict]) -> list[str]:
    out = ["## Abnormal volume & outliers", ""]
    out.append("_The skill's entry point: explain each flag below (catalyst, accumulation vs "
               "distribution, what it implies for tomorrow's plan)._")
    out.append("")
    if not outliers:
        out.append("_No abnormal volume, state change, or RSI extreme today._")
        out.append("")
        return out
    rows = []
    for o in outliers:
        state = o.get("state", "—")
        if o.get("prev_state") and o["prev_state"] != state:
            state = f"{o['prev_state']} → {state}"
        rows.append([
            o["symbol"], _pct(o.get("day_change_pct")), f"{o.get('rvol', 0):.2f}",
            f"{o.get('vol_z', 0):+.1f}", o.get("vol_state", "—"), state,
            f"{o.get('rsi', 0):.0f}", o.get("intent") or "—",
            " · ".join(o.get("flags", [])),
        ])
    out += report._table(
        ["Symbol", "Today", "RVOL", "vol_z", "Vol state", "State", "RSI", "Intent", "Why flagged"],
        rows, ["l", "r", "r", "r", "l", "l", "r", "l", "l"],
    )
    return out


def generate(
    md_path: str,
    json_path: str,
    generated_at: str,
    market: MarketState,
    holding_recs: list[Recommendation],
    watchlist_recs: list[Recommendation],
    option_analyses: list[OptionAnalysis],
    summary: dict,
    fundamentals: dict[str, Fundamentals] | None = None,
    positioning: dict[str, OptionPositioning] | None = None,
    roleviews: dict[str, RoleView] | None = None,
    outliers: list[dict] | None = None,
) -> None:
    """Write the daily `.md` (outliers section + the weekly review body) and the `.json`."""
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    roleviews = roleviews or {}
    outliers = outliers or []

    body = report.render_markdown(
        generated_at, market, holding_recs, watchlist_recs, option_analyses, summary,
        fundamentals, positioning, roleviews,
    ).split("\n")[2:]  # drop the weekly H1 title + its blank line; we set our own header

    lines = [f"# Daily Review — {generated_at}", ""]
    lines += _outliers_section(outliers)
    lines += body
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    payload = {
        "generated_at": generated_at,
        "market": asdict(market),
        "portfolio": summary,
        "outliers": outliers,
        "holdings": [asdict(r) for r in holding_recs],
        "watchlist": [asdict(r) for r in watchlist_recs],
        "options": [asdict(a) for a in option_analyses],
        "fundamentals": {sym: asdict(f) for sym, f in fundamentals.items()},
        "positioning": {sym: asdict(p) for sym, p in positioning.items()},
        "roles": {sym: asdict(rv) for sym, rv in roleviews.items()},
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
