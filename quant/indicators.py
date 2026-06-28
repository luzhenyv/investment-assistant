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
    """Wilder's RSI (SMMA smoothing, alpha=1/period) — the industry-standard definition
    used by stockstats / TA-Lib / TradingView. Gains and losses are exponentially smoothed
    rather than simple-averaged, so the result carries memory of the whole series and matches
    the number charting tools report (an SMA of the last `period` changes drifts ~5 pts in a trend)."""
    diff = close.diff()
    gain = diff.clip(lower_bound=0)
    loss = (-diff).clip(lower_bound=0)
    avg_gain = gain.ewm_mean(alpha=1 / period, adjust=False, ignore_nulls=True).tail(1).item()
    avg_loss = loss.ewm_mean(alpha=1 / period, adjust=False, ignore_nulls=True).tail(1).item()
    # Only gains over the window -> RSI is 100.
    if not avg_loss:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def _macd_line(close: pl.Series, fast: int, slow: int) -> pl.Series:
    """MACD line series: fast EMA - slow EMA (standard EMA, alpha=2/(n+1))."""
    ema_fast = close.ewm_mean(span=fast, adjust=False)
    ema_slow = close.ewm_mean(span=slow, adjust=False)
    return ema_fast - ema_slow


def macd(
    close: pl.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float]:
    """Latest (macd_line, signal_line, histogram). Momentum via the gap between a fast and
    slow EMA; histogram = line - signal is the acceleration read (positive & rising = momentum
    building). Distinct from RSI: unbounded and trend-relative, not an overbought/oversold band."""
    line = _macd_line(close, fast, slow)
    signal_line = line.ewm_mean(span=signal, adjust=False)
    hist = line - signal_line
    return (
        float(line.tail(1).item()),
        float(signal_line.tail(1).item()),
        float(hist.tail(1).item()),
    )


def bollinger(
    close: pl.Series, window: int = 20, k: float = 2.0,
    squeeze_lookback: int = 120, squeeze_q: float = 0.15,
) -> tuple[float, float, bool]:
    """Latest (bandwidth, pct_b, is_squeeze) for a `window`-SMA ± `k`·σ Bollinger band.

    bandwidth = (upper-lower)/mid = 2k·σ/mid — a volatility-normalized width; pct_b =
    (price-lower)/(upper-lower) — where price sits in the band (>1 above upper, <0 below lower).
    is_squeeze: bandwidth sits in the bottom `squeeze_q` of its last `squeeze_lookback` bars —
    coiling volatility that often precedes a breakout (the one concept ATR/levels.py don't capture)."""
    mid = close.rolling_mean(window)
    sd = close.rolling_std(window)
    band = 2 * k * sd
    bandwidth = band / mid
    pct_b = (close - (mid - k * sd)) / band
    bw = float(bandwidth.tail(1).item())
    recent = bandwidth.tail(squeeze_lookback).drop_nulls()
    is_squeeze = bool(recent.len() and bw <= recent.quantile(squeeze_q))
    return bw, float(pct_b.tail(1).item()), is_squeeze


def _swing_pivots(values: list[float], roll: list[float | None], min_gap: int) -> list[int]:
    """Bar indices where a value equals its centered rolling extreme (a confirmed fractal pivot).
    Consecutive/flat extremes (a flat double-bottom) collapse to one pivot per `min_gap` bars so a
    swing is never compared against itself."""
    out: list[int] = []
    for i, (v, r) in enumerate(zip(values, roll)):
        if r is not None and v == r and (not out or i - out[-1] >= min_gap):
            out.append(i)
    return out


def macd_divergence(
    close: pl.Series, high: pl.Series, low: pl.Series,
    fast: int = 12, slow: int = 26, signal: int = 9, k: int = 5, lookback: int = 120,
) -> str:
    """Classify MACD-line divergence vs price over the last `lookback` bars: "bullish" |
    "bearish" | "none".

    Swing pivots are the same centered 2k+1 fractal levels.py uses, so a pivot is only confirmed
    k bars after it prints — no look-ahead in a backtest slice. Bullish: the last two swing LOWS
    make a lower price low but a higher MACD-line low (selling exhausting). Bearish: the last two
    swing HIGHS make a higher price high but a lower MACD-line high (buying exhausting)."""
    win = 2 * k + 1
    if close.len() < win:
        return "none"
    line = _macd_line(close, fast, slow).to_list()
    hi, lo = high.to_list(), low.to_list()
    lo_roll = low.rolling_min(win, center=True).to_list()
    hi_roll = high.rolling_max(win, center=True).to_list()
    n = close.len()
    floor = n - lookback

    lows = [i for i in _swing_pivots(lo, lo_roll, k) if i >= floor and line[i] is not None]
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if lo[b] < lo[a] and line[b] > line[a]:
            return "bullish"

    highs = [i for i in _swing_pivots(hi, hi_roll, k) if i >= floor and line[i] is not None]
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if hi[b] > hi[a] and line[b] < line[a]:
            return "bearish"

    return "none"


def atr(high: pl.Series, low: pl.Series, close: pl.Series, period: int = 14) -> float:
    """Wilder's ATR (SMMA smoothing, alpha=1/period) — the TA-Lib / stockstats / TradingView
    standard, and the same smoothing rsi() uses. True Range is the max of (H-L), |H-prevC|,
    |L-prevC|; the leading shift(1) null collapses to H-L on the first bar."""
    prev_close = close.shift(1)
    true_range = pl.DataFrame(
        [
            (high - low).rename("hl"),
            (high - prev_close).abs().rename("hc"),
            (low - prev_close).abs().rename("lc"),
        ]
    ).max_horizontal()
    return float(
        true_range.ewm_mean(alpha=1 / period, adjust=False, ignore_nulls=True).tail(1).item()
    )


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
