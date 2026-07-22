"""Read-Only Daily Review View Renderer for core.

A pure implementation of the REVIEW_SYSTEM.md contract:
- ONLY reads from Memory as of a specific vantage.
- Generates beautiful, arranged Markdown and JSON reports.
- ORIGINATES NO JUDGMENT (all flags and intents are read directly from stored Assessments and Decisions).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from core import clock
from core.memory import Memory
from core.record import Assessment, Decision


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _signed_money(x: float | None) -> str:
    if x is None or abs(x) < 0.01:
        return "—"
    return f"+${x:,.0f}" if x > 0 else f"-${abs(x):,.0f}"


def _table(headers: list[str], rows: list[list[str]], aligns: list[str]) -> list[str]:
    """Render a GitHub-flavored Markdown table with explicit alignments."""
    out = []
    # Header
    out.append("| " + " | ".join(headers) + " |")
    # Separator
    seps = []
    for a in aligns:
        if a == "r":
            seps.append("---:")
        elif a == "c":
            seps.append(":---:")
        else:
            seps.append(":---")
    out.append("| " + " | ".join(seps) + " |")
    # Rows
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    out.append("")
    return out


def generate_review_views(
    memory: Memory,
    all_symbols: list[str],
    cash: float,
    holdings_dict: dict,
    pre_positions: list[str],
    watch_list: list[str],
    cfg: dict,
    out_dir: str,
    as_of: datetime,
) -> tuple[str, str]:
    """Read the bitemporal Memory as of a vantage instant and generate MD/JSON Review Reports.
    
    No calculations or judgments are made in this function; it merely arranges stored records.
    """
    os.makedirs(out_dir, exist_ok=True)
    generated_at = clock.timestamp(as_of)
    stamp = clock.file_stamp(as_of)
    
    # Read stored Assessments and Decisions
    decisions_list = memory.as_of(as_of, "decision")
    assessments_list = memory.as_of(as_of, "assessment")
    
    # Map decisions by subject (latest first)
    decisions_by_sym: dict[str, Decision] = {}
    for d in sorted(decisions_list, key=lambda d: d.known_at):
        if isinstance(d, Decision) and d.provenance.startswith("sizing_strategy"):
            decisions_by_sym[d.subject] = d
            
    # Map assessments by subject and perspective
    tech_asm_by_sym: dict[str, Assessment] = {}
    left_asm_by_sym: dict[str, Assessment] = {}
    bottom_asm_by_sym: dict[str, Assessment] = {}
    
    for a in sorted(assessments_list, key=lambda a: a.known_at):
        if not isinstance(a, Assessment):
            continue
        if a.provenance.startswith("technical_assessor"):
            tech_asm_by_sym[a.subject] = a
        elif a.provenance.startswith("left_side_entry_assessor"):
            left_asm_by_sym[a.subject] = a
        elif a.provenance.startswith("bottom_fishing_assessor"):
            bottom_asm_by_sym[a.subject] = a
            
    # Resolve the final session close date (the latest Fact event_at)
    fact_dates = [f.event_at for f in memory.as_of(as_of, "fact")]
    as_of_bar = clock.datestamp(as_of)
    if fact_dates:
        as_of_bar = str(max(fact_dates))
        
    stale = as_of_bar < clock.datestamp(as_of)
    
    # Gather output data structures for the reports
    holdings_recs: list[dict] = []
    pre_positions_recs: list[dict] = []
    watchlist_recs: list[dict] = []
    outliers_list: list[dict] = []
    
    # Compute current pricing weights based on bitemporal closing Facts
    equity_value = 0.0
    prices_by_sym: dict[str, float] = {}
    for sym in all_symbols:
        close_f = memory.latest_fact(sym, "close", clock.today(), as_of)
        if close_f is not None:
            prices_by_sym[sym] = close_f.value
            if sym in holdings_dict:
                h = holdings_dict[sym]
                equity_value += h.shares * close_f.value
                
    total_portfolio_value = cash + equity_value
    cash_frac = cash / total_portfolio_value if total_portfolio_value > 0 else 0.0
    
    # Resolve cash band status
    cash_band = cfg.get("cash_band", {"min": 0.10, "max": 0.25})
    cash_status = "ok"
    if cash_frac < cash_band.get("min", 0.10):
        cash_status = "low"
    elif cash_frac > cash_band.get("max", 0.25):
        cash_status = "high"
        
    deployable = max(0.0, cash - cash_band.get("max", 0.25) * total_portfolio_value)
    
    # Loop over symbols to sort into categories
    for sym in sorted(all_symbols):
        d = decisions_by_sym.get(sym)
        t_asm = tech_asm_by_sym.get(sym)
        l_asm = left_asm_by_sym.get(sym)
        b_asm = bottom_asm_by_sym.get(sym)
        
        if not d or not t_asm or not t_asm.payload:
            continue
            
        metrics = json.loads(t_asm.payload)
        d_payload = json.loads(d.payload)
        
        # Build technical Assessment flags (outliers)
        flags = []
        if metrics.get("vol_state") != "Normal":
            flags.append(f"{metrics['vol_state']} volume")
        if abs(metrics.get("vol_z", 0.0)) >= 1.5:
            flags.append(f"Abnormal volume ({metrics['vol_z']:+.1f}σ)")
        if abs(metrics.get("atr_move", 0.0)) >= 1.5:
            flags.append(f"Abnormal ATR move ({metrics['atr_move']:+.1f}x)")
        if metrics.get("rsi", 50.0) >= 70:
            flags.append(f"RSI 超买 ({metrics['rsi']:.0f})")
        elif metrics.get("rsi", 50.0) <= 40:
            flags.append(f"RSI 超卖 ({metrics['rsi']:.0f})")
        if metrics.get("bb_squeeze"):
            flags.append("布林带收口 (Squeeze)")
        if metrics.get("bb_pct_b", 0.5) >= 1.0:
            flags.append("布林带上轨突破")
        elif metrics.get("bb_pct_b", 0.5) <= 0.0:
            flags.append("布林带下轨超卖")
        if metrics.get("macd_cross") != "none":
            cross_name = "金叉" if metrics["macd_cross"] == "golden" else "死叉"
            flags.append(f"MACD {cross_name}")
        if metrics.get("kdj_cross") != "none":
            cross_name = "金叉" if metrics["kdj_cross"] == "golden" else "死叉"
            flags.append(f"KDJ {cross_name}")
        if metrics.get("macd_divergence") != "none":
            div_name = "底背离" if metrics["macd_divergence"] == "bullish" else "顶背离"
            flags.append(f"MACD {div_name}")
        if l_asm and l_asm.result == "candidate":
            flags.append("左侧建仓机遇 (Left-side)")
        if b_asm and b_asm.result == "candidate":
            flags.append("抄底机会 (Bottom-fishing)")
            
        # Build outlier record if any flags exist
        if flags:
            outliers_list.append({
                "symbol": sym,
                "flags": flags,
                "day_change_pct": metrics.get("day_change_pct"),
                "rvol": metrics.get("rvol"),
                "vol_z": metrics.get("vol_z"),
                "vol_state": metrics.get("vol_state"),
                "rsi": metrics.get("rsi"),
                "intent": d_payload.get("intent"),
            })
            
        # Classify symbol record by membership category
        membership = d_payload.get("membership")
        rec_entry = {
            "symbol": sym,
            "intent": d_payload.get("intent"),
            "reason": d_payload.get("reason"),
            "dollar_gap": d_payload.get("dollar_gap"),
            "rsi": metrics.get("rsi"),
            "trend_score": metrics.get("trend_score"),
            "price": metrics.get("price"),
            "support": metrics.get("support"),
            "resistance": metrics.get("resistance"),
            "valuation": metrics.get("valuation_label"),
            "role": d_payload.get("role"),
            "pnl_pct": 0.0,
            "shares": 0.0,
            "avg_cost": 0.0,
        }
        
        if membership == "holding" and sym in holdings_dict:
            h = holdings_dict[sym]
            rec_entry["shares"] = h.shares
            rec_entry["avg_cost"] = h.avg_cost
            if h.avg_cost > 0:
                rec_entry["pnl_pct"] = (price - h.avg_cost) / h.avg_cost
            holdings_recs.append(rec_entry)
        elif membership == "pre_position":
            pre_positions_recs.append(rec_entry)
        else:
            watchlist_recs.append(rec_entry)
            
    # --- RENDER MARKDOWN REPORT ---
    lines = [
        f"# Core Daily Review — {generated_at}",
        "",
        f"_Bitemporal data as of **{as_of_bar}** (latest daily close) · Vantage generated {generated_at}._",
        "",
    ]
    
    if stale:
        lines.append(f"> ⚠️ **Latest daily close is {as_of_bar}, not today** — the close shown is the prior session (market open / holiday lag).")
        lines.append("")
        
    # Section 1: Abnormal volume & outliers (Technical Assessments)
    lines.append("## Abnormal volume & outliers")
    lines.append("")
    lines.append("_Technical indicator and strategy-candidate Assessments generated by the system today:_")
    lines.append("")
    
    if not outliers_list:
        lines.append("_No abnormal volume, state changes, or technical extremes flagged today._")
        lines.append("")
    else:
        rows = []
        for o in outliers_list:
            rows.append([
                o["symbol"],
                _pct(o.get("day_change_pct")),
                f"{o.get('rvol', 0.0):.2f}",
                f"{o.get('vol_z', 0.0):+.1f}",
                o.get("vol_state", "—"),
                f"{o.get('rsi', 0.0):.0f}",
                o.get("intent", "—"),
                " · ".join(o["flags"]),
            ])
        lines += _table(
            ["Symbol", "Today", "RVOL", "vol_z", "Vol state", "RSI", "Intent", "Why flagged"],
            rows, ["l", "r", "r", "r", "l", "r", "l", "l"]
        )
        
    # Section 2: Portfolio Stats
    lines.append("## Portfolio")
    lines.append("")
    lines += _table(
        ["Total value", "Cash", "Cash %", "Status", "Deployable"],
        [[f"${total_portfolio_value:,.0f}", f"${cash:,.0f}",
          f"{cash_frac:.1%}", cash_status,
          f"${deployable:,.0f}" if deployable > 0 else "—"]],
        ["r", "r", "r", "l", "r"],
    )
    if cash_status == "low":
        lines.append("- ⚠️ Cash below floor — **no new buys suggested**.")
        lines.append("")
        
    # Section 3: Position Management Actions (Holdings)
    lines.append("## Holdings — Sizing & Exit Alerts")
    lines.append("")
    if not holdings_recs:
        lines.append("_No holdings recorded._")
        lines.append("")
    else:
        rows = []
        for h in holdings_recs:
            rows.append([
                h["symbol"], h["intent"], _signed_money(h["dollar_gap"]),
                h["role"], _money(h["avg_cost"]), _pct(h["pnl_pct"]), h["reason"]
            ])
        lines += _table(
            ["Symbol", "Sizing Rec", "$ Gap", "Role", "Cost Basis", "Current P&L", "Reason / Strategy Alert"],
            rows, ["l", "l", "r", "l", "r", "r", "l"]
        )
        
    # Section 4: High Priority Pre-Positions (随时准备建仓)
    lines.append("## Pre-Position candidates (随时建仓 / 重点关注)")
    lines.append("")
    lines.append("_Positions scheduled for purchase. Waiting for key technical breakout or stop-falling support reversal:_")
    lines.append("")
    if not pre_positions_recs:
        lines.append("_No pre-positions configured in portfolio.yaml._")
        lines.append("")
    else:
        rows = []
        for p in pre_positions_recs:
            setup = "Near Support" if p["support"] and abs(p["price"] - p["support"]) / p["price"] <= 0.05 else "Basing"
            rows.append([
                p["symbol"], p["intent"], _signed_money(p["dollar_gap"]),
                _money(p["price"]), _money(p["support"]) if p["support"] else "—", setup, p["reason"]
            ])
        lines += _table(
            ["Symbol", "Action Recommendation", "$ Gap", "Price", "Nearest Support", "Setup Status", "Technical Condition"],
            rows, ["l", "l", "r", "r", "r", "l", "l"]
        )
        
    # Section 5: Watchlist Candidates
    lines.append("## Watchlist candidates")
    lines.append("")
    lines.append("_Scan candidates eligible to open relative to technical indicators, RS levels, and Left-Side/Bottom-Fishing signals:_")
    lines.append("")
    if not watchlist_recs:
        lines.append("_None matching watchlist entry criteria today._")
        lines.append("")
    else:
        rows = []
        for w in watchlist_recs:
            rows.append([
                w["symbol"], w["intent"], _signed_money(w["dollar_gap"]),
                f"{w['trend_score']:.0f}", f"{w['rsi']:.0f}", w["valuation"], w["reason"]
            ])
        lines += _table(
            ["Symbol", "Action Recommendation", "$ Gap", "Trend Score", "RSI", "Valuation", "Technical Rationale"],
            rows, ["l", "l", "r", "r", "r", "l", "l"]
        )
        
    lines.append("---")
    lines.append("_Intents and proposed sizing steps are rule-based policy suggestions. Confirm all parameters before trade execution._")
    
    md_content = "\n".join(lines)
    md_path = os.path.join(out_dir, f"daily_review_{stamp}.md")
    with open(md_path, "w") as f:
        f.write(md_content)
        
    # --- RENDER JSON VIEW PAYLOAD ---
    json_payload = {
        "generated_at": generated_at,
        "as_of_bar": as_of_bar,
        "stale": stale,
        "portfolio": {
            "cash": cash,
            "total_value": total_portfolio_value,
            "cash_frac": cash_frac,
            "cash_status": cash_status,
            "deployable": deployable,
        },
        "outliers": outliers_list,
        "holdings": holdings_recs,
        "pre_positions": pre_positions_recs,
        "watchlist": watchlist_recs,
    }
    
    json_content = json.dumps(json_payload, indent=2, ensure_ascii=False)
    json_path = os.path.join(out_dir, f"daily_review_{stamp}.json")
    with open(json_path, "w") as f:
        f.write(json_content)
        
    return md_path, json_path
