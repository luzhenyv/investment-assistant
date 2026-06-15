"""Pure technical-indicator functions. Each takes a Polars price column/Series and
returns a scalar (the latest value). No I/O, no global state.

Latest-value semantics let the same functions serve the live weekly run and the
backtester: the backtester slices a frame up to week T, then calls these — the
"latest" value is then the value as-of T."""
from __future__ import annotations

import polars as pl


def moving_average(close: pl.Series, window: int) -> float:
    return float(close.tail(window).mean())


def rsi(close: pl.Series, period: int = 14) -> float:
    diff = close.diff()
    avg_gain = diff.clip(lower_bound=0).tail(period).mean()
    avg_loss = (-diff).clip(lower_bound=0).tail(period).mean()
    # Only gains over the window -> RSI is 100.
    if not avg_loss:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def atr(high: pl.Series, low: pl.Series, close: pl.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    true_range = pl.DataFrame(
        [
            (high - low).rename("hl"),
            (high - prev_close).abs().rename("hc"),
            (low - prev_close).abs().rename("lc"),
        ]
    ).max_horizontal()
    return float(true_range.tail(period).mean())


def high_52w(high: pl.Series) -> float:
    return float(high.tail(252).max())


def low_52w(low: pl.Series) -> float:
    return float(low.tail(252).min())
