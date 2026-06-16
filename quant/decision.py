"""The rule engine. Maps market regime + per-symbol scores + portfolio weights to
an *intent* per holding, plus a light watchlist scan. Pure functions — no I/O.

Rules are first-match-wins per holding. Thresholds come from config."""
from __future__ import annotations

from quant.models import Holding, MarketState, Recommendation, Signal

WEAK_REGIMES = {"Correction", "Panic"}
CALM_REGIMES = {"Bull", "Neutral"}


def effective_target(symbol: str, cfg: dict) -> float:
    """Target weight for a symbol. Hand-set names use their config weight; a
    watchlist name entered without one falls back to the default slot weight."""
    targets = cfg.get("target_weights", {})
    if symbol in targets:
        return targets[symbol]
    return cfg.get("lifecycle", {}).get("entry_default_weight", 0.05)


def effective_ceiling(state: str, target_weight: float, cfg: dict) -> float:
    """Upper weight bound before Trim fires. State-aware: an accelerating winner is
    allowed to run higher (accel_mult) before being rebalanced down; every other
    state trims at the normal drift band. Only the *upper* band is state-aware —
    the lower (Add) band stays target*(1-drift) so we still buy dips at the same
    level."""
    base = target_weight * (1 + cfg["drift_band"])
    if state == "Trend Acceleration":
        return base * cfg.get("lifecycle", {}).get("accel_mult", 1.5)
    return base


def _scores(sig: Signal) -> dict:
    return {
        "state": sig.state,
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

    # 0. Trend is broken (below MA200 / stack collapsed) => exit the whole position.
    #    Sits above Hedge so a broken name leaves rather than just being defended.
    if sig.state == "Broken" and holding.shares > 0:
        return Recommendation(
            intent="Close",
            reason="Trend broken (below MA200 / stack collapsed) — exit to zero.",
            dollar_gap=-current_weight * total_value,
            **base,
        )

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

    # 3. Strong and accelerating with room below its (raised) ceiling => add to
    #    strength. This is the momentum / pyramiding path — buy winners, capped by
    #    the state-aware ceiling so it can't run away.
    ceiling = effective_ceiling(sig.state, target_weight, cfg)
    if (
        sig.state == "Trend Acceleration"
        and target_weight > 0
        and current_weight < ceiling
        and not cash_low
    ):
        add_gap = (ceiling - current_weight) * total_value
        return Recommendation(
            intent="Add Core",
            reason=f"Trend Acceleration — pyramiding toward {ceiling:.0%} ceiling.",
            dollar_gap=add_gap,
            **base,
        )

    # 4. Overweight beyond the state-aware ceiling => rebalance down. Accelerating
    #    names use a raised ceiling above, so a legitimate winner is not trimmed
    #    merely for being over its base target.
    if target_weight > 0 and current_weight > ceiling:
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
    cfg: dict,
    open_slots: int,
) -> list[Recommendation]:
    """Rank unheld candidates and surface up to `open_slots` to open. Entries need a
    constructive regime (skip Panic/Correction), an entry-grade state, and a trend
    score clearing the bar. `open_slots` = max_positions - current position count."""
    if open_slots <= 0 or market.regime in WEAK_REGIMES:
        return []
    entry_min = cfg.get("lifecycle", {}).get("entry_trend_min", 75)
    entry_states = {"Trend Acceleration", "Mean Reversion"}
    cands = [
        s
        for sym, s in signals.items()
        if sym not in held and s.state in entry_states and s.trend_score >= entry_min
    ]
    cands.sort(key=lambda s: (s.trend_score, s.momentum_score), reverse=True)
    out = []
    for s in cands[:open_slots]:
        out.append(
            Recommendation(
                symbol=s.symbol,
                intent="Increase Exposure",
                reason=f"Watchlist entry — {s.state}, trend {s.trend_score:.0f}.",
                scores=_scores(s),
            )
        )
    return out


def attach_strategy_hints(recs: list[Recommendation], intent_map: dict) -> None:
    for r in recs:
        r.strategy_hint = intent_map.get(r.intent, [])
