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
    swing HIGHS make a higher price high but a lower MACD-line high (buying exhausting).

    A pattern is negated once price closes beyond the triggering pivot `b` (a later close above the
    swing high kills a bearish divergence; below the swing low kills a bullish one) — the market has
    resolved it, so we return "none" rather than a stale flag."""
    win = 2 * k + 1
    if close.len() < win:
        return "none"
    line = _macd_line(close, fast, slow).to_list()
    hi, lo, c = high.to_list(), low.to_list(), close.to_list()
    lo_roll = low.rolling_min(win, center=True).to_list()
    hi_roll = high.rolling_max(win, center=True).to_list()
    n = close.len()
    floor = n - lookback

    lows = [i for i in _swing_pivots(lo, lo_roll, k) if i >= floor and line[i] is not None]
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if lo[b] < lo[a] and line[b] > line[a] and min(c[b + 1:], default=lo[b]) >= lo[b]:
            return "bullish"

    highs = [i for i in _swing_pivots(hi, hi_roll, k) if i >= floor and line[i] is not None]
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if hi[b] > hi[a] and line[b] < line[a] and max(c[b + 1:], default=hi[b]) <= hi[b]:
            return "bearish"

    return "none"


def macd_cross(prev_hist: float | None, curr_hist: float) -> str:
    """MACD golden/death cross from the histogram (line - signal) sign flip between the prior bar
    and now: "golden" (histogram turned positive — the MACD line crossed ABOVE its signal line),
    "death" (turned negative — crossed below), or "none". `prev_hist` None (no prior bar / first
    run) → "none"."""
    if prev_hist is None:
        return "none"
    if prev_hist <= 0 < curr_hist:
        return "golden"
    if prev_hist >= 0 > curr_hist:
        return "death"
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


def return_zscore(close: pl.Series, lookback: int = 21) -> float:
    """Z-score of the latest daily return vs the prior `lookback` daily returns.

    Today's return is excluded from the baseline, so an abnormal move does not dilute its own
    reference distribution. Returns 0.0 when history is too short or the window is flat."""
    rets = close.pct_change().drop_nulls()
    if rets.len() < lookback + 1:
        return 0.0
    today = float(rets.tail(1).item())
    prior = rets.tail(lookback + 1).head(lookback)
    mean, std = prior.mean(), prior.std()
    if not std or abs(float(std)) < 1e-12:
        return 0.0
    return (today - float(mean)) / float(std)


def atr_move_multiple(close: pl.Series, atr_value: float) -> float:
    """Latest close-to-close move measured in ATRs, signed by direction.

    Returns 0.0 when history is too short or ATR is unavailable/zero."""
    if close.len() < 2 or not atr_value:
        return 0.0
    prev = float(close.tail(2).head(1).item())
    return (float(close.tail(1).item()) - prev) / atr_value


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


# --------------------------------------------------------------------------- #
# Extended indicator library — ported to Polars from `stockstats`
# (Cedric Zhuang, BSD-3-Clause): https://github.com/jealous/stockstats
#
# REPORT-ONLY: none of these are wired into scoring/decision, so the backtest is
# unchanged. They keep the same latest-value semantics as the functions above
# (return the as-of-T scalar, so a sliced backtest frame just works). Smoothing
# follows this module's Wilder convention (`adjust=False` — the exact recursive
# form, marginally tighter than stockstats' `adjust=True` on short series,
# identical on long history). Default windows mirror stockstats. Faithfulness
# caveats, called out per function: OBV is the standard textbook definition
# (stockstats has none); MFI is scaled 0-100 (the recognized scale) vs
# stockstats' 0-1 fraction; KAMA matches stockstats' smoothing, which omits the
# StockCharts squaring of the smoothing constant.
# --------------------------------------------------------------------------- #
def _wilder(expr: pl.Expr, period: int) -> pl.Expr:
    """Wilder SMMA (alpha=1/period) — the same recursion rsi()/atr() use."""
    return expr.ewm_mean(alpha=1.0 / period, adjust=False, ignore_nulls=True)


def _ema(expr: pl.Expr, span: int) -> pl.Expr:
    return expr.ewm_mean(span=span, adjust=False)


def _rsi_expr(col: pl.Expr, period: int) -> pl.Expr:
    """RSI as a full series-expression (the scalar rsi() above can't be windowed)."""
    d = col.diff()
    g = _wilder(d.clip(lower_bound=0), period)
    loss = _wilder((-d).clip(lower_bound=0), period)
    return pl.when(loss == 0).then(pl.lit(100.0)).otherwise(100 - 100 / (1 + g / loss))


def _tr_expr() -> pl.Expr:
    """True Range over columns h/l/c; first bar collapses to H-L (prevC is null)."""
    pc = pl.col("c").shift(1)
    return pl.max_horizontal(
        pl.col("h") - pl.col("l"), (pl.col("h") - pc).abs(), (pl.col("l") - pc).abs()
    )


def _latest(cols: dict[str, pl.Series], expr: pl.Expr) -> float | None:
    v = pl.DataFrame(cols).select(expr.alias("_v"))["_v"].tail(1).item()
    return None if v is None else float(v)


def kdj(
    high: pl.Series, low: pl.Series, close: pl.Series, window: int = 9, smooth: int = 3
) -> tuple[float, float, float]:
    """Latest (K, D, J) of the KDJ stochastic. RSV = position of close in the window's
    high-low range (×100); K = SMMA(RSV, 1/smooth) (i.e. 2/3·prevK + 1/3·RSV), D = SMMA(K),
    J = 3K − 2D. Overbought >80, oversold <20; J swings beyond 0-100 (early/exhausted moves)."""
    hh, ll = pl.col("h").rolling_max(window), pl.col("l").rolling_min(window)
    rng = hh - ll
    rsv = pl.when(rng != 0).then((pl.col("c") - ll) / rng * 100).otherwise(0.0)
    k_expr, d_expr = _wilder(rsv, smooth), _wilder(_wilder(rsv, smooth), smooth)
    df = pl.DataFrame({"h": high, "l": low, "c": close}).select(
        k_expr.alias("k"), d_expr.alias("d")
    )
    k, d = float(df["k"].tail(1).item()), float(df["d"].tail(1).item())
    return k, d, 3 * k - 2 * d


def stoch_rsi(close: pl.Series, window: int = 14) -> float:
    """Latest Stochastic RSI (×100): where RSI sits in its own `window`-bar range. More
    sensitive than RSI — designed to flag overbought/oversold faster (0-100)."""
    r = _rsi_expr(pl.col("c"), window)
    rng = r.rolling_max(window) - r.rolling_min(window)
    sr = pl.when(rng != 0).then((r - r.rolling_min(window)) / rng * 100).otherwise(0.0)
    return _latest({"c": close}, sr)


def cci(high: pl.Series, low: pl.Series, close: pl.Series, window: int = 14) -> float:
    """Latest Commodity Channel Index: (TP − SMA(TP)) / (0.015 · meanAbsDev(TP)), TP=(H+L+C)/3.
    >+100 strong up / overbought, <−100 strong down / oversold. The 0.015 scales ~70-80% into ±100."""
    tp = (high + low + close) / 3
    sma = tp.rolling_mean(window)
    # True mean-absolute-deviation: |TP − window_mean| averaged over the window (not a
    # rolling mean of |TP − rolling_mean|, which would use a different mean per bar).
    mad = tp.rolling_map(lambda s: (s - s.mean()).abs().mean(), window_size=window)
    tp_l, sma_l, mad_l = tp.tail(1).item(), sma.tail(1).item(), mad.tail(1).item()
    if not mad_l:
        return 0.0
    return float((tp_l - sma_l) / (0.015 * mad_l))


def williams_r(high: pl.Series, low: pl.Series, close: pl.Series, window: int = 14) -> float:
    """Latest Williams %R = (Hn − C)/(Hn − Ln) × −100. Range −100..0 (stockstats sign
    convention); near 0 = overbought, near −100 = oversold."""
    hn, ln = pl.col("h").rolling_max(window), pl.col("l").rolling_min(window)
    rng = hn - ln
    wr = pl.when(rng != 0).then((hn - pl.col("c")) / rng).otherwise(0.0) * -100
    return _latest({"h": high, "l": low, "c": close}, wr)


def adx(
    high: pl.Series, low: pl.Series, close: pl.Series, window: int = 14, adx_span: int = 6
) -> tuple[float, float, float]:
    """Latest (ADX, +DI, −DI) — Wilder's DMI. +DM/−DM are smoothed (SMMA) and normalized by
    ATR into the directional indices; DX = |+DI−−DI|/(+DI+−DI)·100; ADX = EMA(DX, adx_span).
    ADX>25 ≈ trending (direction from which DI leads), <20 ≈ choppy. adx_span=6 per stockstats."""
    hd, ld = pl.col("h").diff(), -pl.col("l").diff()
    pdm = pl.when((hd > 0) & (hd > ld)).then(hd).otherwise(0.0)
    ndm = pl.when((ld > 0) & (ld > hd)).then(ld).otherwise(0.0)
    atr = _wilder(_tr_expr(), window)
    pdi, ndi = _wilder(pdm, window) / atr * 100, _wilder(ndm, window) / atr * 100
    s = pdi + ndi
    dx = pl.when(s != 0).then((pdi - ndi).abs() / s).otherwise(0.0) * 100
    df = pl.DataFrame({"h": high, "l": low, "c": close}).select(
        _ema(dx, adx_span).alias("adx"), pdi.alias("pdi"), ndi.alias("ndi")
    )
    return (
        float(df["adx"].tail(1).item()),
        float(df["pdi"].tail(1).item()),
        float(df["ndi"].tail(1).item()),
    )


def mfi(
    high: pl.Series, low: pl.Series, close: pl.Series, volume: pl.Series, window: int = 14
) -> float:
    """Latest Money Flow Index (volume-weighted RSI): 100·posFlow/(posFlow+negFlow) over the
    window, flow = TP·volume bucketed by TP direction. >80 overbought, <20 oversold.
    Scaled 0-100 per the standard (stockstats returns the 0-1 fraction)."""
    tp = (pl.col("h") + pl.col("l") + pl.col("c")) / 3
    rmf = tp * pl.col("v")
    tpd = tp.diff()
    pos = pl.when(tpd > 0).then(rmf).otherwise(0.0).rolling_sum(window)
    neg = pl.when(tpd < 0).then(rmf).otherwise(0.0).rolling_sum(window)
    total = pos + neg
    out = pl.when(total > 0).then(pos / total * 100).otherwise(50.0)
    return _latest({"h": high, "l": low, "c": close, "v": volume}, out)


def obv(close: pl.Series, volume: pl.Series) -> float:
    """Latest On-Balance Volume (running Σ of ±volume by close direction). Standard textbook
    definition — NOT in stockstats; added here to round out volume-conviction reads. Absolute
    level is arbitrary; what matters is its slope vs price (confirmation / divergence)."""
    d = pl.col("c").diff().sign().fill_null(0)
    return _latest({"c": close, "v": volume}, (d * pl.col("v")).cum_sum())


def trix(close: pl.Series, window: int = 12) -> float:
    """Latest TRIX (×100): 1-bar rate-of-change of a triple-smoothed EMA of close. Oscillates
    around 0 — above/rising = momentum up, below/falling = down; triple-smoothing filters noise."""
    e3 = _ema(_ema(_ema(pl.col("c"), window), window), window)
    return _latest({"c": close}, (e3 / e3.shift(1) - 1) * 100)


def roc(close: pl.Series, window: int = 12) -> float:
    """Latest Rate of Change (×100): (C / C[t−window] − 1). Raw momentum; >0 up, <0 down."""
    return _latest({"c": close}, (pl.col("c") / pl.col("c").shift(window) - 1) * 100)


def cmo(close: pl.Series, window: int = 14) -> float:
    """Latest Chande Momentum Oscillator: 100·(ΣUp − ΣDown)/(ΣUp + ΣDown) over the window.
    Range −100..+100; unlike RSI it uses raw (unsmoothed) sums, so it's more responsive."""
    d = pl.col("c").diff()
    up, dn = d.clip(lower_bound=0).rolling_sum(window), (-d).clip(lower_bound=0).rolling_sum(window)
    s = up + dn
    return _latest({"c": close}, pl.when(s != 0).then((up - dn) / s * 100).otherwise(0.0))


def aroon(high: pl.Series, low: pl.Series, window: int = 25) -> float:
    """Latest Aroon oscillator (AroonUp − AroonDown), range −100..+100. AroonUp = 100·(N −
    bars-since-N-bar-high)/N, AroonDown likewise for the low. Positive = uptrend in control
    (a recent high), negative = downtrend. Depends only on the last `window` bars."""
    if high.len() < window:
        return 0.0
    h, l = high.tail(window), low.tail(window)
    since_high = (window - 1) - int(h.arg_max())
    since_low = (window - 1) - int(l.arg_min())
    return (window - since_high) / window * 100 - (window - since_low) / window * 100


def supertrend(
    high: pl.Series, low: pl.Series, close: pl.Series, window: int = 14, mult: float = 3.0
) -> tuple[float, float]:
    """Latest (supertrend line, direction) — ATR-banded trend follower. Bands = (H+L)/2 ± mult·ATR,
    ratcheted so they only tighten toward price; direction flips (+1 up / −1 down) when close
    crosses the active band. The line acts as a trailing stop. Recursive, so computed bar-by-bar."""
    n = close.len()
    if n < 2:
        return float(close.tail(1).item()), 0.0
    atr = (
        pl.DataFrame({"h": high, "l": low, "c": close})
        .select(_wilder(_tr_expr(), window).alias("a"))["a"]
        .to_list()
    )
    h, l, c = high.to_list(), low.to_list(), close.to_list()
    fub = flb = 0.0
    st, direction = 0.0, 0.0
    for i in range(1, n):
        a = atr[i] or 0.0
        hl2 = (h[i] + l[i]) / 2
        bub, blb = hl2 + mult * a, hl2 - mult * a
        fub = bub if (bub < fub or c[i - 1] > fub) else fub
        flb = blb if (blb > flb or c[i - 1] < flb) else flb
        if c[i] > fub:
            direction = 1.0
        elif c[i] < flb:
            direction = -1.0
        st = flb if direction == 1.0 else fub
    return float(st), direction


def kama(close: pl.Series, window: int = 10, fast: int = 5, slow: int = 34) -> float:
    """Latest Kaufman Adaptive Moving Average: an EMA whose smoothing speeds up in trends and
    slows in chop, via the efficiency ratio ER = |C−C[t−window]| / Σ|ΔC|. Seeded with SMA(window).

    NOTE: matches stockstats' smoothing `2·(ER·(2/(fast+1) − 2/(slow+1)) + 2/(slow+1))`, which
    omits the StockCharts squaring of that constant — kept for fidelity to the ported source."""
    n = close.len()
    if n < window + 1:
        return float(close.tail(1).item())
    c = close.to_list()
    absdiff = [0.0] + [abs(c[i] - c[i - 1]) for i in range(1, n)]
    fast_sc, slow_sc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    last = sum(c[0:window]) / window  # SMA seed at bar window-1
    for i in range(window, n):
        vol = sum(absdiff[i - window + 1 : i + 1])
        er = abs(c[i] - c[i - window]) / vol if vol > 0 else 0.0
        sc = 2.0 * (er * (fast_sc - slow_sc) + slow_sc)
        last = last + sc * (c[i] - last)
    return float(last)


def kdj_cross(
    high: pl.Series, low: pl.Series, close: pl.Series, window: int = 9, smooth: int = 3
) -> str:
    """Detect if KDJ crossed on the latest bar.

    Returns "golden" (K crossed above D), "death" (K crossed below D), or "none".
    """
    if close.len() < window + smooth * 2:
        return "none"

    hh, ll = pl.col("h").rolling_max(window), pl.col("l").rolling_min(window)
    rng = hh - ll
    rsv = pl.when(rng != 0).then((pl.col("c") - ll) / rng * 100).otherwise(0.0)
    k_expr, d_expr = _wilder(rsv, smooth), _wilder(_wilder(rsv, smooth), smooth)
    df = pl.DataFrame({"h": high, "l": low, "c": close}).select(
        k_expr.alias("k"), d_expr.alias("d")
    ).drop_nulls()

    if df.height < 2:
        return "none"

    k_series = df["k"]
    d_series = df["d"]

    k_prev = float(k_series.tail(2).head(1).item())
    k_curr = float(k_series.tail(1).item())
    d_prev = float(d_series.tail(2).head(1).item())
    d_curr = float(d_series.tail(1).item())

    if k_prev <= d_prev and k_curr > d_curr:
        return "golden"
    if k_prev >= d_prev and k_curr < d_curr:
        return "death"
    return "none"
