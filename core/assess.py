"""Technical Assessor for core.

Computes technical indicators, support/resistance levels, and judges investment/speculative candidates,
storing all detailed metrics in the Assessment payload bitemporally.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
import polars as pl

from core import clock, indicators
from core.memory import Memory
from core.record import Assessment, Fact


def detect_sr_levels(
    close_series: pl.Series, high_series: pl.Series, low_series: pl.Series, window: int = 10
) -> tuple[float | None, float | None]:
    """Lightweight support and resistance swing-pivot finder.
    
    Returns (nearest_support, nearest_resistance) relative to the latest close price.
    """
    if len(close_series) < window * 2:
        return None, None
        
    price = float(close_series.tail(1).item())
    pivots_low = []
    pivots_high = []
    
    highs = high_series.to_list()
    lows = low_series.to_list()
    
    for i in range(window, len(highs) - window):
        # Local high
        if highs[i] == max(highs[i - window : i + window + 1]):
            pivots_high.append(highs[i])
        # Local low
        if lows[i] == min(lows[i - window : i + window + 1]):
            pivots_low.append(lows[i])
            
    # Nearest support is the highest pivot low below current price
    supports = [p for p in pivots_low if p < price]
    nearest_support = max(supports) if supports else None
    
    # Nearest resistance is the lowest pivot high above current price
    resistances = [p for p in pivots_high if p > price]
    nearest_resistance = min(resistances) if resistances else None
    
    # Fallback to 52w low and 52w high if no pivots found
    if nearest_support is None:
        nearest_support = float(low_series.tail(252).min())
    if nearest_resistance is None:
        nearest_resistance = float(high_series.tail(252).max())
        
    return nearest_support, nearest_resistance


def load_cached_fundamentals(symbol: str) -> dict:
    """Load cached fundamentals from data/cache/fundamentals.json for the symbol."""
    path = "data/cache/fundamentals.json"
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f) or {}
            # Cache is a map symbol -> dictionary
            return data.get(symbol) or {}
        except Exception:
            return {}
    return {}


def run_technical_assessments(
    memory: Memory,
    symbol: str,
    as_of: datetime | None = None,
    *,
    version: str = "v1",
) -> list[Assessment]:
    """Run all technical perspective assessments for a symbol as of a specific instant.
    
    Returns a list of Assessments (technical indicators, left_side_entry, bottom_fishing).
    """
    at = as_of or clock.now()
    
    # Fetch Fact historical series
    close_facts = memory.facts(symbol, "close", as_of=at)
    high_facts = memory.facts(symbol, "high", as_of=at)
    low_facts = memory.facts(symbol, "low", as_of=at)
    volume_facts = memory.facts(symbol, "volume", as_of=at)
    
    if len(close_facts) < 20:
        return []  # Not enough data for meaningful indicators
        
    close = pl.Series([f.value for f in close_facts])
    high = pl.Series([f.value for f in high_facts])
    low = pl.Series([f.value for f in low_facts])
    volume = pl.Series([f.value for f in volume_facts])
    
    price = float(close.tail(1).item())
    event_date = close_facts[-1].event_at
    
    # Compute classic indicators
    ma20 = indicators.moving_average(close, 20)
    ma50 = indicators.moving_average(close, 50)
    ma200 = indicators.moving_average(close, 200) if len(close) >= 200 else ma50
    rsi_val = indicators.rsi(close)
    
    macd_line, macd_sig, macd_hist = indicators.macd(close)
    macd_line_full = indicators._macd_line(close, 12, 26)
    macd_sig_full = macd_line_full.ewm_mean(span=9, adjust=False)
    macd_hist_full = macd_line_full - macd_sig_full
    macd_cross_val = "none"
    if macd_hist_full.len() >= 2:
        macd_cross_val = indicators.macd_cross(
            float(macd_hist_full.tail(2).head(1).item()),
            float(macd_hist_full.tail(1).item())
        )
        
    div = indicators.macd_divergence(close, high, low)
    bb_bw, bb_pct_b, bb_squeeze = indicators.bollinger(close)
    k_val, d_val, j_val = indicators.kdj(high, low, close)
    kdj_cross_val = indicators.kdj_cross(high, low, close)
    sup, res = detect_sr_levels(close, high, low)
    atr_val = indicators.atr(high, low, close)
    atr_mult = indicators.atr_move_multiple(close, atr_val)
    rvol_val = indicators.rvol(volume)
    vol_z = indicators.volume_zscore(volume)
    
    # Trend Score
    trend_score = 0.0
    if price > ma20: trend_score += 25
    if ma20 > ma50: trend_score += 25
    if ma50 > ma200: trend_score += 25
    if price > ma200: trend_score += 25
    
    # Volume State
    vol_state = "Normal"
    if vol_z >= 2.0:
        vol_state = "Abnormal"
    elif vol_z >= 1.0:
        vol_state = "Elevated"
        
    # Day change
    day_change_pct = 0.0
    if len(close) >= 2:
        prev_close = float(close.tail(2).head(1).item())
        if prev_close > 0:
            day_change_pct = (price - prev_close) / prev_close
            
    # Load fundamentals
    fund = load_cached_fundamentals(symbol)
    peg = fund.get("peg")
    if peg is not None:
        peg = float(peg)
    val_label = fund.get("valuation_label") or "fair"
    
    # 52w extremes
    hi_52w = indicators.high_52w(high)
    lo_52w = indicators.low_52w(low)
    
    # Build complete technical metric dictionary
    metrics = {
        "price": price,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "rsi": rsi_val,
        "macd": macd_line,
        "macd_signal": macd_sig,
        "macd_hist": macd_hist,
        "macd_cross": macd_cross_val,
        "macd_divergence": div,
        "bb_bandwidth": bb_bw,
        "bb_pct_b": bb_pct_b,
        "bb_squeeze": bb_squeeze,
        "kdj_k": k_val,
        "kdj_d": d_val,
        "kdj_j": j_val,
        "kdj_cross": kdj_cross_val,
        "support": sup,
        "resistance": res,
        "atr": atr_val,
        "atr_move": atr_mult,
        "trend_score": trend_score,
        "rvol": rvol_val,
        "vol_z": vol_z,
        "vol_state": vol_state,
        "day_change_pct": day_change_pct,
        "peg": peg,
        "valuation_label": val_label,
        "high_52w": hi_52w,
        "low_52w": lo_52w,
    }
    metrics_json = json.dumps(metrics)
    
    # Compile Fact references
    fact_refs = tuple(f.id for f in (close_facts + high_facts + low_facts + volume_facts))
    
    results: list[Assessment] = []
    
    # 1. Base Technical Indicators Assessment
    results.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=event_date,
        known_at=at,
        provenance=f"technical_assessor@{version}",
        refs=fact_refs,
        perspective="technical",
        result="neutral",
        confidence=1.0,
        payload=metrics_json,
    ))
    
    # 2. Left-Side Entry Candidate Assessment
    # Conditions: Downward trend / pullbacks + Cheap/Fair valuation + Near support
    is_left_side = False
    if trend_score < 75 or price < ma20:
        if val_label in ("cheap (growth-justified)", "fair") or (peg is not None and peg <= 2.0):
            if sup is not None:
                dist_pct = (price - sup) / price if price > 0 else 0.0
                if 0 <= dist_pct <= 0.05 or (price - sup <= 1.5 * atr_val):
                    is_left_side = True
                    
    results.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=event_date,
        known_at=at,
        provenance=f"left_side_entry_assessor@{version}",
        refs=fact_refs,
        perspective="left_side_entry",
        result="candidate" if is_left_side else "none",
        confidence=0.8 if is_left_side else 0.0,
        payload=metrics_json,
    ))
    
    # 3. Bottom-Fishing Candidate Assessment
    # Conditions: Deeply oversold OR MACD bullish divergence + Near strong support
    is_bottom_fishing = False
    if rsi_val <= 35 or bb_pct_b <= 0.0 or div == "bullish":
        if sup is not None:
            dist_pct = (price - sup) / price if price > 0 else 0.0
            if 0 <= dist_pct <= 0.05 or (price - sup <= 1.5 * atr_val):
                is_bottom_fishing = True
                
    results.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=event_date,
        known_at=at,
        provenance=f"bottom_fishing_assessor@{version}",
        refs=fact_refs,
        perspective="bottom_fishing",
        result="candidate" if is_bottom_fishing else "none",
        confidence=0.9 if is_bottom_fishing else 0.0,
        payload=metrics_json,
    ))

    return results


def momentum_assessment(
    memory: Memory,
    subject: str,
    as_of: datetime | None = None,
    *,
    oversold: float = 30.0,
    overbought: float = 70.0,
    version: str = "v1",
) -> Assessment | None:
    """Read `subject`'s close Facts known by `as_of`, and judge momentum via RSI."""
    at = as_of or clock.now()
    facts = memory.facts(subject, metric="close", as_of=at)
    if len(facts) < 2:
        return None

    close = pl.Series([f.value for f in facts])
    rsi = indicators.rsi(close)
    if rsi <= oversold:
        result = "oversold"
    elif rsi >= overbought:
        result = "overbought"
    else:
        result = "neutral"

    # Deterministic confidence: how far RSI sits from the neutral 50, normalized to 0..1.
    confidence = round(min(abs(rsi - 50.0) / 50.0, 1.0), 4)

    return Assessment(
        kind="assessment",
        subject=subject,
        event_at=facts[-1].event_at,          # judged as of the latest bar it read
        known_at=at,                           # made at the judgment instant (= now, live; = t, replay)
        provenance=f"momentum_assessor@{version}",
        refs=tuple(f.id for f in facts),       # the Facts this judgment rests on
        perspective="momentum",
        result=result,
        confidence=confidence,
    )
