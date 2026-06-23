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


def trailing_return(close: pl.Series, lookback: int) -> float:
    """Relative strength: total return over the last `lookback` bars. Returns 0.0
    when history is shorter than lookback+1 (young tickers rank low, not crash)."""
    if close.len() < lookback + 1:
        return 0.0
    past = float(close.tail(lookback + 1).head(1).item())
    if not past:
        return 0.0
    return float(close.tail(1).item()) / past - 1.0


def correlation(df_a: pl.DataFrame, df_b: pl.DataFrame, lookback: int) -> float:
    """Pearson correlation of two symbols' daily returns over the trailing `lookback`
    overlapping bars. Joins on date so frames with different start dates align; returns
    0.0 when the overlap is too short to trust (young tickers count as uncorrelated,
    not maximally diversifying) or either series is flat over the window."""
    joined = (
        df_a.select(["date", "Close"])
        .join(df_b.select(["date", "Close"]), on="date", how="inner", suffix="_b")
        .sort("date")
        .tail(lookback + 1)
    )
    if joined.height < 21:  # need ~a month of overlap before a correlation means anything
        return 0.0
    rets = joined.select(
        pl.col("Close").pct_change().alias("a"),
        pl.col("Close_b").pct_change().alias("b"),
    ).drop_nulls()
    if rets.height < 2:
        return 0.0
    c = rets.select(pl.corr("a", "b")).item()
    return float(c) if c is not None else 0.0


def rvol(volume: pl.Series, lookback: int = 20) -> float:
    """Relative volume: today's volume / average of the prior `lookback` bars (today
    excluded, so a spike doesn't inflate its own baseline). 1.0 = average; >1.5 ≈ busy.
    Returns 1.0 (neutral) when history is too short or the baseline is zero/empty."""
    if volume.len() < lookback + 1:
        return 1.0
    today = float(volume.tail(1).item())
    base = float(volume.tail(lookback + 1).head(lookback).mean())
    if not base:
        return 1.0
    return today / base


def volume_zscore(volume: pl.Series, lookback: int = 20) -> float:
    """How many standard deviations today's volume sits above its recent norm, over the
    prior `lookback` bars (today excluded). The statistical 'abnormal' measure. Returns
    0.0 when history is too short or the window is flat (zero std)."""
    if volume.len() < lookback + 1:
        return 0.0
    prior = volume.tail(lookback + 1).head(lookback)
    mean = prior.mean()
    std = prior.std()
    if not std:
        return 0.0
    return (float(volume.tail(1).item()) - float(mean)) / float(std)


def high_52w(high: pl.Series) -> float:
    return float(high.tail(252).max())


def low_52w(low: pl.Series) -> float:
    return float(low.tail(252).min())
