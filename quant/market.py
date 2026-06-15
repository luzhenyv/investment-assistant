"""Derive overall market regime from index trends + VIX. Pure function."""
from __future__ import annotations

from quant.models import MarketState, Signal


def _vix_adjustment(vix: float) -> tuple[float, str]:
    if vix < 15:
        return 10.0, f"VIX low ({vix:.1f}) — calm"
    if vix < 20:
        return 0.0, f"VIX normal ({vix:.1f})"
    if vix < 30:
        return -10.0, f"VIX elevated ({vix:.1f})"
    return -25.0, f"VIX high ({vix:.1f}) — fear"


def _regime(bull_score: float) -> str:
    if bull_score < 20:
        return "Panic"
    if bull_score < 40:
        return "Correction"
    if bull_score < 60:
        return "Neutral"
    if bull_score < 80:
        return "Bull"
    return "Strong Bull"


def detect_market(spy: Signal, qqq: Signal, vix: float) -> MarketState:
    base = (spy.trend_score + qqq.trend_score) / 2
    adj, vix_note = _vix_adjustment(vix)
    bull_score = max(0.0, min(100.0, base + adj))
    notes = [
        f"SPY trend {spy.trend_score:.0f}, QQQ trend {qqq.trend_score:.0f}",
        vix_note,
    ]
    return MarketState(regime=_regime(bull_score), bull_score=bull_score, notes=notes)
