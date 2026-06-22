"""Support & resistance ZONE detection.

Reproduces a trader's discretionary support/resistance grading (small/medium/
strong/super-strong) as a 4-layer pipeline: candidate extraction -> per-candidate
scoring -> 1-D clustering into bands -> per-ticker normalization into ordinal
strength labels.

Pure functions, Polars in. `detect_zones` reads only the frame it's handed, so
slicing the frame to week T yields an as-of-T result (no look-ahead) — same
contract as quant/indicators.py, just a list output instead of a scalar.

Strength principles encoded (from the lecture):
  - structural "points" (fib, swing) > range "zones"
  - longer-duration structure > shorter (time priority, log-damped)
  - higher volume-at-price > lower (when Volume present)
  - more touches/tests > fewer
  - confluence: independent methods agreeing at one price is the biggest bonus
  - strength is fuzzy & relative to the stock itself (per-ticker quantile labels)

Both timeframes are read: weekly bars (resampled from the daily frame) surface the
big multi-month structures the lecture prioritizes; daily bars add finer levels.
Candidates from both are pooled before clustering.

Trendlines are deferred: sloping levels need a different (slope, intercept) model,
and all calibration zones are horizontal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import polars as pl

from quant import indicators
from quant.models import Zone

# Ordinal strength labels, weakest -> strongest.
_LABELS = ["small", "medium", "strong", "super-strong"]


@dataclass
class _Candidate:
    """One raw price level before clustering. Internal to this module."""
    price: float            # point level, or band midpoint for zone-kind sources
    low: float              # == price for points; band low for boxes/volume nodes
    high: float             # == price for points; band high for boxes/volume nodes
    method: str             # swing | box | fib | round | ma | volume
    is_point: bool          # True = precise structural level; False = range band
    duration_days: int      # calendar span of the structure (time priority)
    timeframe: str          # daily | weekly
    touch_count: int = 0
    reaction: float = 0.0   # bounce magnitude in ATRs (pivots only; else 0)
    volume: float = 0.0     # volume-at-price ratio vs mean bucket (volume nodes only)
    score: float = 0.0      # filled by _score_candidate


# --------------------------------------------------------------------------- #
# Timeframe resampling
# --------------------------------------------------------------------------- #
def _to_weekly(df: pl.DataFrame) -> pl.DataFrame:
    """Resample a daily OHLC(V) frame into weekly bars."""
    aggs = [
        pl.col("Open").first().alias("Open"),
        pl.col("High").max().alias("High"),
        pl.col("Low").min().alias("Low"),
        pl.col("Close").last().alias("Close"),
    ]
    if "Volume" in df.columns:
        aggs.append(pl.col("Volume").sum().alias("Volume"))
    return df.sort("date").group_by_dynamic("date", every="1w").agg(aggs).sort("date")


# --------------------------------------------------------------------------- #
# Layer 1 — candidate extractors
# --------------------------------------------------------------------------- #
def _touch_tol(level: float, atr: float, lev: dict) -> float:
    """Adaptive proximity tolerance, reused for touch-counting and clustering."""
    return max(lev.get("cluster_pct", 0.015) * level, lev.get("cluster_atr_mult", 1.0) * atr)


def _count_touches(frame: pl.DataFrame, level: float, tol: float) -> int:
    """Bars whose [Low-tol, High+tol] range straddles the level."""
    near = ((frame["Low"] - tol) <= level) & (level <= (frame["High"] + tol))
    return int(near.sum())


def _swing_pivots(
    frame: pl.DataFrame, k: int, bar_days: int, atr: float, timeframe: str
) -> list[_Candidate]:
    """Fractal swing highs/lows: an extreme of the symmetric 2k+1 window."""
    if frame.height < 2 * k + 1:
        return []
    win = 2 * k + 1
    marked = frame.with_columns(
        pl.col("High").rolling_max(win, center=True).alias("_hmax"),
        pl.col("Low").rolling_min(win, center=True).alias("_lmin"),
    )
    highs = frame["High"].to_list()
    lows = frame["Low"].to_list()
    hmax = marked["_hmax"].to_list()
    lmin = marked["_lmin"].to_list()
    n = len(highs)
    out: list[_Candidate] = []
    for i in range(n):
        is_sh = hmax[i] is not None and highs[i] == hmax[i]
        is_sl = lmin[i] is not None and lows[i] == lmin[i]
        if is_sh:
            fwd_low = min(lows[i + 1 : i + 1 + k], default=lows[i])
            reaction = min((highs[i] - fwd_low) / atr, 10.0) if atr else 0.0
            out.append(_Candidate(highs[i], highs[i], highs[i], "swing", True,
                                  bar_days, timeframe, 1, max(reaction, 0.0)))
        if is_sl:
            fwd_high = max(highs[i + 1 : i + 1 + k], default=highs[i])
            reaction = min((fwd_high - lows[i]) / atr, 10.0) if atr else 0.0
            out.append(_Candidate(lows[i], lows[i], lows[i], "swing", True,
                                  bar_days, timeframe, 1, max(reaction, 0.0)))
    return out


def _range_boxes(
    frame: pl.DataFrame, bar_days: int, lev: dict, timeframe: str
) -> list[_Candidate]:
    """Consolidation bands: maximal runs where price stays range-bound."""
    win = lev.get("box_win", 8)
    box_pct = lev.get("box_pct", 0.06)
    if frame.height < win:
        return []
    marked = frame.with_columns(
        (
            (pl.col("High").rolling_max(win) - pl.col("Low").rolling_min(win))
            / pl.col("Close").rolling_mean(win)
        ).alias("_range")
    )
    tight = [(r is not None and r < box_pct) for r in marked["_range"].to_list()]
    highs = frame["High"].to_list()
    lows = frame["Low"].to_list()
    n = len(tight)
    out: list[_Candidate] = []
    i = 0
    while i < n:
        if not tight[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and tight[j + 1]:
            j += 1
        # tight at row r means the window [r-win+1, r] is range-bound.
        start = max(0, i - win + 1)
        lo = min(lows[start : j + 1])
        hi = max(highs[start : j + 1])
        mid = (lo + hi) / 2.0
        duration = (j - start + 1) * bar_days
        out.append(_Candidate(mid, lo, hi, "box", False, duration, timeframe))
        i = j + 1
    return out


def _fib_levels(
    frame: pl.DataFrame, bar_days: int, lev: dict, atr: float, timeframe: str
) -> list[_Candidate]:
    """Fibonacci retracements of the dominant swing (max High, min Low) in frame."""
    if frame.height < 5:
        return []
    highs = frame["High"].to_list()
    lows = frame["Low"].to_list()
    hi = max(highs)
    lo = min(lows)
    if hi <= lo:
        return []
    hi_i = highs.index(hi)
    lo_i = lows.index(lo)
    duration = abs(hi_i - lo_i) * bar_days
    out: list[_Candidate] = []
    for ratio in lev.get("fib_ratios", [0.236, 0.382, 0.5, 0.618, 0.786]):
        level = lo + ratio * (hi - lo)
        touches = _count_touches(frame, level, _touch_tol(level, atr, lev))
        out.append(_Candidate(level, level, level, "fib", True, duration, timeframe, touches))
    return out


def _round_numbers(frame: pl.DataFrame, atr: float, lev: dict, timeframe: str) -> list[_Candidate]:
    """Psychological round-number levels across the frame's price range."""
    lo = float(frame["Low"].min())
    hi = float(frame["High"].max())
    mid = (lo + hi) / 2.0
    if mid < 50:
        step = 5.0
    elif mid < 200:
        step = 10.0
    elif mid < 500:
        step = 25.0
    else:
        step = 50.0
    out: list[_Candidate] = []
    level = math.ceil(lo / step) * step
    while level <= hi:
        touches = _count_touches(frame, level, _touch_tol(level, atr, lev))
        out.append(_Candidate(level, level, level, "round", True, 0, timeframe, touches))
        level += step
    return out


def _ma_levels(frame: pl.DataFrame, atr: float, lev: dict, timeframe: str) -> list[_Candidate]:
    """Latest MA50 / MA200 as dynamic levels (low prior — set in config)."""
    close = frame["Close"]
    out: list[_Candidate] = []
    for window in (50, 200):
        if close.len() >= window:
            level = indicators.moving_average(close, window)
            touches = _count_touches(frame, level, _touch_tol(level, atr, lev))
            out.append(_Candidate(level, level, level, "ma", True, 0, timeframe, touches))
    return out


def _volume_nodes(
    frame: pl.DataFrame, bar_days: int, lev: dict, timeframe: str
) -> list[_Candidate]:
    """Volume-by-price high-volume nodes (Close-binned volume; VWAP-by-price proxy).

    Returns [] when no Volume column is present, so the pipeline is volume-agnostic."""
    if "Volume" not in frame.columns or frame.height < 10:
        return []
    nbins = lev.get("volume_bins", 40)
    node_mult = lev.get("volume_node_mult", 1.3)
    lo = float(frame["Low"].min())
    hi = float(frame["High"].max())
    if hi <= lo:
        return []
    width = (hi - lo) / nbins
    binned = (
        frame.with_columns(
            ((pl.col("Close") - lo) / width).floor().clip(0, nbins - 1).cast(pl.Int64).alias("_b")
        )
        .group_by("_b")
        .agg(pl.col("Volume").sum().alias("v"), pl.len().alias("bars"))
        .sort("_b")
    )
    bidx = binned["_b"].to_list()
    vols = binned["v"].to_list()
    bars = binned["bars"].to_list()
    vol_by_bin = dict(zip(bidx, vols))
    bars_by_bin = dict(zip(bidx, bars))
    mean_vol = sum(vols) / len(vols) if vols else 0.0
    if mean_vol <= 0:
        return []
    out: list[_Candidate] = []
    for b, v in zip(bidx, vols):
        if v < mean_vol * node_mult:
            continue
        # local maximum vs neighbouring bins
        if v < vol_by_bin.get(b - 1, 0) or v < vol_by_bin.get(b + 1, 0):
            continue
        center = lo + (b + 0.5) * width
        out.append(_Candidate(
            price=center, low=lo + b * width, high=lo + (b + 1) * width,
            method="volume", is_point=False, duration_days=bars_by_bin[b] * bar_days,
            timeframe=timeframe, volume=v / mean_vol,
        ))
    return out


def _anchored_vwap(
    frame: pl.DataFrame, bar_days: int, lev: dict, atr: float, timeframe: str
) -> list[_Candidate]:
    """Volume-weighted average price anchored at the major swing LOWS — the bullish "anchored
    VWAP from the low" institutions defend as dynamic support in an uptrend. (VWAP anchored to
    highs / window-start behaves as a mean/magnet, not a reversal level, and tested with negative
    edge — so we anchor only to lows.) Needs Volume; returns [] otherwise."""
    if "Volume" not in frame.columns or frame.height < 20:
        return []
    k = lev.get("pivot_k", 5)
    low = frame["Low"].to_list()
    h = frame["High"].to_list()
    c = frame["Close"].to_list()
    v = frame["Volume"].to_list()
    n = len(c)
    lmin = frame["Low"].rolling_min(2 * k + 1, center=True).to_list()
    swing_lows = [i for i in range(n) if lmin[i] is not None and low[i] == lmin[i]]
    if not swing_lows:
        swing_lows = [low.index(min(low))]
    anchors = sorted(swing_lows, key=lambda i: low[i])[: lev.get("vwap_anchors", 3)]
    out: list[_Candidate] = []
    for a in sorted(set(anchors)):
        cum_pv = cum_v = 0.0
        for i in range(a, n):
            cum_pv += (h[i] + low[i] + c[i]) / 3.0 * v[i]
            cum_v += v[i]
        if cum_v <= 0:
            continue
        level = cum_pv / cum_v
        touches = _count_touches(frame, level, _touch_tol(level, atr, lev))
        out.append(_Candidate(level, level, level, "vwap", True,
                              (n - 1 - a) * bar_days, timeframe, touches))
    return out


def _extract(
    frame: pl.DataFrame, timeframe: str, bar_days: int, lev: dict, atr: float
) -> list[_Candidate]:
    """Run all Layer-1 extractors on one timeframe's frame."""
    k = lev.get("pivot_k", 5)
    cands: list[_Candidate] = []
    cands += _swing_pivots(frame, k, bar_days, atr, timeframe)
    cands += _range_boxes(frame, bar_days, lev, timeframe)
    cands += _fib_levels(frame, bar_days, lev, atr, timeframe)
    cands += _round_numbers(frame, atr, lev, timeframe)
    cands += _ma_levels(frame, atr, lev, timeframe)
    cands += _volume_nodes(frame, bar_days, lev, timeframe)
    cands += _anchored_vwap(frame, bar_days, lev, atr, timeframe)
    return cands


# --------------------------------------------------------------------------- #
# Layer 2 — per-candidate scoring
# --------------------------------------------------------------------------- #
def _score_candidate(c: _Candidate, lev: dict) -> float:
    w = lev.get("weights", {})
    mp = lev.get("method_prior", {})
    cap = lev.get("touch_cap", 5)
    s = w.get("kind", 1.0) * (1.0 if c.is_point else 0.6)
    s += w.get("duration", 1.0) * math.log1p(max(c.duration_days, 0))
    s += w.get("touch", 0.8) * min(c.touch_count, cap)
    s += w.get("reaction", 0.6) * c.reaction
    s += w.get("volume", 1.0) * c.volume
    s += w.get("method", 1.0) * mp.get(c.method, 0.5)
    return s


# --------------------------------------------------------------------------- #
# Layer 3 — clustering into zones
# --------------------------------------------------------------------------- #
def _cluster(cands: list[_Candidate], lev: dict, atr: float, price: float) -> list[Zone]:
    """Greedy 1-D agglomerative merge of nearby candidates into price bands."""
    if not cands:
        return []
    bonus = lev.get("confluence_bonus", 0.35)
    count_damp = lev.get("count_damp", 0.5)
    max_frac = lev.get("max_zone_frac", 0.08)
    ordered = sorted(cands, key=lambda c: c.price)
    groups: list[list[_Candidate]] = [[ordered[0]]]
    cur_low = ordered[0].price  # candidates are point prices; sorted ascending
    for c in ordered[1:]:
        tol = _touch_tol(c.price, atr, lev)
        prev = groups[-1][-1].price
        # single-link gap to the nearest member, plus a hard cap on cluster span so
        # dense regions don't chain into one over-wide zone.
        if (c.price - prev) <= tol and (c.price - cur_low) <= max_frac * c.price:
            groups[-1].append(c)
        else:
            groups.append([c])
            cur_low = c.price

    zones: list[Zone] = []
    for g in groups:
        methods = sorted({m.method for m in g})
        timeframes = sorted({m.timeframe for m in g})
        # Damp raw member count: near-price regions accumulate many candidates of every
        # method, so a plain sum ranks "activity density" rather than structural strength.
        base = sum(m.score for m in g) / (len(g) ** count_damp)
        score = base * (1 + bonus * (len(methods) - 1))
        low = min(m.low for m in g)
        high = max(m.high for m in g)
        mid = (low + high) / 2.0
        zones.append(Zone(
            low=low, high=high, score=score, label="small",
            kind="support" if mid <= price else "resistance",
            touches=sum(m.touch_count for m in g),
            methods=methods, timeframes=timeframes, members=len(g),
        ))
    return zones


# --------------------------------------------------------------------------- #
# Layer 4 — per-ticker normalization into ordinal labels
# --------------------------------------------------------------------------- #
def _label_zones(zones: list[Zone], lev: dict) -> None:
    """Assign ordinal labels by within-ticker score quantiles (fuzzy & relative)."""
    if not zones:
        return
    q = lev.get("label_quantiles", {})
    scores = pl.Series([z.score for z in zones])
    ss = scores.quantile(q.get("super_strong", 0.90), interpolation="linear")
    s = scores.quantile(q.get("strong", 0.65), interpolation="linear")
    m = scores.quantile(q.get("medium", 0.30), interpolation="linear")
    for z in zones:
        if z.score >= ss:
            label = "super-strong"
        elif z.score >= s:
            label = "strong"
        elif z.score >= m:
            label = "medium"
        else:
            label = "small"
        # Confluence cap: the out-of-sample edge test (scripts/level_edge.py) shows only
        # zones with >= strong_min_methods distinct methods reverse price more than a random
        # level — lower-confluence zones never earn a strong/super-strong label.
        if len(z.methods) < lev.get("strong_min_methods", 3) and label in ("strong", "super-strong"):
            label = "medium"
        z.label = label


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def detect_zones(df: pl.DataFrame, cfg: dict, current_price: float | None = None) -> list[Zone]:
    """Detect ranked support/resistance zones from an OHLC(V) frame.

    `df` is a date-sorted Polars frame (date, Open, High, Low, Close[, Volume]).
    Reads only `df`, so slicing to week T gives an as-of-T result. Returns zones
    sorted by strength score, descending."""
    lev = cfg.get("levels", {})
    df = df.sort("date")
    if df.height < 5:
        return []
    price = current_price if current_price is not None else float(df["Close"].tail(1).item())
    atr_val = indicators.atr(df["High"], df["Low"], df["Close"]) or price * 0.02

    lookback = lev.get("lookback_bars", 504)
    daily = df.tail(lookback) if lookback else df
    weekly = _to_weekly(df)
    if lookback:
        weekly = weekly.tail(max(1, lookback // 5))

    cands = _extract(daily, "daily", 1, lev, atr_val)
    cands += _extract(weekly, "weekly", 5, lev, atr_val)
    # Actionable-range filter: a trader draws S/R near current price, not at the
    # stock's ancient pre-growth base. Without this, regions where price spent years
    # early in a 10y history rack up huge member counts and dominate scoring. The
    # ceiling extends to the historical high so overhead resistance after a pullback
    # (price well below its recent peak) is still surfaced.
    hi = float(daily["High"].max())
    floor = lev.get("price_floor_frac", 0.4) * price
    ceiling = max(lev.get("price_ceiling_frac", 1.35) * price, hi * 1.02)
    cands = [c for c in cands if floor <= c.price <= ceiling]
    if not cands:
        return []
    for c in cands:
        c.score = _score_candidate(c, lev)

    zones = _cluster(cands, lev, atr_val, price)
    # Confluence filter: drop zones with too few distinct methods (see _label_zones note).
    min_methods = lev.get("min_methods", 2)
    zones = [z for z in zones if len(z.methods) >= min_methods]
    _label_zones(zones, lev)
    zones.sort(key=lambda z: z.score, reverse=True)
    return zones
