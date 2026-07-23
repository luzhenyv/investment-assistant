"""Technical, Fundamental, and Abstract Assessor framework for core.

Computes technical indicators, support/resistance levels, and fundamental valuation metrics,
and judges investment/speculative candidates, storing all detailed metrics in the
Assessment payload bitemporally.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import date, datetime
import polars as pl

from core import clock, indicators
from core.memory import Memory
from core.record import Assessment, Fact


class Assessor(ABC):
    """Abstract Base Class for all bitemporal Assessors in core."""

    def __init__(self, version: str = "v1"):
        self.version = version

    @property
    @abstractmethod
    def perspective(self) -> str:
        """The perspective name (e.g. 'technical', 'fundamental', 'left_side_entry')."""
        pass

    @property
    def provenance(self) -> str:
        """The provenance identifier (e.g. 'technical_assessor@v1')."""
        return f"{self.perspective}_assessor@{self.version}"

    @abstractmethod
    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        """Execute the assessment logic and return exactly one bitemporal Assessment."""
        pass


def _num(s: object) -> float | None:
    """Coerce a field to float. Handles native floats and strings,
    treating "None"/"NaN"/"-"/"null" as missing -> None.
    """
    if s is None:
        return None
    text = str(s).strip()
    if text in ("", "None", "-", "NaN", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def calculate_valuation_label(
    pe: float | None,
    forward_pe: float | None,
    peg: float | None,
    cfg: dict,
) -> str:
    """Coarse valuation tag driven by PEG (growth-adjusted), with a cyclical-ramp note."""
    fund_cfg = cfg.get("fundamentals", {}) if cfg else {}
    peg_cheap = fund_cfg.get("peg_cheap", 1.0)
    peg_rich = fund_cfg.get("peg_rich", 2.0)

    ramping = forward_pe is not None and pe is not None and pe > 0 and forward_pe < 0.6 * pe

    if peg is not None and peg > 0:
        if peg <= peg_cheap:
            base = "cheap (growth-justified)"
        elif peg > peg_rich:
            base = "rich"
        else:
            base = "fair"
    elif ramping:
        base = "fair"
    else:
        return "unknown"

    return f"{base} · fwd PE ≪ trailing" if ramping else base


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


class FundamentalAssessor(Assessor):
    """Computes growth-adjusted valuation labels and produces one fundamental Assessment."""

    @property
    def perspective(self) -> str:
        return "fundamental"

    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        at = as_of or clock.now()
        event_date = clock.today()  # fallback if no facts exist

        # Get latest date from close facts if available
        close_facts = memory.facts(symbol, "close", as_of=at)
        if close_facts:
            event_date = close_facts[-1].event_at

        fund_data = load_cached_fundamentals(symbol)
        if not fund_data:
            return None

        raw = fund_data.get("raw", {})
        fetched = fund_data.get("fetched", "")

        pe = _num(raw.get("pe"))
        forward_pe = _num(raw.get("forward_pe"))
        peg = _num(raw.get("peg"))
        pb = _num(raw.get("pb"))
        ev_ebitda = _num(raw.get("ev_ebitda"))
        profit_margin = _num(raw.get("profit_margin"))
        rev_growth = _num(raw.get("rev_growth"))
        eps_growth = _num(raw.get("eps_growth"))
        analyst_target = _num(raw.get("analyst_target"))
        beta = _num(raw.get("beta"))
        sector = raw.get("sector")

        val_label = calculate_valuation_label(pe, forward_pe, peg, cfg or {})

        payload = {
            "pe": pe,
            "forward_pe": forward_pe,
            "peg": peg,
            "pb": pb,
            "ev_ebitda": ev_ebitda,
            "profit_margin": profit_margin,
            "rev_growth": rev_growth,
            "eps_growth": eps_growth,
            "analyst_target": analyst_target,
            "beta": beta,
            "sector": sector,
            "valuation_label": val_label,
            "as_of": fetched,
        }

        return Assessment(
            kind="assessment",
            subject=symbol,
            event_at=event_date,
            known_at=at,
            provenance=self.provenance,
            refs=(),  # No fact references as this comes from a slow-moving offline JSON cache
            perspective=self.perspective,
            result=val_label,
            confidence=1.0,
            payload=json.dumps(payload),
        )


class TechnicalAssessor(Assessor):
    """Computes technical indicators and levels, producing exactly one technical Assessment."""

    @property
    def perspective(self) -> str:
        return "technical"

    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        at = as_of or clock.now()
        
        # Fetch Fact historical series
        close_facts = memory.facts(symbol, "close", as_of=at)
        high_facts = memory.facts(symbol, "high", as_of=at)
        low_facts = memory.facts(symbol, "low", as_of=at)
        volume_facts = memory.facts(symbol, "volume", as_of=at)
        
        if len(close_facts) < 20:
            return None  # Not enough data for meaningful indicators
            
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
            "high_52w": hi_52w,
            "low_52w": lo_52w,
        }
        metrics_json = json.dumps(metrics)
        
        # Compile Fact references
        fact_refs = tuple(f.id for f in (close_facts + high_facts + low_facts + volume_facts))
        
        return Assessment(
            kind="assessment",
            subject=symbol,
            event_at=event_date,
            known_at=at,
            provenance=self.provenance,
            refs=fact_refs,
            perspective=self.perspective,
            result="neutral",
            confidence=1.0,
            payload=metrics_json,
        )


class BottomFishingAssessor(Assessor):
    """Evaluates Bottom-Fishing Candidates by reading technical indicators bitemporally."""

    @property
    def perspective(self) -> str:
        return "bottom_fishing"

    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        at = as_of or clock.now()
        
        # Lookup the latest technical assessment bitemporally
        asms = memory.as_of(at, "assessment", symbol)
        tech_asm = next((a for a in asms if isinstance(a, Assessment) and a.perspective == "technical"), None)
        
        if not tech_asm or not tech_asm.payload:
            return None
            
        metrics = json.loads(tech_asm.payload)
        price = metrics.get("price")
        rsi_val = metrics.get("rsi")
        bb_pct_b = metrics.get("bb_pct_b")
        div = metrics.get("macd_divergence")
        sup = metrics.get("support")
        atr_val = metrics.get("atr", 0.0)
        
        if price is None or rsi_val is None or bb_pct_b is None:
            return None
            
        is_bottom_fishing = False
        if rsi_val <= 35 or bb_pct_b <= 0.0 or div == "bullish":
            if sup is not None:
                dist_pct = (price - sup) / price if price > 0 else 0.0
                if 0 <= dist_pct <= 0.05 or (price - sup <= 1.5 * atr_val):
                    is_bottom_fishing = True
                    
        return Assessment(
            kind="assessment",
            subject=symbol,
            event_at=tech_asm.event_at,
            known_at=at,
            provenance=self.provenance,
            refs=(tech_asm.id,),
            perspective=self.perspective,
            result="candidate" if is_bottom_fishing else "none",
            confidence=0.9 if is_bottom_fishing else 0.0,
            payload=tech_asm.payload,
        )


class LeftSideEntryAssessor(Assessor):
    """Cross-Lens Assessor: Evaluates Left-Side Entry Candidates from both lenses."""

    @property
    def perspective(self) -> str:
        return "left_side_entry"

    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        at = as_of or clock.now()
        
        # Lookup the latest technical and fundamental assessments bitemporally
        asms = memory.as_of(at, "assessment", symbol)
        tech_asm = next((a for a in asms if isinstance(a, Assessment) and a.perspective == "technical"), None)
        fund_asm = next((a for a in asms if isinstance(a, Assessment) and a.perspective == "fundamental"), None)
        
        if not tech_asm or not tech_asm.payload:
            return None
            
        metrics = json.loads(tech_asm.payload)
        price = metrics.get("price")
        rsi = metrics.get("rsi")
        trend_score = metrics.get("trend_score", 0.0)
        ma20 = metrics.get("ma20")
        support = metrics.get("support")
        atr = metrics.get("atr", 0.0)
        
        if price is None or rsi is None or ma20 is None:
            return None
            
        # Default valuation fallbacks
        val_label = "unknown"
        peg = None
        if fund_asm and fund_asm.payload:
            try:
                fund_payload = json.loads(fund_asm.payload)
                val_label = fund_payload.get("valuation_label") or "unknown"
                peg = fund_payload.get("peg")
            except Exception:
                pass
                
        is_left_side = False
        if trend_score < 75 or price < ma20:
            if val_label in ("cheap (growth-justified)", "fair") or (peg is not None and peg <= 2.0):
                if support is not None:
                    dist_pct = (price - support) / price if price > 0 else 0.0
                    if 0 <= dist_pct <= 0.05 or (price - support <= 1.5 * atr):
                        is_left_side = True
                        
        # Edges in the reference graph point back to both technical and fundamental assessments
        refs = tuple(id_ for id_ in (tech_asm.id, fund_asm.id) if id_ is not None) if fund_asm else (tech_asm.id,)
        
        return Assessment(
            kind="assessment",
            subject=symbol,
            event_at=tech_asm.event_at,
            known_at=at,
            provenance=self.provenance,
            refs=refs,
            perspective=self.perspective,
            result="candidate" if is_left_side else "none",
            confidence=0.8 if is_left_side else 0.0,
            payload=tech_asm.payload,
        )


class MomentumAssessor(Assessor):
    """Concrete Assessor that judges momentum via RSI."""

    def __init__(self, oversold: float = 30.0, overbought: float = 70.0, version: str = "v1"):
        super().__init__(version)
        self.oversold = oversold
        self.overbought = overbought

    @property
    def perspective(self) -> str:
        return "momentum"

    def run(
        self,
        memory: Memory,
        symbol: str,
        as_of: datetime | None = None,
        cfg: dict | None = None,
    ) -> Assessment | None:
        at = as_of or clock.now()
        facts = memory.facts(symbol, metric="close", as_of=at)
        if len(facts) < 2:
            return None

        close = pl.Series([f.value for f in facts])
        rsi = indicators.rsi(close)
        if rsi <= self.oversold:
            result = "oversold"
        elif rsi >= self.overbought:
            result = "overbought"
        else:
            result = "neutral"

        # Deterministic confidence: how far RSI sits from the neutral 50, normalized to 0..1.
        confidence = round(min(abs(rsi - 50.0) / 50.0, 1.0), 4)

        return Assessment(
            kind="assessment",
            subject=symbol,
            event_at=facts[-1].event_at,          # judged as of the latest bar it read
            known_at=at,                           # made at the judgment instant (= now, live; = t, replay)
            provenance=self.provenance,
            refs=tuple(f.id for f in facts),       # the Facts this judgment rests on
            perspective=self.perspective,
            result=result,
            confidence=confidence,
        )


# --- Backward-compatible functional delegates ---

def run_fundamental_assessments(
    memory: Memory,
    symbol: str,
    as_of: datetime | None = None,
    cfg: dict | None = None,
    *,
    version: str = "v1",
) -> Assessment | None:
    """Run fundamental assessments for a symbol (delegated to FundamentalAssessor)."""
    return FundamentalAssessor(version).run(memory, symbol, as_of, cfg)


def run_technical_assessments(
    memory: Memory,
    symbol: str,
    as_of: datetime | None = None,
    *,
    version: str = "v1",
) -> Assessment | None:
    """Run pure technical indicators assessment for a symbol (delegated to TechnicalAssessor)."""
    return TechnicalAssessor(version).run(memory, symbol, as_of)


def run_bottom_fishing_assessment(
    memory: Memory,
    symbol: str,
    as_of: datetime | None = None,
    *,
    version: str = "v1",
) -> Assessment | None:
    """Evaluates Bottom-Fishing Candidates (delegated to BottomFishingAssessor)."""
    return BottomFishingAssessor(version).run(memory, symbol, as_of)


def run_left_side_assessment(
    memory: Memory,
    symbol: str,
    as_of: datetime | None = None,
    *,
    version: str = "v1",
) -> Assessment | None:
    """Evaluates Left-Side Entry Candidates (delegated to LeftSideEntryAssessor)."""
    return LeftSideEntryAssessor(version).run(memory, symbol, as_of)


def momentum_assessment(
    memory: Memory,
    subject: str,
    as_of: datetime | None = None,
    *,
    oversold: float = 30.0,
    overbought: float = 70.0,
    version: str = "v1",
) -> Assessment | None:
    """Judge momentum via RSI (delegated to MomentumAssessor)."""
    return MomentumAssessor(oversold, overbought, version).run(memory, subject, as_of)
