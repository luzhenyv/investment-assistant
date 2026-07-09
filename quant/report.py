"""Render the weekly review as Markdown (for humans) + JSON (for future tooling)."""
from __future__ import annotations

import json
from dataclasses import asdict

from quant import levels as levels_mod
from quant.models import (
    Fundamentals, MacroState, MarketState, OptionAnalysis, OptionPositioning, Recommendation,
    RoleView, SectorState, SentimentView, Zone,
)


def _macro_block(macro: MacroState) -> list[str]:
    """Compact macro-backdrop block — context that runs parallel to the market regime; never
    feeds the engine. Surfaced for the macro-review skill to overlay the calendar/catalyst."""
    out = [f"## Macro backdrop: **{macro.backdrop}**", ""]
    for note in macro.notes:
        out.append(f"- {note}")
    out.append("")
    out.append("_Report-only FRED context (does not feed scoring/decision). The macro-review skill "
               "adds the calendar (FOMC/CPI/PCE/NFP) and what would change the read._")
    out.append("")
    return out


def _sector_block(sector: SectorState) -> list[str]:
    """Sector-rotation block — configurable ETF map classified into RRG quadrants + abnormality
    flags. Report-only context parallel to the market/macro blocks; never feeds the engine."""
    out = [f"## Sector rotation: **{sector.backdrop}**", ""]
    for note in sector.notes:
        out.append(f"- {note}")
    out.append("")
    rows = []
    for r in sector.rows:
        rows.append([
            r.symbol, r.group, r.quadrant, f"{r.day_change_pct:+.1%}",
            f"{r.rs_micro:+.0%}", f"{r.rs_fast:+.0%}", f"{r.rs_slow:+.0%}",
            r.vol_state, f"{r.rsi:.0f}", " · ".join(r.flags) or "—",
        ])
    out += _table(
        ["ETF", "Group", "Quadrant", "Day", "RS 5d", "RS 21d", "RS 63d", "Vol", "RSI", "Flags"],
        rows, ["l", "l", "l", "r", "r", "r", "r", "l", "r", "l"],
    )
    if sector.rotations:
        out.append("**Rotation / abnormal flags:**")
        out += [f"- {r}" for r in sector.rotations]
        out.append("")
    out.append("_Report-only ETF rotation (RRG quadrant off relative strength vs SPY; does not feed "
               "scoring/decision). RS is relative return vs SPY over 5d/21d/63d._")
    out.append("")
    return out


def _fmt(x, money=True, pct=False):
    if x is None:
        return "—"
    if pct:
        return f"{x:+.0%}"
    return f"${x:,.0f}" if money else f"{x:.2f}"


def _signed_money(x) -> str:
    """Signed dollar amount for the $ Gap column (`—` when None), e.g. +$849 / -$3,190."""
    if x is None:
        return "—"
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def _rs_pct(rs) -> str:
    """RS is a trailing-return fraction; show as a percentage (+22%, +1025%)."""
    return f"{rs:+.0%}" if rs is not None else "—"


def _table(headers: list[str], rows: list[list], aligns: list[str] | None = None) -> list[str]:
    """A GitHub-flavoured Markdown table as a list of lines (trailing blank line).
    `aligns` is a per-column list of 'l' | 'r'; 'r' right-aligns the column."""
    aligns = aligns or ["l"] * len(headers)
    sep = ["---:" if a == "r" else "---" for a in aligns]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    out.append("")
    return out


def _recs_actions_table(recs: list[Recommendation], roleviews: dict[str, RoleView]) -> list[str]:
    """The 'what to do' table: intent, sizing step, role/horizon and the exit pair."""
    rows = []
    for r in recs:
        rv = roleviews.get(r.symbol)
        role_h, tpsl = "—", "—"
        if rv is not None:
            role_h = f"{rv.role} · {rv.horizon}" if rv.horizon and rv.horizon != "—" else rv.role
            if rv.tp_price is not None and rv.sl_price is not None:
                tpsl = f"${rv.tp_price:,.0f} / ${rv.sl_price:,.0f}"
        rows.append([r.symbol, r.intent, _signed_money(r.dollar_gap), role_h, tpsl])
    return _table(
        ["Symbol", "Intent", "$ Gap", "Role · Horizon", "TP / SL"],
        rows, ["l", "l", "r", "l", "r"],
    )


def _recs_signals_table(
    recs: list[Recommendation], fundamentals: dict[str, Fundamentals], with_sector: bool
) -> list[str]:
    """The 'why' table: the horizon signals side by side, plus a valuation summary."""
    headers = ["Symbol", "State", "Trend", "Mom", "RS", "RSI", "Price"]
    aligns = ["l", "l", "r", "r", "r", "r", "r"]
    if with_sector:
        headers.append("Sector")
        aligns.append("l")
    headers += ["Valuation", "Target"]
    aligns += ["l", "r"]
    rows = []
    for r in recs:
        s = r.scores or {}
        f = fundamentals.get(r.symbol)
        row = [
            r.symbol, s.get("state", "—"), s.get("trend", "—"), s.get("momentum", "—"),
            _rs_pct(s.get("rs")), s.get("rsi", "—"), _fmt(s.get("price")),
        ]
        if with_sector:
            row.append(s.get("sector", "—"))
        row.append(f.valuation_label if f is not None else "—")
        row.append(_fmt(f.upside_to_target, pct=True) if f is not None else "—")
        rows.append(row)
    return _table(headers, rows, aligns)


def _recs_notes(
    recs: list[Recommendation], fundamentals: dict[str, Fundamentals], roleviews: dict[str, RoleView],
    levels: dict[str, list[Zone]] | None = None,
) -> list[str]:
    """One compact note per symbol: the reason, the valuation detail not in the table
    (PE/fwd/PEG), the role-mismatch flag, the playbook, ways to express, nearest S/R."""
    levels = levels or {}
    lines = []
    for r in recs:
        f = fundamentals.get(r.symbol)
        rv = roleviews.get(r.symbol)
        parts: list[str] = [r.reason] if r.reason else []
        if f is not None:
            if f.pe is not None:
                parts.append(f"PE {f.pe:.1f}" + (f" (fwd {f.forward_pe:.1f})" if f.forward_pe is not None else ""))
            elif f.forward_pe is not None:
                parts.append(f"fwd PE {f.forward_pe:.1f}")
            if f.peg is not None:
                parts.append(f"PEG {f.peg:.2f}")
            if f.stale:
                parts.append("⚠ stale")
        if rv is not None:
            if not rv.agree and rv.source == "config":
                parts.append(f"role mismatch (suggested {rv.suggested_role} ⚠)")
            if rv.playbook:
                parts.append("playbook: " + ", ".join(rv.playbook))
        if r.strategy_hint:
            parts.append("express: " + ", ".join(r.strategy_hint))
        if rv is not None and rv.user_plan:
            engine = f"{rv.role} · {rv.horizon}" if rv.horizon and rv.horizon != "—" else rv.role
            parts.append(f"📝 your plan: {rv.user_plan} (engine: {engine})")
        zs = levels.get(r.symbol)
        if zs:
            sup, res = levels_mod.nearest_zones(None, zs)
            sr = []
            if sup is not None:
                sr.append(f"S ${sup.mid:,.0f} ({sup.label}·{len(sup.methods)}m)")
            if res is not None:
                sr.append(f"R ${res.mid:,.0f} ({res.label}·{len(res.methods)}m)")
            if sr:
                parts.append("S/R: " + " / ".join(sr))
        if parts:
            lines.append(f"- **{r.symbol}** — " + " · ".join(parts))
    if lines:
        lines.append("")
    return lines


def _options_tables(option_analyses: list[OptionAnalysis]) -> list[str]:
    """Structure/P&L table + Greeks table + a note per position (legs, assignment risk)."""
    sp_rows, gk_rows, notes = [], [], []
    for a in option_analyses:
        m = a.metrics
        pos = f"{a.underlying} {a.type.upper()}" if a.type else a.underlying
        dte = m.get("short_dte") if m.get("short_dte") is not None else m.get("nearest_dte")
        be = f"${m['breakeven']:,.2f}" if m.get("breakeven") is not None else "—"
        if m.get("max_profit") is not None and m.get("max_loss") is not None:
            cap = f"${m['max_profit']:,.0f} / ${m['max_loss']:,.0f}"
        else:
            cap = "—"
        sp_rows.append([
            pos, a.intent, f"${m['underlying_price']:,.2f}", dte, be,
            f"${m['net_debit']:,.2f}", f"${m['pnl_floor']:+,.0f}", cap,
        ])
        if a.greeks:
            g = a.greeks
            gk_rows.append([
                pos, f"{g['net_delta']:+.0f}", f"${g['net_theta']:+,.2f}",
                f"${g['net_vega']:+,.2f}", f"{g['net_gamma']:+.3f}", f"${g['net_rho']:+,.2f}",
            ])
        else:
            gk_rows.append([pos, "—", "—", "—", "—", "—"])
        nparts = [a.reason] if a.reason else []
        nparts.append(f"legs: {m['legs']}")
        if m.get("assignment_risk"):
            nparts.append("ITM → assignment risk")
        notes.append(f"- **{pos}** — " + " · ".join(nparts))
    out = _table(
        ["Position", "Intent", "Spot", "DTE", "Breakeven", "Net cost", "P&L floor", "Max P / L"],
        sp_rows, ["l", "l", "r", "r", "r", "r", "r", "r"],
    )
    out.append("### Greeks (net)")
    out.append("")
    out += _table(
        ["Position", "Δ (sh)", "Θ /day", "Vega /1%", "Γ", "ρ /1%"],
        gk_rows, ["l", "r", "r", "r", "r", "r"],
    )
    if notes:
        out += notes + [""]
    return out


def _positioning_tables(positioning: dict[str, OptionPositioning]) -> list[str]:
    """One row per underlying; confluence/warning notes below (the expected-move and
    reward:risk lines are dropped — they're columns now)."""
    rows, notes = [], []
    for sym in sorted(positioning):
        p = positioning[sym]
        walls = f"{_fmt(p.put_wall)} / {_fmt(p.call_wall)}"
        em = f"±${p.em:,.0f} ({p.em_pct:.0%})" if p.em is not None else "—"
        rr = f"{p.rr_ratio:.1f}:1" if p.rr_ratio is not None else "—"
        pcoi = f"{p.pc_oi:.2f}" if p.pc_oi is not None else "—"
        iv = f"{p.atm_iv:.0%}" if p.atm_iv is not None else "—"
        skew = f"{p.iv_skew:+.0%}" if p.iv_skew is not None else "—"
        gflip = f"${p.gamma_flip:,.0f}" if p.gamma_flip is not None else "—"
        ivr = f"{p.iv_rank:.0%}" if p.iv_rank is not None else "—"
        rows.append([p.symbol, f"${p.spot:,.2f}", walls, _fmt(p.max_pain), gflip,
                     em, rr, pcoi, iv, ivr, skew])
        kept = [n for n in p.notes
                if not n.startswith("expected move") and not n.startswith("reward:risk")]
        if kept:
            notes.append(f"- **{p.symbol}** — " + " · ".join(kept))
    out = _table(
        ["Symbol", "Spot", "Put/Call wall", "Max pain", "Gamma flip", "Exp move", "R:R", "P/C OI",
         "ATM IV", "IV rank", "Skew"],
        rows, ["l", "r", "r", "r", "r", "r", "r", "r", "r", "r", "r"],
    )
    if notes:
        out += notes + [""]
    return out


def _sentiment_tables(sentiment: dict[str, SentimentView]) -> list[str]:
    """One row per symbol: the retail-sentiment label, net bull/bear, message + Reddit volume, and
    the chatter z-score; contrarian / low-sample notes below."""
    rows, notes = [], []
    for sym in sorted(sentiment):
        s = sentiment[sym]
        net = f"{s.st_net:+.2f}" if s.st_net is not None else "—"
        z = f"{s.sent_vol_z:+.1f}σ" if s.sent_vol_z is not None else "—"
        rows.append([s.symbol, s.sentiment_label, net, f"{s.st_bull}/{s.st_bear}",
                     s.st_unlabeled, s.st_total, z, s.reddit_posts])
        if s.notes:
            notes.append(f"- **{s.symbol}** — " + " · ".join(s.notes))
    out = _table(
        ["Symbol", "Label", "Net", "Bull/Bear", "Unlbl", "Msgs", "Chatter z", "Reddit"],
        rows, ["l", "l", "r", "r", "r", "r", "r", "r"],
    )
    if notes:
        out += notes + [""]
    out.append("_Report-only retail sentiment (StockTwits Bull/Bear labels + Reddit post volume; does "
               "not feed scoring/decision). Net = (bull−bear)/labelled ∈ [−1,1]; Chatter z = message "
               "count vs this store's history. The sentiment-review skill adds the catalyst/divergence read._")
    out.append("")
    return out


def _zone_str(z: Zone | None) -> str:
    """A zone as a price band + strength tag: hand-curated → `$118–$121 (strong·curated)`,
    auto-detected → `$118–$121 (strong·3m·flip)` (distinct-method confluence count)."""
    if z is None:
        return "—"
    if z.methods == ["manual"]:
        tag = f"{z.label}·curated"
    else:
        tag = f"{z.label}·{len(z.methods)}m" + ("·flip" if z.flipped else "")
    return f"${z.low:,.0f}–${z.high:,.0f} ({tag})"


_SRC_TAG = {"manual": "curated", "manual-stale": "curated ⚠stale", "auto": "auto"}


def _levels_block(levels: dict[str, list[Zone]], levels_source: dict[str, str]) -> list[str]:
    """One row per symbol: nearest support below and nearest resistance above, the strength label,
    and provenance (curated / auto). Report-only structural S/R — a hand-curated levels.yaml is
    authoritative where present; the auto detector's edge is concentrated in ≥3-method support."""
    rows = []
    for sym in sorted(levels):
        sup, res = levels_mod.nearest_zones(None, levels[sym])
        rows.append([sym, _zone_str(sup), _zone_str(res),
                     _SRC_TAG.get(levels_source.get(sym, "auto"), "auto")])
    out = ["## Support / Resistance (structural)", ""]
    out += _table(["Symbol", "Nearest support", "Nearest resistance", "Src"],
                  rows, ["l", "r", "r", "l"])
    n_stale = sum(1 for s in levels_source.values() if s == "manual-stale")
    if n_stale:
        out.append(f"- ⚠️ {n_stale} name(s) on **stale curation** (past `manual_refresh_days`) — "
                   f"re-review and bump their `as_of` in `levels.yaml`.")
        out.append("")
    out.append("_Report-only S/R (does not feed scoring/decision). `curated` = hand-set in "
               "levels.yaml (authoritative); `auto` = quant/levels.py detector, whose edge is "
               "concentrated in ≥3-method support. Treat strength as a prior, not a hard level._")
    out.append("")
    return out


def render_markdown(
    generated_at: str,
    market: MarketState,
    holding_recs: list[Recommendation],
    watchlist_recs: list[Recommendation],
    option_analyses: list[OptionAnalysis],
    summary: dict,
    fundamentals: dict[str, Fundamentals] | None = None,
    positioning: dict[str, OptionPositioning] | None = None,
    roleviews: dict[str, RoleView] | None = None,
    macro: MacroState | None = None,
    sector: SectorState | None = None,
    levels: dict[str, list[Zone]] | None = None,
    levels_source: dict[str, str] | None = None,
    sentiment: dict[str, SentimentView] | None = None,
) -> str:
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    roleviews = roleviews or {}
    levels = levels or {}
    levels_source = levels_source or {}
    sentiment = sentiment or {}
    out: list[str] = [f"# Weekly Investment Review — {generated_at}", ""]

    out.append(f"## Market: **{market.regime}**  (bull score {market.bull_score:.0f}/100)")
    for note in market.notes:
        out.append(f"- {note}")
    out.append("")

    if macro is not None:
        out += _macro_block(macro)

    if sector is not None:
        out += _sector_block(sector)

    out.append("## Portfolio")
    out.append("")
    deployable = summary.get("deployable")
    out += _table(
        ["Total value", "Cash", "Cash %", "Status", "Deployable"],
        [[f"${summary['total_value']:,.0f}", f"${summary['cash']:,.0f}",
          f"{summary['cash_frac']:.1%}", summary["cash_status"],
          f"${deployable:,.0f}" if deployable is not None else "—"]],
        ["r", "r", "r", "l", "r"],
    )
    if summary["cash_status"] == "low":
        out.append("- ⚠️ Cash below floor — **no new buys this week** (Add/Income suppressed).")
        out.append("")
    elif summary["cash_status"] == "high":
        out.append(f"- Cash above ceiling — consider deploying up to ${summary['deployable']:,.0f}.")
        out.append("")

    unconfigured = summary.get("unconfigured_targets") or []
    if unconfigured:
        out.append("## ⚙️ Config reminder")
        out.append(
            f"- Held / buy-candidate names with **no `target_weights` entry**, sized at the "
            f"default {summary.get('default_weight', 0):.0%}: **{', '.join(unconfigured)}**."
        )
        out.append("- Set an explicit weight in `config.yaml: target_weights` to size them intentionally.")
        out.append("")

    out.append("## Holdings — actions")
    out.append("")
    out += _recs_actions_table(holding_recs, roleviews)
    out.append("### Signals & valuation")
    out.append("")
    out += _recs_signals_table(holding_recs, fundamentals, with_sector=False)
    notes = _recs_notes(holding_recs, fundamentals, roleviews, levels)
    if notes:
        out.append("### Notes")
        out.append("")
        out += notes

    out.append("## Options — actions")
    out.append("")
    if option_analyses:
        out += _options_tables(option_analyses)
    else:
        out.append("_None recorded._")
        out.append("")

    if positioning:
        out.append("## Options Positioning (S/R from the chain)")
        out.append("")
        out += _positioning_tables(positioning)

    if levels:
        out += _levels_block(levels, levels_source)

    if sentiment:
        out.append("## Social sentiment (retail)")
        out.append("")
        out += _sentiment_tables(sentiment)

    out.append("## Watchlist candidates")
    out.append("")
    if watchlist_recs:
        out += _recs_actions_table(watchlist_recs, roleviews)
        out.append("### Signals & valuation")
        out.append("")
        out += _recs_signals_table(watchlist_recs, fundamentals, with_sector=True)
        notes = _recs_notes(watchlist_recs, fundamentals, roleviews, levels)
        if notes:
            out.append("### Notes")
            out.append("")
            out += notes
    else:
        out.append("_None this week (market not constructive, or no setups)._")
        out.append("")

    out.append("---")
    out.append("_Intents are intentions, not trades. You choose strikes and sizing._")
    out.append("_Option P&L is an intrinsic-only floor (no time value); confirm marks with your broker._")
    out.append("_Greeks are Black-Scholes from live implied vol (q=0); deep-ITM IV can be unreliable._")
    if fundamentals:
        out.append("_Valuation hints are from Alpha Vantage: trailing GAAP PE can mislead for cyclicals "
                   "(watch forward PE); analyst target is lagging consensus._")
    if positioning:
        out.append("_Option positioning is free yfinance data: EOD OI lags ~1 day, there's no buy/sell "
                   "flow direction, and walls/max-pain are tendencies (not levels). Not backtested._")
    return "\n".join(out)


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
    macro: MacroState | None = None,
    sector: SectorState | None = None,
    levels: dict[str, list[Zone]] | None = None,
    levels_source: dict[str, str] | None = None,
    sentiment: dict[str, SentimentView] | None = None,
) -> None:
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    roleviews = roleviews or {}
    levels = levels or {}
    levels_source = levels_source or {}
    sentiment = sentiment or {}
    md = render_markdown(
        generated_at, market, holding_recs, watchlist_recs, option_analyses, summary,
        fundamentals, positioning, roleviews, macro, sector, levels, levels_source, sentiment,
    )
    with open(md_path, "w") as f:
        f.write(md)

    payload = {
        "generated_at": generated_at,
        "market": asdict(market),
        "macro": asdict(macro) if macro is not None else None,
        "sectors": asdict(sector) if sector is not None else None,
        "portfolio": summary,
        "holdings": [asdict(r) for r in holding_recs],
        "watchlist": [asdict(r) for r in watchlist_recs],
        "options": [asdict(a) for a in option_analyses],
        "fundamentals": {sym: asdict(f) for sym, f in fundamentals.items()},
        "positioning": {sym: asdict(p) for sym, p in positioning.items()},
        "roles": {sym: asdict(rv) for sym, rv in roleviews.items()},
        "levels": {sym: [asdict(z) for z in zs] for sym, zs in levels.items()},
        "levels_source": levels_source,
        "sentiment": {sym: asdict(v) for sym, v in sentiment.items()},
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
