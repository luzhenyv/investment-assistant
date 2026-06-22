"""Option-chain positioning: where dealers will be forced to hedge (walls / max pain),
how far the market is pricing a move (expected move), the fear tilt (IV skew), and the
risk/reward odds of a long entry — cross-referenced with the price-structure zones from
quant/levels.py. Report-only hints; never feeds scoring/decision.

Metric functions are pure over a grid dict (testable offline). `analyze` is the orchestrator
that fetches the chain (free yfinance) + computes the zones. Free-data caveats: EOD OI lags
~1 trading day, there is no trade-direction (buy vs sell) signal, and there are no historical
chains — so this can't be backtested. Walls/max-pain are tendencies, not levels."""
from __future__ import annotations

import datetime as dt

from quant import levels, providers
from quant.models import OptionPositioning, Zone


def _band(spot: float, cfg: dict) -> tuple[float, float]:
    """Actionable strike band around spot — option OI concentrates much nearer spot than
    multi-year price structure, so this is tighter than levels.py's range."""
    op = cfg.get("option_positioning", {})
    return spot * op.get("band_floor", 0.70), spot * op.get("band_high", 1.30)


def _in_band(strikes, lo: float, hi: float):
    return [k for k in strikes if lo <= k <= hi]


def _max_oi_strike(side: dict, candidates) -> float | None:
    best, best_oi = None, 0.0
    for k in candidates:
        oi = side.get(k, {}).get("oi", 0.0)
        if oi > best_oi:
            best, best_oi = k, oi
    return best


def put_wall(grid: dict, spot: float, cfg: dict) -> float | None:
    """Strike with the most put OI at/below spot within the band — potential support."""
    lo, hi = _band(spot, cfg)
    puts = grid["puts"]
    cands = [k for k in _in_band(puts, lo, hi) if k <= spot * 1.02]
    return _max_oi_strike(puts, cands)


def call_wall(grid: dict, spot: float, cfg: dict) -> float | None:
    """Strike with the most call OI at/above spot within the band — potential resistance."""
    lo, hi = _band(spot, cfg)
    calls = grid["calls"]
    cands = [k for k in _in_band(calls, lo, hi) if k >= spot * 0.98]
    return _max_oi_strike(calls, cands)


def max_pain(grid: dict, spot: float, cfg: dict) -> float | None:
    """Strike (within band) minimising total cash paid out to option holders at expiry —
    the classic 'magnet'. A tendency, ranked low by pros; included as a coarse read."""
    lo, hi = _band(spot, cfg)
    strikes = sorted(set(_in_band(grid["calls"], lo, hi)) | set(_in_band(grid["puts"], lo, hi)))
    if not strikes:
        return None
    best, best_pay = None, None
    for s in strikes:
        pay = sum(d["oi"] * max(0.0, s - k) for k, d in grid["calls"].items())
        pay += sum(d["oi"] * max(0.0, k - s) for k, d in grid["puts"].items())
        if best_pay is None or pay < best_pay:
            best, best_pay = s, pay
    return best


def _nearest_strike(side: dict, target: float, *, need_iv: bool = False) -> float | None:
    pool = [k for k in side if (side[k]["iv"] is not None)] if need_iv else list(side)
    return min(pool, key=lambda k: abs(k - target)) if pool else None


def expected_move(grid: dict, spot: float) -> tuple[float | None, float | None]:
    """ATM straddle (ATM call price + ATM put price) → expected move ($, %)."""
    ck = _nearest_strike(grid["calls"], spot)
    pk = _nearest_strike(grid["puts"], spot)
    if ck is None or pk is None:
        return None, None
    cp, pp = grid["calls"][ck]["price"], grid["puts"][pk]["price"]
    if not cp or not pp:
        return None, None
    em = cp + pp
    return em, (em / spot if spot else None)


def atm_iv(grid: dict, spot: float) -> float | None:
    ck = _nearest_strike(grid["calls"], spot, need_iv=True)
    pk = _nearest_strike(grid["puts"], spot, need_iv=True)
    ivs = [grid[s][k]["iv"] for s, k in (("calls", ck), ("puts", pk)) if k is not None]
    return sum(ivs) / len(ivs) if ivs else None


def iv_skew(grid: dict, spot: float, cfg: dict) -> float | None:
    """OTM-put IV minus OTM-call IV (at ±skew_pct from spot). Positive = downside fear —
    the free proxy for the dangerous short-gamma regime where dips can air-pocket."""
    pct = cfg.get("option_positioning", {}).get("skew_pct", 0.10)
    pk = _nearest_strike(grid["puts"], spot * (1 - pct), need_iv=True)
    ck = _nearest_strike(grid["calls"], spot * (1 + pct), need_iv=True)
    if pk is None or ck is None:
        return None
    return grid["puts"][pk]["iv"] - grid["calls"][ck]["iv"]


def _sum_oi(side: dict) -> float:
    return sum(d.get("oi", 0.0) for d in side.values())


def _sum_vol(side: dict) -> float:
    return sum(d.get("vol", 0.0) for d in side.values())


def pc_oi(grid: dict) -> float | None:
    c = _sum_oi(grid["calls"])
    return _sum_oi(grid["puts"]) / c if c else None


def pc_vol(grid: dict) -> float | None:
    c = _sum_vol(grid["calls"])
    return _sum_vol(grid["puts"]) / c if c else None


def reward_risk(spot: float, cw: float | None, pw: float | None):
    """Upside to the call wall vs downside to the put wall — the entry 'odds' (赔率)."""
    reward = (cw - spot) / spot if (cw is not None and spot) else None
    risk = (spot - pw) / spot if (pw is not None and spot) else None
    ratio = reward / risk if (reward is not None and risk and risk > 0) else None
    return reward, risk, ratio


def _zone_at(price: float | None, zones: list[Zone], kind: str) -> Zone | None:
    if price is None:
        return None
    for z in zones:
        if z.kind == kind and z.low <= price <= z.high:
            return z
    return None


def _build_notes(spot, pw, cw, mp, em_low, em_high, rr, skew, zones, cfg) -> list[str]:
    notes: list[str] = []
    # Confluence: a wall that lands inside a same-side structural zone is a stronger level.
    sz = _zone_at(pw, zones, "support")
    if pw is not None:
        notes.append(
            f"put wall ${pw:,.0f} ⟂ {sz.label} support zone ${sz.low:,.0f}-${sz.high:,.0f} — confluence"
            if sz else f"put wall ${pw:,.0f} — no structural support zone there (weaker)"
        )
    rz = _zone_at(cw, zones, "resistance")
    if cw is not None and rz:
        notes.append(f"call wall ${cw:,.0f} ⟂ {rz.label} resistance ${rz.low:,.0f}-${rz.high:,.0f} — confluence")
    if em_low is not None:
        notes.append(f"expected move ${em_low:,.0f}-${em_high:,.0f} — a pullback inside this is normal")
    if rr is not None:
        verdict = "favourable" if rr >= cfg.get("option_positioning", {}).get("rr_good", 2.0) else "thin"
        notes.append(f"reward:risk {rr:.1f}:1 ({verdict}) — upside to call wall vs downside to put wall")
    if skew is not None and skew > cfg.get("option_positioning", {}).get("skew_warn", 0.05):
        notes.append(f"elevated put skew (+{skew:.0%}) — downside fear bid; dips may not be cushioned")
    return notes


def analyze(symbol: str, spot: float, df, cfg: dict) -> OptionPositioning | None:
    """Fetch the nearest-monthly chain, compute positioning + odds, and cross-reference with
    levels.detect_zones. Returns None when no chain is available."""
    op = cfg.get("option_positioning", {})
    expiry = providers.pick_monthly_expiry(symbol, op.get("dte_lo", 25), op.get("dte_hi", 45))
    if expiry is None:
        return None
    grid = providers.fetch_chain_grid(symbol, expiry)
    if grid is None:
        return None

    dte = max(0, (dt.date.fromisoformat(expiry) - dt.date.today()).days)
    pw, cw, mp = put_wall(grid, spot, cfg), call_wall(grid, spot, cfg), max_pain(grid, spot, cfg)
    em, em_pct = expected_move(grid, spot)
    em_low = spot - em if em is not None else None
    em_high = spot + em if em is not None else None
    skew = iv_skew(grid, spot, cfg)
    reward, risk, rr = reward_risk(spot, cw, pw)
    zones = levels.detect_zones(df, cfg, current_price=spot)
    notes = _build_notes(spot, pw, cw, mp, em_low, em_high, rr, skew, zones, cfg)

    return OptionPositioning(
        symbol=symbol, spot=spot, expiry=expiry, dte=dte,
        put_wall=pw, call_wall=cw, max_pain=mp,
        em=em, em_pct=em_pct, em_low=em_low, em_high=em_high,
        pc_oi=pc_oi(grid), pc_vol=pc_vol(grid),
        atm_iv=atm_iv(grid, spot), iv_skew=skew,
        reward=reward, risk=risk, rr_ratio=rr, notes=notes,
    )
