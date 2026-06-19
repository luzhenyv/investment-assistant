"""Load recorded option strategies and derive underlying-based metrics.

No option-price feed: every metric (DTE, moneyness, breakeven, intrinsic value,
P&L, assignment risk) is computed from the strikes + the live underlying price.
The P&L reported is therefore an *intrinsic-only floor* — it ignores remaining
time value, so a real mark is at least this good. Pure given inputs."""
from __future__ import annotations

import math
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


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_greeks(S: float, K: float, T: float, r: float, sigma: float, right: str) -> dict | None:
    """Per-share Black-Scholes Greeks (dividend yield q=0). vega per 1.00 vol,
    theta per year, rho per 1.00 rate — normalized at aggregation. None if degenerate."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _norm_pdf(d1) * math.sqrt(T)
    if right == "call":
        delta = _norm_cdf(d1)
        theta = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * disc * _norm_cdf(d2)
        rho = K * T * disc * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * disc * _norm_cdf(-d2)
        rho = -K * T * disc * _norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def _net_greeks(
    strat: OptionStrategy, S: float, today: date, ivs: dict, r: float
) -> dict | None:
    """Sum signed, position-scaled (×100×contracts) Greeks across legs. Returns None if
    any leg lacks a usable IV (implied-only — no realized fallback)."""
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    for leg in strat.legs:
        if leg.expiry is None:
            return None
        sigma = ivs.get((leg.right, float(leg.strike), leg.expiry.isoformat()))
        if sigma is None:
            return None
        T = (leg.expiry - today).days / 365.0
        g = _bs_greeks(S, leg.strike, T, r, sigma, leg.right)
        if g is None:
            return None
        sign = 1.0 if leg.action == "long" else -1.0
        scale = sign * 100 * leg.contracts
        for k in net:
            net[k] += scale * g[k]
    return {
        "net_delta": round(net["delta"], 1),       # share-equivalents
        "net_gamma": round(net["gamma"], 3),        # Δ-shares per $1 move
        "net_vega": round(net["vega"] / 100, 2),    # $ per 1 vol point
        "net_theta": round(net["theta"] / 365, 2),  # $ per calendar day
        "net_rho": round(net["rho"] / 100, 2),      # $ per 1% rate
    }


def analyze(
    strat: OptionStrategy,
    underlying_price: float,
    today: date,
    ivs: dict | None = None,
    r: float = 0.04,
) -> OptionAnalysis:
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
    greeks = _net_greeks(strat, underlying_price, today, ivs or {}, r)
    return OptionAnalysis(
        id=strat.id,
        underlying=strat.underlying,
        type=strat.type,
        intent=intent,
        reason=reason,
        metrics=metrics,
        greeks=greeks,
    )
