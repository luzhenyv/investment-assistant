"""Render the weekly review as Markdown (for humans) + JSON (for future tooling)."""
from __future__ import annotations

import json
from dataclasses import asdict

from quant.models import (
    Fundamentals, MarketState, OptionAnalysis, OptionPositioning, Recommendation,
)


def _valuation_line(f: Fundamentals) -> str:
    """One-line valuation hint, e.g.
    `- valuation: PE 53.5 (fwd 10.5), PEG 0.36 · target $946 (+9%) · cheap (growth-justified) ⚠ stale`"""
    parts: list[str] = []
    if f.pe is not None:
        parts.append(f"PE {f.pe:.1f}" + (f" (fwd {f.forward_pe:.1f})" if f.forward_pe is not None else ""))
    elif f.forward_pe is not None:
        parts.append(f"fwd PE {f.forward_pe:.1f}")
    if f.peg is not None:
        parts.append(f"PEG {f.peg:.2f}")
    if f.analyst_target is not None:
        up = f" ({f.upside_to_target:+.0%})" if f.upside_to_target is not None else ""
        parts.append(f"target ${f.analyst_target:,.0f}{up}")
    parts.append(f.valuation_label)
    line = "- valuation: " + " · ".join(parts)
    return line + " ⚠ stale" if f.stale else line


def _rec_line(r: Recommendation, fund: Fundamentals | None = None) -> list[str]:
    lines = [f"### {r.symbol} — **{r.intent}**", f"- {r.reason}"]
    if r.scores:
        scores = ", ".join(f"{k}={v}" for k, v in r.scores.items())
        lines.append(f"- scores: {scores}")
    if fund is not None:
        lines.append(_valuation_line(fund))
    if r.strategy_hint:
        lines.append(f"- ways to express: {', '.join(r.strategy_hint)}")
    lines.append("")
    return lines


def _option_line(a: OptionAnalysis) -> list[str]:
    """Lines for a single option strategy in markdown."""
    m = a.metrics
    title = f"{a.underlying} {a.type.upper()}" if a.type else a.underlying
    lines = [f"### {title} — **{a.intent}**", f"- {a.reason}"]
    lines.append(f"- underlying ${m['underlying_price']:,.2f} ({m['legs']})")
    dte = m.get("short_dte") if m.get("short_dte") is not None else m.get("nearest_dte")
    risk = " · ITM → assignment risk" if m.get("assignment_risk") else ""
    if m.get("breakeven") is not None:
        lines.append(f"- DTE {dte}{risk} · breakeven ${m['breakeven']:,.2f}")
    else:
        lines.append(f"- DTE {dte}{risk}")
    cap = ""
    if m.get("max_profit") is not None and m.get("max_loss") is not None:
        cap = f" · max profit ${m['max_profit']:,.0f} / max loss ${m['max_loss']:,.0f}"
    lines.append(f"- net cost ${m['net_debit']:,.2f}/sh · intrinsic-floor P&L ${m['pnl_floor']:+,.0f}{cap}")
    if a.greeks:
        g = a.greeks
        lines.append(
            f"- Greeks (net): Δ {g['net_delta']:+.0f} sh · Θ ${g['net_theta']:+,.2f}/day · "
            f"vega ${g['net_vega']:+,.2f}/1% · Γ {g['net_gamma']:+.3f} · ρ ${g['net_rho']:+,.2f}/1%"
        )
    else:
        lines.append("- Greeks: unavailable (live IV not found)")
    lines.append("")
    return lines


def _fmt(x, money=True, pct=False):
    if x is None:
        return "—"
    if pct:
        return f"{x:+.0%}"
    return f"${x:,.0f}" if money else f"{x:.2f}"


def _positioning_line(p: OptionPositioning) -> list[str]:
    """Lines for one underlying's option-chain positioning."""
    lines = [f"### {p.symbol} — spot ${p.spot:,.2f} · {p.expiry} ({p.dte}d)"]
    lines.append(
        f"- put wall {_fmt(p.put_wall)} · call wall {_fmt(p.call_wall)} · max pain {_fmt(p.max_pain)}"
    )
    if p.em is not None:
        lines.append(f"- expected move ±${p.em:,.0f} ({p.em_pct:.0%}) → {_fmt(p.em_low)}–{_fmt(p.em_high)}")
    rr = f"{p.rr_ratio:.1f}:1" if p.rr_ratio is not None else "—"
    pcoi = f"{p.pc_oi:.2f}" if p.pc_oi is not None else "—"
    iv = f"{p.atm_iv:.0%}" if p.atm_iv is not None else "—"
    skew = f"{p.iv_skew:+.0%}" if p.iv_skew is not None else "—"
    lines.append(f"- reward:risk {rr} · P/C OI {pcoi} · ATM IV {iv} · skew {skew}")
    for n in p.notes:
        lines.append(f"- {n}")
    lines.append("")
    return lines


def render_markdown(
    generated_at: str,
    market: MarketState,
    holding_recs: list[Recommendation],
    watchlist_recs: list[Recommendation],
    option_analyses: list[OptionAnalysis],
    summary: dict,
    fundamentals: dict[str, Fundamentals] | None = None,
    positioning: dict[str, OptionPositioning] | None = None,
) -> str:
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    out: list[str] = [f"# Weekly Investment Review — {generated_at}", ""]

    out.append(f"## Market: **{market.regime}**  (bull score {market.bull_score:.0f}/100)")
    for note in market.notes:
        out.append(f"- {note}")
    out.append("")

    out.append("## Portfolio")
    out.append(f"- Total value: ${summary['total_value']:,.0f}")
    out.append(f"- Cash: ${summary['cash']:,.0f} ({summary['cash_frac']:.1%}) — {summary['cash_status']}")
    if summary["cash_status"] == "low":
        out.append("- ⚠️ Cash below floor — **no new buys this week** (Add/Income suppressed).")
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

    out.append("## Holdings — action list")
    out.append("")
    for r in holding_recs:
        out += _rec_line(r, fundamentals.get(r.symbol))

    out.append("## Options — action list")
    out.append("")
    if option_analyses:
        for a in option_analyses:
            out += _option_line(a)
    else:
        out.append("_None recorded._")
        out.append("")

    if positioning:
        out.append("## Options Positioning (S/R from the chain)")
        out.append("")
        for sym in sorted(positioning):
            out += _positioning_line(positioning[sym])

    out.append("## Watchlist candidates")
    out.append("")
    if watchlist_recs:
        for r in watchlist_recs:
            out += _rec_line(r, fundamentals.get(r.symbol))
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
) -> None:
    fundamentals = fundamentals or {}
    positioning = positioning or {}
    md = render_markdown(
        generated_at, market, holding_recs, watchlist_recs, option_analyses, summary,
        fundamentals, positioning,
    )
    with open(md_path, "w") as f:
        f.write(md)

    payload = {
        "generated_at": generated_at,
        "market": asdict(market),
        "portfolio": summary,
        "holdings": [asdict(r) for r in holding_recs],
        "watchlist": [asdict(r) for r in watchlist_recs],
        "options": [asdict(a) for a in option_analyses],
        "fundamentals": {sym: asdict(f) for sym, f in fundamentals.items()},
        "positioning": {sym: asdict(p) for sym, p in positioning.items()},
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
