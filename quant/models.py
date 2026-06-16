"""Plain data containers passed between modules."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MarketState:
    regime: str          # Panic | Correction | Neutral | Bull | Strong Bull
    bull_score: float    # 0-100
    notes: list[str] = field(default_factory=list)


@dataclass
class Signal:
    """Per-symbol technical snapshot + derived scores."""
    symbol: str
    price: float
    ma20: float
    ma50: float
    ma200: float
    rsi: float
    atr: float
    high_52w: float
    low_52w: float
    trend_score: float
    momentum_score: float
    pullback: bool
    breakout: bool
    state: str = "Range"   # asset state machine label (see scoring.asset_state)
    rs: float = 0.0        # relative strength: trailing return over rs_lookback


@dataclass
class Holding:
    symbol: str
    core: float
    trading: float
    avg_cost: float

    @property
    def shares(self) -> float:
        return self.core + self.trading


@dataclass
class Recommendation:
    symbol: str
    intent: str          # Add Core | Trim | Hold | Generate Income | Hedge | Increase Exposure | Close
    reason: str
    scores: dict = field(default_factory=dict)
    strategy_hint: list[str] = field(default_factory=list)
    dollar_gap: float | None = None   # signed $ to reach target weight (Add Core / Trim)
