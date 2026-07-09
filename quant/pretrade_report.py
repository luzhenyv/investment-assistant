"""Render the pre-trade brief as Markdown (for humans) + JSON (for the pretrade-check skill).
Mirrors quant/report.py's style; kept separate so the weekly report stays untouched. The `.md`
ends with a `## Catalyst & Timed Action` placeholder the skill fills in (web-search the catalyst,
then a timed go / stage / wait-for-print / stand-aside call)."""
from __future__ import annotations

import json
from dataclasses import asdict

from quant.models import PreTradeBrief


def _money(x) -> str:
    return "—" if x is None else f"${x:,.0f}"


def _n(x, d: int = 1) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def _pct(x, signed: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


def _table(headers: list[str], rows: list[list], aligns: list[str]) -> list[str]:
    sep = ["---:" if a == "r" else "---" for a in aligns]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    out.append("")
    return out


def _position_line(p: dict) -> str:
    """One-line current position + what 'a starter' means in dollars for this name."""
    if not p:
        return ""
    tgt = p.get("target_weight")
    step = p.get("step_size")
    tail = (f"target {_pct(tgt, signed=False)} · 1 step ≈ {_money(step)}"
            if tgt is not None else f"1 step ≈ {_money(step)}")
    if not p.get("held"):
        return f"**Position**: not held · {tail}"
    split = f"{p.get('core'):.0f} core / {p.get('trading'):.0f} trading"
    return (
        f"**Position**: hold {p.get('shares'):.0f} sh ({split}) @ avg {_money(p.get('avg_cost'))} · "
        f"now {_pct(p.get('current_weight'), signed=False)} of {tail} · gap {_money(p.get('gap_to_target'))}"
    )


def _brief_md(b: PreTradeBrief) -> list[str]:
    lv, sc, va, lk = b.live, b.scores, b.valuation, b.levels
    src = "today's session" if lv.get("today_session") else "last close — market closed"
    out = [f"## {b.symbol} — pre-trade brief", ""]

    # Headline: the live-vs-engine gap that motivates this whole layer.
    out.append(
        f"**Live ${lv['last']:,.2f}** ({src}) · today **{_pct(b.today_move_pct)}** vs prev close "
        f"{_money(lv.get('prev_close'))} · engine saw {_money(sc.get('price'))} (daily close)"
    )
    out.append("")

    # Today's tape
    out += _table(
        ["Prev close", "Open", "Session low", "Session high", "Live last", "Today"],
        [[_money(lv.get("prev_close")), _money(lv.get("open")), _money(lv.get("day_low")),
          _money(lv.get("day_high")), _money(lv["last"]), _pct(b.today_move_pct)]],
        ["r", "r", "r", "r", "r", "r"],
    )

    # Engine signal (daily-close) + valuation
    out.append(
        f"**Signal** (daily close): {sc.get('state')} · trend {sc.get('trend'):.0f} · "
        f"mom {sc.get('momentum'):.0f} · RS {_pct(sc.get('rs'), signed=True)} · RSI {sc.get('rsi'):.0f}"
    )
    if va:
        out.append(
            f"**Valuation**: {va.get('label')} · PE {_n(va.get('pe'))} (fwd {_n(va.get('forward_pe'))}) · "
            f"PEG {_n(va.get('peg'), 2)} · target {_money(va.get('analyst_target'))} "
            f"(upside {_pct(va.get('upside_to_target'))})"
        )
    if b.roles:
        out.append(
            f"**Role**: {b.roles.get('role')} · {b.roles.get('horizon')}"
            + (f" — {b.roles['note']}" if b.roles.get("note") else "")
        )
    pos_line = _position_line(b.position)
    if pos_line:
        out.append(pos_line)
    if b.sentiment:
        s = b.sentiment
        net = f"{s['net']:+.2f}" if s.get("net") is not None else "—"
        z = f" · chatter {s['sent_vol_z']:+.1f}σ" if s.get("sent_vol_z") is not None else ""
        out.append(
            f"**Sentiment**: {s.get('label')} · net {net} · {s.get('st_bull')}/{s.get('st_bear')} "
            f"bull/bear of {s.get('st_total')} msgs · {s.get('reddit_posts')} reddit{z}"
        )
    out.append("")

    # Re-anchored levels (distances measured from the LIVE price)
    rows = []
    for label, key, dkey in [
        ("Call wall (resistance)", "call_wall", "to_call_wall"),
        ("Take-profit", "tp_price", "to_tp"),
        ("Max pain", "max_pain", "to_max_pain"),
        ("Stop-loss (role)", "sl_price", "to_sl"),
        ("Gamma flip", "gamma_flip", "to_gamma_flip"),
        ("Put wall (support)", "put_wall", "to_put_wall"),
    ]:
        if lk.get(key) is not None:
            rows.append([label, _money(lk.get(key)), _pct(lk.get(dkey))])
    if rows:
        out.append("**Re-anchored levels** (distance from live price):")
        out.append("")
        out += _table(["Level", "Price", "Dist from live"], rows, ["l", "r", "r"])
        if lk.get("live_rr") is not None:
            out.append(
                f"Live reward:risk **{lk['live_rr']:.1f}:1** "
                f"(up {_pct(lk.get('live_reward'))} to call wall vs down {_pct(lk.get('live_risk'))} "
                f"to put wall)"
            )
            out.append("")
        if lk.get("iv_rank") is not None:
            tone = "rich — favor selling premium" if lk["iv_rank"] >= 0.5 else "cheap — favor buying premium"
            out.append(f"IV rank **{lk['iv_rank']:.0%}** ({tone})")
            out.append("")

    # Earnings gate
    if b.earnings:
        e = b.earnings
        flag = "⚠️ WITHIN GATE" if e.get("within_gate") else "clear"
        est = " (estimated)" if e.get("is_estimate") else ""
        out.append(
            f"**Earnings**: {e['next_date']}{est} — in {e['days_until']}d · {flag}"
            + (f" · {e['sizing_note']}" if e.get("sizing_note") else "")
        )
        out.append("")

    # Market context
    mc = b.market_ctx
    out.append(
        f"**Market context**: SPY {_pct(mc.get('spy_change_pct'))} · QQQ {_pct(mc.get('qqq_change_pct'))} · "
        f"VIX {mc.get('vix'):.1f}" if mc.get("vix") is not None else
        f"**Market context**: SPY {_pct(mc.get('spy_change_pct'))} · QQQ {_pct(mc.get('qqq_change_pct'))}"
    )
    out.append("")

    # Re-anchored human reads
    if b.notes:
        out.append("**Reads:**")
        out += [f"- {n}" for n in b.notes]
        out.append("")

    return out


def generate(md_path: str, json_path: str, generated_at: str, briefs: list[PreTradeBrief]) -> None:
    """Write the `.md` brief (per symbol) and the `.json` the skill reads."""
    lines = [f"# Pre-Trade Brief — {generated_at}", ""]
    lines.append("_Live data overlaid on the weekly engine's signal — the engine runs on daily "
                 "cached bars and is a session behind. Levels are re-anchored to the live price._")
    lines.append("")
    pf = briefs[0].portfolio if briefs else {}
    if pf:
        lines.append(
            f"**Book**: total {_money(pf.get('total_value'))} · cash {_money(pf.get('cash'))} "
            f"({_pct(pf.get('cash_frac'), signed=False)}, {pf.get('cash_status')}) · "
            f"deployable {_money(pf.get('deployable'))}"
        )
        lines.append("")
    for b in briefs:
        lines += _brief_md(b)
        lines.append("---")
        lines.append("")

    lines.append("## Catalyst & Timed Action")
    lines.append("")
    lines.append("_Fill via the `pretrade-check` skill: web-search today's catalyst, classify "
                 "macro/beta vs profit-taking vs thesis-breaking, then give a timed "
                 "go / stage / wait-for-print / stand-aside call with stop + sizing._")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    payload = {"generated_at": generated_at, "briefs": [asdict(b) for b in briefs]}
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
