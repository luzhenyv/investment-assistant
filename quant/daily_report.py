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
    Fundamentals, MacroState, MarketState, OptionAnalysis, OptionPositioning, Recommendation,
    RoleView, SectorState,
)


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _money(x) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _ohlcv_section(ohlcv: dict) -> list[str]:
    """A per-symbol Open/High/Low/Close/Volume table keyed by the bar's date — the user's
    eyeball-checkable record of exactly which session each row priced off."""
    out = ["## Daily OHLCV (verification)", ""]
    out.append("_The raw daily bar behind every record — confirm the session date and prices against "
               "your broker. `Close` is the engine's `price`._")
    out.append("")
    rows = []
    for sym in sorted(ohlcv):
        b = ohlcv[sym]
        rows.append([sym, b["bar_date"], _money(b["open"]), _money(b["high"]), _money(b["low"]),
                     _money(b["close"]), f"{int(b['volume']):,}"])
    out += report._table(
        ["Symbol", "Bar date", "Open", "High", "Low", "Close", "Volume"],
        rows, ["l", "l", "r", "r", "r", "r", "r"],
    )
    return out


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
    ohlcv: dict | None = None,
    as_of_bar: str | None = None,
    stale: bool = False,
    macro: MacroState | None = None,
    sector: SectorState | None = None,
) -> None:
    """Write the daily `.md` (outliers section + the weekly review body) and the `.json`."""
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    roleviews = roleviews or {}
    outliers = outliers or []
    ohlcv = ohlcv or {}

    body = report.render_markdown(
        generated_at, market, holding_recs, watchlist_recs, option_analyses, summary,
        fundamentals, positioning, roleviews, macro, sector,
    ).split("\n")[2:]  # drop the weekly H1 title + its blank line; we set our own header

    lines = [f"# Daily Review — {generated_at}", ""]
    if as_of_bar:
        lines.append(f"_Data as of **{as_of_bar}** (latest daily close) · generated {generated_at}._")
        lines.append("")
        if stale:
            lines.append(f"> ⚠️ **Latest daily bar is {as_of_bar}, not today** — the close shown is the "
                         f"**prior session** (market still open, weekend/holiday, or vendor lag).")
            lines.append("")
    lines += _outliers_section(outliers)
    if ohlcv:
        lines += _ohlcv_section(ohlcv)
    lines += body
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    payload = {
        "generated_at": generated_at,
        "as_of_bar": as_of_bar,
        "stale": stale,
        "market": asdict(market),
        "macro": asdict(macro) if macro is not None else None,
        "sectors": asdict(sector) if sector is not None else None,
        "portfolio": summary,
        "ohlcv": ohlcv,
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
