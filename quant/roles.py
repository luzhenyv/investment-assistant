"""Horizon role per symbol: long-term **core**, mid-term **swing**, or short-term
**momentum** — each with its own take-profit / stop-loss discipline and option playbook.

The role in force is hand-set in config (`roles:`); when a symbol isn't listed, the engine
falls back to a *suggested* role from trend + relative strength + valuation. The whole point
(the user's framing) is to decide the trade's nature BEFORE entry, so you don't "buy with
long-term logic and sell with short-term emotion". Report-only — never feeds scoring/decision."""
from __future__ import annotations

from quant.models import Fundamentals, RoleView, Signal

ROLES = ("core", "swing", "momentum", "avoid")


def suggest_role(sig: Signal, fund: Fundamentals | None, cfg: dict) -> str:
    """Transparent first-match suggestion from the data we already have.

    core     = strong trend AND reasonable valuation -> own the compounder
    momentum = strong trend BUT rich/unknown valuation -> chasing the last leg, quick exit
    swing    = quality on a pullback (mean reversion) -> buy the dip, ride the recovery
    avoid    = broken trend
    """
    rr = cfg.get("role_rules", {})
    core_trend_min = rr.get("core_trend_min", 75)
    val = (fund.valuation_label if fund else "unknown") or "unknown"
    rich = val.startswith("rich")
    reasonable = val.startswith("cheap") or val.startswith("fair")

    if sig.state == "Broken":
        return "avoid"
    if sig.state == "Mean Reversion":
        return "swing"
    strong = sig.trend_score >= core_trend_min
    if strong and reasonable:
        return "core"
    if strong:  # rich or unknown valuation
        return "momentum"
    return "swing"


def role_plan(role: str, price: float, cfg: dict) -> dict:
    """Resolve a role to its horizon, TP/SL (pct + price), and option playbook from
    `role_rules` config. Core has no fixed TP/SL (trim on thesis break, add on dips)."""
    rules = cfg.get("role_rules", {}).get(role, {})
    tp = rules.get("take_profit")
    sl = rules.get("stop_loss")
    return {
        "horizon": rules.get("horizon", "—"),
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
        "tp_price": price * (1 + tp) if tp is not None else None,
        "sl_price": price * (1 - sl) if sl is not None else None,
        "playbook": list(rules.get("playbook", [])),
    }


def build(symbol: str, sig: Signal, fund: Fundamentals | None, cfg: dict) -> RoleView:
    """Assemble the RoleView: config role wins; otherwise the suggestion. Flags a mismatch
    so the user can sanity-check a hand-set role against what the data implies."""
    suggested = suggest_role(sig, fund, cfg)
    configured = (cfg.get("roles", {}) or {}).get(symbol)
    role = configured if configured in ROLES else suggested
    source = "config" if configured in ROLES else "suggested"
    agree = role == suggested
    plan = role_plan(role, sig.price, cfg)

    if source == "config" and not agree:
        note = f"hand-set {role}, but data suggests {suggested} — confirm the thesis still fits"
    elif role == "avoid":
        note = "trend broken — no new buys; close per the decision engine"
    elif role == "momentum":
        note = "chasing strength — define the exit before you enter; don't let it become a bag"
    elif role == "swing":
        note = "quality on a dip — ride the recovery to target, don't marry it"
    else:
        note = "compounder — add on dips while the thesis holds; trim only on break/extreme"

    return RoleView(
        symbol=symbol, role=role, suggested_role=suggested, source=source, agree=agree,
        horizon=plan["horizon"], take_profit_pct=plan["take_profit_pct"],
        stop_loss_pct=plan["stop_loss_pct"], tp_price=plan["tp_price"],
        sl_price=plan["sl_price"], playbook=plan["playbook"], note=note,
    )
