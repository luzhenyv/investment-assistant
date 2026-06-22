"""Plain data containers passed between modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


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
class Zone:
    """A scored support/resistance price band (see quant/levels.py)."""
    low: float                  # band lower bound (price)
    high: float                 # band upper bound (price)
    score: float                # raw aggregated strength (pre-normalization)
    label: str                  # small | medium | strong | super-strong
    kind: str                   # support | resistance (relative to current price)
    touches: int                # total touch count across merged members
    methods: list[str] = field(default_factory=list)     # distinct sources, e.g. ["fib","swing","volume"]
    timeframes: list[str] = field(default_factory=list)  # ["weekly","daily"]
    members: int = 1            # candidates merged into this zone (confluence proxy)

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass
class Fundamentals:
    """Valuation/fundamentals snapshot from Alpha Vantage OVERVIEW (see quant/valuation.py).
    Report-only hints — never feeds scoring/decision. Any field may be None when the
    vendor omits it. Prices/levels are deliberately NOT taken from here (Signal owns those)."""
    symbol: str
    sector: str | None
    pe: float | None              # trailing GAAP P/E (can mislead for cyclicals)
    forward_pe: float | None      # forward P/E (fwd << trailing => earnings ramping)
    peg: float | None             # P/E-to-growth (the growth-adjusted read)
    pb: float | None              # price/book
    ev_ebitda: float | None
    profit_margin: float | None
    rev_growth: float | None      # quarterly revenue growth YoY
    eps_growth: float | None      # quarterly earnings growth YoY
    analyst_target: float | None  # consensus target price (lagging) — a coarse upper bound
    beta: float | None
    upside_to_target: float | None  # (analyst_target - price)/price
    valuation_label: str          # cheap (growth-justified) | fair | rich | unknown
    as_of: str                    # ISO date the OVERVIEW was fetched
    stale: bool = False           # served from a cache older than refresh_days


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


@dataclass
class OptionLeg:
    action: str          # long | short
    right: str           # call | put
    strike: float
    expiry: date
    contracts: int = 1
    premium: float | None = None   # per share, as paid/received at open


@dataclass
class OptionStrategy:
    id: str
    underlying: str
    type: str            # vertical | pmcc | ...
    legs: list[OptionLeg]
    opened: date | None = None
    net_debit: float | None = None         # per share (+ paid / - received); else computed
    credits_collected: float = 0.0         # per share, cumulative premium from prior rolls
    note: str = ""


@dataclass
class OptionAnalysis:
    """Underlying-based (intrinsic-only) snapshot of one option strategy."""
    id: str
    underlying: str
    type: str
    intent: str          # Roll short call | Expiring — close or roll | Close — near max profit | Hold
    reason: str
    metrics: dict = field(default_factory=dict)
    greeks: dict | None = None   # net position Greeks (Black-Scholes from live IV); None if IV unavailable
