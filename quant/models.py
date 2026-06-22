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
class OptionPositioning:
    """Option-chain positioning snapshot for one underlying (see quant/option_flow.py).
    Report-only hints from the free yfinance chain (EOD OI lags ~1 day; no flow direction;
    not backtestable). Any field may be None when the chain is thin."""
    symbol: str
    spot: float
    expiry: str                   # ISO date of the analysed monthly expiry
    dte: int                      # days to that expiry
    put_wall: float | None        # max put-OI strike (potential support)
    call_wall: float | None       # max call-OI strike (potential resistance)
    max_pain: float | None        # strike minimising total option-holder payout
    em: float | None              # expected move ($, ATM straddle)
    em_pct: float | None          # expected move as % of spot
    em_low: float | None          # spot - em
    em_high: float | None         # spot + em
    pc_oi: float | None           # put/call open-interest ratio (>1 = more puts)
    pc_vol: float | None          # put/call volume ratio (today's positioning)
    atm_iv: float | None          # at-the-money implied vol
    iv_skew: float | None         # OTM put IV - OTM call IV (positive = downside fear)
    reward: float | None          # (call_wall - spot)/spot, upside to resistance
    risk: float | None            # (spot - put_wall)/spot, downside to support
    rr_ratio: float | None        # reward / risk (the "赔率"; >=2 favourable)
    notes: list[str] = field(default_factory=list)  # confluence vs levels.py zones + reads


@dataclass
class RoleView:
    """Horizon role for one symbol + its take-profit / stop-loss discipline (see quant/roles.py).
    Report-only hint. `role` is the hand-set config role when present, else the suggested one —
    the point is to stop 'using long-term logic to make a short-term trade'."""
    symbol: str
    role: str                     # core | swing | momentum | avoid (the one in force)
    suggested_role: str           # what trend+RS+valuation imply
    source: str                   # "config" (hand-set) | "suggested" (no config entry)
    agree: bool                   # config role matches the suggestion
    horizon: str                  # human-readable hold horizon
    take_profit_pct: float | None # None for core (trim on thesis break, not a fixed target)
    stop_loss_pct: float | None
    tp_price: float | None        # take_profit_pct applied to current price
    sl_price: float | None
    playbook: list[str] = field(default_factory=list)  # how to express this role (options etc.)
    note: str = ""                # one-line rationale / mismatch warning


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
