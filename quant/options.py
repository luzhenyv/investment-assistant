"""Load recorded option strategies and derive underlying-based metrics.

No option-price feed: every metric (DTE, moneyness, breakeven, intrinsic value,
P&L, assignment risk) is computed from the strikes + the live underlying price.
The P&L reported is therefore an *intrinsic-only floor* — it ignores remaining
time value, so a real mark is at least this good. Pure given inputs."""
from __future__ import annotations

from datetime import date

import yaml

from quant.models import OptionAnalysis, OptionLeg, OptionStrategy


def _to_date(value) -> date | None:
    """YAML parses bare ISO dates to date already; tolerate strings too."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_options(path: str) -> list[OptionStrategy]:
    """Return the recorded strategies. Missing file or no `strategies` key → []."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    strategies = []
    for s in data.get("strategies") or []:
        legs = [
            OptionLeg(
                action=leg["action"],
                right=leg["right"],
                strike=float(leg["strike"]),
                expiry=_to_date(leg["expiry"]),
                contracts=int(leg.get("contracts", 1)),
                premium=(float(leg["premium"]) if leg.get("premium") is not None else None),
            )
            for leg in s.get("legs") or []
        ]
        strategies.append(
            OptionStrategy(
                id=s["id"],
                underlying=s["underlying"],
                type=s.get("type", ""),
                legs=legs,
                opened=_to_date(s.get("opened")),
                net_debit=(float(s["net_debit"]) if s.get("net_debit") is not None else None),
                credits_collected=float(s.get("credits_collected", 0) or 0),
                note=s.get("note", "") or "",
            )
        )
    return strategies


def _net_debit(strat: OptionStrategy) -> float:
    """Per-share cost basis (+ paid / - received). Use the recorded value if given,
    else sum(long premiums) − sum(short premiums) − credits already harvested."""
    if strat.net_debit is not None:
        return strat.net_debit
    paid = sum(l.premium or 0.0 for l in strat.legs if l.action == "long")
    received = sum(l.premium or 0.0 for l in strat.legs if l.action == "short")
    return paid - received - strat.credits_collected


def _leg_intrinsic(leg: OptionLeg, price: float) -> float:
    """Per-share intrinsic value of one leg, signed +long / −short."""
    if leg.right == "call":
        value = max(0.0, price - leg.strike)
    else:
        value = max(0.0, leg.strike - price)
    return value if leg.action == "long" else -value


def analyze(strat: OptionStrategy, underlying_price: float, today: date) -> OptionAnalysis:
    net_debit = _net_debit(strat)
    contracts = max((l.contracts for l in strat.legs), default=1)
    mult = 100 * contracts

    net_intrinsic = sum(_leg_intrinsic(l, underlying_price) for l in strat.legs)
    pnl_floor = (net_intrinsic - net_debit) * mult

    longs = [l for l in strat.legs if l.action == "long"]
    shorts = [l for l in strat.legs if l.action == "short"]
    long_strike = min((l.strike for l in longs), default=None)
    short_call = next((l for l in shorts if l.right == "call"), None)

    # Spread-width model: max loss = debit; max profit = strike width − debit (when a
    # short call caps the upside). Approximate for a PMCC — ignores LEAPS time value.
    max_loss = net_debit * mult if net_debit > 0 else None
    max_profit = None
    if short_call is not None and long_strike is not None:
        max_profit = (short_call.strike - long_strike - net_debit) * mult
    breakeven = (long_strike + net_debit) if long_strike is not None else None

    short_dte = min(((l.expiry - today).days for l in shorts if l.expiry), default=None)
    nearest_dte = min(((l.expiry - today).days for l in strat.legs if l.expiry), default=None)
    assignment_risk = short_call is not None and underlying_price > short_call.strike

    legs_desc = " / ".join(
        f"{l.action} ${l.strike:g} {l.right}" for l in strat.legs
    )

    # Action ladder — first match wins.
    if assignment_risk:
        intent = "Roll short call"
        reason = (
            f"Underlying ${underlying_price:,.2f} above short ${short_call.strike:g} "
            f"call ({short_dte}d left) — ITM, assignment risk. Roll up/out to keep the position."
        )
    elif nearest_dte is not None and nearest_dte <= 7:
        intent = "Expiring — close or roll"
        reason = f"Nearest leg expires in {nearest_dte}d — close or roll before expiry."
    elif max_profit and max_profit > 0 and pnl_floor >= 0.9 * max_profit:
        intent = "Close — near max profit"
        reason = (
            f"Intrinsic-floor P&L ${pnl_floor:,.0f} is near the ${max_profit:,.0f} cap — "
            f"little left to gain; consider closing."
        )
    else:
        intent = "Hold"
        reason = f"Underlying ${underlying_price:,.2f}; nothing to do this week."

    metrics = {
        "underlying_price": round(underlying_price, 2),
        "legs": legs_desc,
        "net_debit": round(net_debit, 2),
        "intrinsic_value": round(net_intrinsic, 2),
        "pnl_floor": round(pnl_floor, 0),
        "max_profit": (round(max_profit, 0) if max_profit is not None else None),
        "max_loss": (round(max_loss, 0) if max_loss is not None else None),
        "breakeven": (round(breakeven, 2) if breakeven is not None else None),
        "short_dte": short_dte,
        "nearest_dte": nearest_dte,
        "assignment_risk": assignment_risk,
    }
    return OptionAnalysis(
        id=strat.id,
        underlying=strat.underlying,
        type=strat.type,
        intent=intent,
        reason=reason,
        metrics=metrics,
    )
