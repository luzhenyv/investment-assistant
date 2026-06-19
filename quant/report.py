"""Render the weekly review as Markdown (for humans) + JSON (for future tooling)."""
from __future__ import annotations

import json
from dataclasses import asdict

from quant.models import MarketState, OptionAnalysis, Recommendation


def _rec_line(r: Recommendation) -> list[str]:
    lines = [f"### {r.symbol} — **{r.intent}**", f"- {r.reason}"]
    if r.scores:
        scores = ", ".join(f"{k}={v}" for k, v in r.scores.items())
        lines.append(f"- scores: {scores}")
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
    lines.append("")
    return lines


def render_markdown(
    generated_at: str,
    market: MarketState,
    holding_recs: list[Recommendation],
    watchlist_recs: list[Recommendation],
    option_analyses: list[OptionAnalysis],
    summary: dict,
) -> str:
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
        out += _rec_line(r)

    out.append("## Options — action list")
    out.append("")
    if option_analyses:
        for a in option_analyses:
            out += _option_line(a)
    else:
        out.append("_None recorded._")
        out.append("")

    out.append("## Watchlist candidates")
    out.append("")
    if watchlist_recs:
        for r in watchlist_recs:
            out += _rec_line(r)
    else:
        out.append("_None this week (market not constructive, or no setups)._")
        out.append("")

    out.append("---")
    out.append("_Intents are intentions, not trades. You choose strikes and sizing._")
    out.append("_Option P&L is an intrinsic-only floor (no time value); confirm marks with your broker._")
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
) -> None:
    md = render_markdown(
        generated_at, market, holding_recs, watchlist_recs, option_analyses, summary
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
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
