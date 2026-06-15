"""Pure technical-indicator functions. Each takes a price DataFrame/Series and
returns a scalar (the latest value). No I/O, no global state."""
from __future__ import annotations

import pandas as pd


def moving_average(close: pd.Series, window: int) -> float:
    return float(close.rolling(window).mean().iloc[-1])


def rsi(close: pd.Series, period: int = 14) -> float:
    diff = close.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    value = 100 - 100 / (1 + rs)
    # When avg_loss is 0 (only gains), RSI is 100.
    return float(value.fillna(100).iloc[-1])


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return float(true_range.rolling(period).mean().iloc[-1])


def high_52w(high: pd.Series) -> float:
    return float(high.tail(252).max())


def low_52w(low: pd.Series) -> float:
    return float(low.tail(252).min())
