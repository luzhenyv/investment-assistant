"""The rule engine. Maps market regime + per-symbol scores + portfolio weights to
an *intent* per holding, plus a light watchlist scan. Pure functions — no I/O.

Rules are first-match-wins per holding. Thresholds come from config."""
from __future__ import annotations

from quant.models import Holding, MarketState, Recommendation, Signal

WEAK_REGIMES = {"Correction", "Panic"}
CALM_REGIMES = {"Bull", "Neutral"}
# States a watchlist name may be entered from (strong stack or a healthy dip).
ENTRY_STATES = {"Trend Acceleration", "Trend Mature", "Mean Reversion"}


def staged_gap(
    current_weight: float,
    cap_weight: float,
    target_weight: float,
    total_value: float,
    cfg: dict,
) -> float:
    """One scale-in step in dollars: add at most `target/max_steps` of weight,
    capped at the room remaining up to `cap_weight`. Lets a position build over a
    few weekly adds instead of filling in one shot."""
    max_steps = cfg.get("lifecycle", {}).get("max_steps", 3)
    step = target_weight / max_steps if max_steps > 0 else target_weight
    add_w = max(0.0, min(cap_weight - current_weight, step))
    return add_w * total_value


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
        "rs": round(sig.rs, 3),
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
        step = staged_gap(current_weight, target_weight, target_weight, total_value, cfg)
        return Recommendation(
            intent="Add Core",
            reason="Panic pullback but price holds above MA200 — accumulate quality "
            f"(~${step:,.0f} this step).",
            dollar_gap=step,
            **base,
        )

    # 3. Strong and accelerating with room below its (raised) ceiling => add to
    #    strength. This is the momentum / pyramiding path — buy winners one step at a
    #    time, capped by the state-aware ceiling so it can't run away.
    ceiling = effective_ceiling(sig.state, target_weight, cfg)
    if (
        sig.state == "Trend Acceleration"
        and target_weight > 0
        and current_weight < ceiling
        and not cash_low
    ):
        step = staged_gap(current_weight, ceiling, target_weight, total_value, cfg)
        return Recommendation(
            intent="Add Core",
            reason=f"Trend Acceleration — pyramiding toward {ceiling:.0%} ceiling "
            f"(~${step:,.0f} this step).",
            dollar_gap=step,
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

    # 5. Underweight + healthy pullback + room to buy => add to core (one step).
    if (
        target_weight > 0
        and current_weight < target_weight * (1 - drift)
        and sig.pullback
        and not cash_low
        and market.regime != "Panic"
    ):
        step = staged_gap(current_weight, target_weight, target_weight, total_value, cfg)
        return Recommendation(
            intent="Add Core",
            reason=f"Underweight + pullback to MA50 — add ~${step:,.0f} (step toward target).",
            dollar_gap=step,
            **base,
        )

    # 6. At/above target and extended => sell premium for income.
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

    # 7. Default.
    return Recommendation(intent="Hold", reason="No rule triggered.", **base)


def _entry_candidates(signals, held, cfg):
    """Unheld names eligible to open, ranked by relative strength (strongest first)."""
    entry_min = cfg.get("lifecycle", {}).get("entry_trend_min", 75)
    cands = [
        s
        for sym, s in signals.items()
        if sym not in held and s.state in ENTRY_STATES and s.trend_score >= entry_min
    ]
    cands.sort(key=lambda s: s.rs, reverse=True)
    return cands


def scan_watchlist(
    signals: dict[str, Signal],
    held: set[str],
    market: MarketState,
    cfg: dict,
    open_slots: int,
    total_value: float,
) -> list[Recommendation]:
    """Rank unheld candidates by relative strength and surface up to `open_slots` to
    open. Entries need a constructive regime (skip Panic/Correction), an entry-grade
    state, and a trend score clearing the bar. Each entry is a first scale-in step."""
    if open_slots <= 0 or market.regime in WEAK_REGIMES:
        return []
    out = []
    for s in _entry_candidates(signals, held, cfg)[:open_slots]:
        target = effective_target(s.symbol, cfg)
        step = staged_gap(0.0, target, target, total_value, cfg)
        out.append(
            Recommendation(
                symbol=s.symbol,
                intent="Increase Exposure",
                reason=f"Watchlist entry — {s.state}, RS {s.rs:+.1%} "
                f"(open ~${step:,.0f}, step 1 toward {target:.0%}).",
                scores=_scores(s),
                dollar_gap=step,
            )
        )
    return out


def rotation(
    signals: dict[str, Signal],
    held: set[str],
    weights: dict[str, float],
    market: MarketState,
    cfg: dict,
    total_value: float,
    cash_low: bool,
) -> list[Recommendation]:
    """When cash is at the floor, free capital by rotating out the weakest laggard to
    fund the strongest fresh candidate. Graduated: fully Close a deeply weak laggard,
    else Trim it one step. Never sells a Trend Acceleration winner. At most one
    rotation per call. Returns [exit_action, entry] so the exit frees cash first."""
    if not cash_low or market.regime in WEAK_REGIMES:
        return []
    cands = _entry_candidates(signals, held, cfg)
    laggards = [
        signals[sym]
        for sym in held
        if sym in signals and signals[sym].state != "Trend Acceleration"
    ]
    if not cands or not laggards:
        return []
    best = cands[0]  # already ranked by RS, strongest first
    worst = min(laggards, key=lambda s: s.rs)
    margin = cfg.get("lifecycle", {}).get("rotation_margin", 0.10)
    if best.rs - worst.rs <= margin:
        return []

    if worst.state in {"Range", "Broken"} or worst.rs < 0:
        exit_action = Recommendation(
            symbol=worst.symbol,
            intent="Close",
            reason=f"Rotate out — weakest holding (RS {worst.rs:+.1%}, {worst.state}); "
            f"free capital for {best.symbol} (RS {best.rs:+.1%}).",
            scores=_scores(worst),
            dollar_gap=-weights.get(worst.symbol, 0.0) * total_value,
        )
    else:
        wt = effective_target(worst.symbol, cfg)
        step = staged_gap(0.0, wt, wt, total_value, cfg)
        exit_action = Recommendation(
            symbol=worst.symbol,
            intent="Trim",
            reason=f"Rotate — trim laggard (RS {worst.rs:+.1%}) one step to fund "
            f"{best.symbol} (RS {best.rs:+.1%}).",
            scores=_scores(worst),
            dollar_gap=-step,
        )

    bt = effective_target(best.symbol, cfg)
    entry = Recommendation(
        symbol=best.symbol,
        intent="Increase Exposure",
        reason=f"Rotate in — strongest candidate (RS {best.rs:+.1%}), funded by "
        f"{worst.symbol}.",
        scores=_scores(best),
        dollar_gap=staged_gap(0.0, bt, bt, total_value, cfg),
    )
    return [exit_action, entry]


def attach_strategy_hints(recs: list[Recommendation], intent_map: dict) -> None:
    for r in recs:
        r.strategy_hint = intent_map.get(r.intent, [])
