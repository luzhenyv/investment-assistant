"""The rule engine. Maps market regime + per-symbol scores + portfolio weights to
an *intent* per holding, plus a light watchlist scan. Pure functions — no I/O.

Rules are first-match-wins per holding. Thresholds come from config."""
from __future__ import annotations

from quant.models import Holding, MarketState, Recommendation, Signal

WEAK_REGIMES = {"Correction", "Panic"}
CALM_REGIMES = {"Bull", "Neutral"}


def _scores(sig: Signal) -> dict:
    return {
        "trend": round(sig.trend_score),
        "momentum": round(sig.momentum_score),
        "rsi": round(sig.rsi),
        "price": round(sig.price, 2),
    }


def decide_holding(
    sig: Signal,
    holding: Holding,
    market: MarketState,
    current_weight: float,
    target_weight: float,
    total_value: float,
    cfg: dict,
    cash_low: bool,
) -> Recommendation:
    drift = cfg["drift_band"]
    overbought = cfg["scoring"]["rsi_overbought"]
    gap = (target_weight - current_weight) * total_value  # +add / -trim
    base = dict(symbol=sig.symbol, scores=_scores(sig))

    # 1. Protect existing core in a weakening market.
    if market.regime in WEAK_REGIMES and holding.core > 0:
        return Recommendation(
            intent="Hedge",
            reason=f"Market regime {market.regime}; protect core position.",
            **base,
        )

    # 2. Panic + still structurally strong + room to buy => convert conviction to core.
    if market.regime == "Panic" and sig.price > sig.ma200 and not cash_low:
        return Recommendation(
            intent="Add Core",
            reason="Panic pullback but price holds above MA200 — accumulate quality.",
            dollar_gap=gap,
            **base,
        )

    # 3. Overweight vs target => rebalance down.
    if target_weight > 0 and current_weight > target_weight * (1 + drift):
        over = (current_weight - target_weight) * 100
        return Recommendation(
            intent="Trim",
            reason=f"Overweight by {over:.1f}% of portfolio vs {target_weight:.0%} target.",
            dollar_gap=gap,
            **base,
        )

    # 4. Underweight + healthy pullback + room to buy => add to core.
    if (
        target_weight > 0
        and current_weight < target_weight * (1 - drift)
        and sig.pullback
        and not cash_low
        and market.regime != "Panic"
    ):
        return Recommendation(
            intent="Add Core",
            reason=f"Underweight + pullback to MA50 — add ~${gap:,.0f} to reach target.",
            dollar_gap=gap,
            **base,
        )

    # 5. At/above target and extended => sell premium for income.
    if (
        current_weight >= target_weight
        and sig.rsi > overbought
        and market.regime in CALM_REGIMES
    ):
        return Recommendation(
            intent="Generate Income",
            reason=f"Extended (RSI {sig.rsi:.0f}) and at target — sell premium. "
            "Heuristic: no IV data in v0.1.",
            **base,
        )

    # 6. Default.
    return Recommendation(intent="Hold", reason="No rule triggered.", **base)


def scan_watchlist(
    signals: dict[str, Signal],
    held: set[str],
    market: MarketState,
    top_n: int = 2,
) -> list[Recommendation]:
    """Surface (do not size) new candidates when the market is constructive."""
    if market.regime not in {"Bull", "Strong Bull"}:
        return []
    cands = [
        s
        for sym, s in signals.items()
        if sym not in held and (s.pullback or s.breakout)
    ]
    cands.sort(key=lambda s: (s.trend_score, s.momentum_score), reverse=True)
    out = []
    for s in cands[:top_n]:
        why = "breakout to 52w high" if s.breakout else "pullback to MA50"
        out.append(
            Recommendation(
                symbol=s.symbol,
                intent="Increase Exposure",
                reason=f"Watchlist candidate — {why}, trend {s.trend_score:.0f}.",
                scores=_scores(s),
            )
        )
    return out


def attach_strategy_hints(recs: list[Recommendation], intent_map: dict) -> None:
    for r in recs:
        r.strategy_hint = intent_map.get(r.intent, [])
