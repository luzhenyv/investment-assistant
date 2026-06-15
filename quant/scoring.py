"""Turn raw indicators into 0-100 scores and boolean flags. Pure functions."""
from __future__ import annotations

import polars as pl

from quant import indicators
from quant.models import Signal


def trend_score(price: float, ma20: float, ma50: float, ma200: float) -> float:
    """25 points for each bullish stack condition -> 0..100."""
    score = 0
    if price > ma20:
        score += 25
    if ma20 > ma50:
        score += 25
    if ma50 > ma200:
        score += 25
    if price > ma200:
        score += 25
    return float(score)


def momentum_score(rsi: float) -> float:
    if rsi > 70:
        return 80.0
    if rsi > 50:
        return 60.0
    if rsi > 40:
        return 40.0
    return 20.0


def is_pullback(price: float, ma50: float, atr: float, atr_mult: float) -> bool:
    """Price near MA50 from above (uptrend dip), within atr_mult ATRs."""
    return ma50 <= price <= ma50 + atr_mult * atr


def is_breakout(price: float, high_52w: float) -> bool:
    """Price at/above the trailing 52-week high."""
    return price >= high_52w


def build_signal(symbol: str, df: pl.DataFrame, cfg: dict) -> Signal:
    """Assemble a full Signal from an OHLC DataFrame using indicators + scores.

    `df` is a Polars frame sorted by date with Open/High/Low/Close columns; the
    indicators read the latest (last-row) value, so slicing `df` to week T turns
    this into an as-of-T snapshot for the backtester."""
    close, high, low = df["Close"], df["High"], df["Low"]
    price = float(close.tail(1).item())
    ma20 = indicators.moving_average(close, 20)
    ma50 = indicators.moving_average(close, 50)
    ma200 = indicators.moving_average(close, 200)
    rsi_val = indicators.rsi(close)
    atr_val = indicators.atr(high, low, close)
    hi = indicators.high_52w(high)
    lo = indicators.low_52w(low)
    atr_mult = cfg["scoring"]["pullback_atr_mult"]
    return Signal(
        symbol=symbol,
        price=price,
        ma20=ma20,
        ma50=ma50,
        ma200=ma200,
        rsi=rsi_val,
        atr=atr_val,
        high_52w=hi,
        low_52w=lo,
        trend_score=trend_score(price, ma20, ma50, ma200),
        momentum_score=momentum_score(rsi_val),
        pullback=is_pullback(price, ma50, atr_val, atr_mult),
        breakout=is_breakout(price, hi),
    )
