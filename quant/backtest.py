"""Strategy-replay backtester. Walk history week-by-week; at each week compute
signals as-of that date by slicing the frame, then run the live Signal / Market /
Decision / Portfolio logic and simulate trades. Output an equity curve plus
total return, CAGR and max drawdown, compared to SPY buy-and-hold.

Approximations — this engine produces discretionary *intents*, not sized orders,
so the simulation is deliberately coarse:
  * Add Core / Increase Exposure  -> buy toward the configured target weight.
  * Trim                          -> sell down to the target weight.
  * Close                         -> sell the whole position to zero.
  * Hedge / Generate Income / Hold-> options overlays, no equity effect here.
Trades fill at the week's close with no commissions or slippage, and a cash
floor (cash_band.min) is kept. Treat results as a sanity check on the rules, not
a P&L promise."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import polars as pl

from quant import decision, market, portfolio, scoring
from quant.models import Holding

WARMUP = 200  # trading days needed before the first signal (MA200 window)
STEP = 5      # rebalance cadence in trading days (~weekly)


@dataclass
class BacktestResult:
    dates: list[str] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    initial_value: float = 0.0
    final_value: float = 0.0
    total_return: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    spy_return: float = 0.0


def _as_of(df: pl.DataFrame, t: date) -> pl.DataFrame:
    return df.filter(pl.col("date") <= t)


def _price_as_of(df: pl.DataFrame, t: date) -> float | None:
    sub = _as_of(df, t)
    return float(sub["Close"].tail(1).item()) if sub.height else None


def _vix_as_of(vix: pl.DataFrame | None, t: date) -> float:
    if vix is None:
        return 20.0
    sub = _as_of(vix, t)
    return float(sub["Close"].tail(1).item()) if sub.height else 20.0


def _holdings(shares: dict[str, float]) -> dict[str, Holding]:
    return {
        s: Holding(symbol=s, core=q, trading=0.0, avg_cost=0.0)
        for s, q in shares.items()
        if q > 0
    }


def _execute(recs, shares, prices, total_value, cfg, cash, cash_band) -> float:
    """Apply each recommendation as a move toward its target weight. Returns cash."""
    floor = cash_band.get("min", 0.0) * total_value
    for r in recs:
        price = prices.get(r.symbol)
        if not price:
            continue
        if r.intent == "Close":
            qty = shares.get(r.symbol, 0.0)
            if qty > 0:
                cash += qty * price
                shares[r.symbol] = 0.0
            continue
        tw = decision.effective_target(r.symbol, cfg)
        if tw <= 0:
            continue
        target_val = tw * total_value
        cur_val = shares.get(r.symbol, 0.0) * price
        if r.intent in ("Add Core", "Increase Exposure"):
            # Honor the rec's own sizing when set (acceleration pyramids toward the
            # raised ceiling, above the base target); else fall back to base target.
            want = r.dollar_gap if r.dollar_gap is not None else (target_val - cur_val)
            buy = min(want, max(0.0, cash - floor))
            if buy > 0:
                shares[r.symbol] = shares.get(r.symbol, 0.0) + buy / price
                cash -= buy
        elif r.intent == "Trim":
            sell = cur_val - target_val
            if sell > 0:
                qty = min(shares.get(r.symbol, 0.0), sell / price)
                shares[r.symbol] -= qty
                cash += qty * price
    return cash


def run(
    history: dict[str, pl.DataFrame],
    vix_hist: pl.DataFrame | None,
    cfg: dict,
    initial_cash: float = 100_000.0,
) -> BacktestResult:
    """Replay the weekly strategy over `history`, starting all-cash (no lookahead)."""
    spy, qqq = history.get("SPY"), history.get("QQQ")
    if spy is None or qqq is None:
        raise SystemExit("Backtest needs SPY and QQQ history.")

    rebal_dates = spy["date"].to_list()[WARMUP::STEP]
    cash_band = cfg["cash_band"]
    max_positions = cfg.get("lifecycle", {}).get("max_positions", 7)

    cash = initial_cash
    shares: dict[str, float] = {}
    out_dates: list[str] = []
    equity_curve: list[float] = []
    spy_prices: list[float] = []

    for t in rebal_dates:
        spy_sub, qqq_sub = _as_of(spy, t), _as_of(qqq, t)
        if spy_sub.height < WARMUP or qqq_sub.height < WARMUP:
            continue

        prices = {
            sym: p for sym, df in history.items() if (p := _price_as_of(df, t)) is not None
        }

        holdings = _holdings(shares)
        total_value = portfolio.portfolio_value(cash, holdings, prices)
        weights = portfolio.current_weights(holdings, prices, total_value)
        cash_low = portfolio.cash_status(cash, total_value, cash_band) == "low"

        signals = {
            sym: scoring.build_signal(sym, sub, cfg)
            for sym, df in history.items()
            if sym not in ("SPY", "QQQ") and (sub := _as_of(df, t)).height >= WARMUP
        }
        spy_sig = scoring.build_signal("SPY", spy_sub, cfg)
        qqq_sig = scoring.build_signal("QQQ", qqq_sub, cfg)
        mkt = market.detect_market(spy_sig, qqq_sig, _vix_as_of(vix_hist, t))

        held = {sym for sym, qty in shares.items() if qty > 0}
        recs = [
            decision.decide_holding(
                sig=signals[sym],
                holding=Holding(symbol=sym, core=shares[sym], trading=0.0, avg_cost=0.0),
                market=mkt,
                current_weight=weights.get(sym, 0.0),
                target_weight=decision.effective_target(sym, cfg),
                total_value=total_value,
                cfg=cfg,
                cash_low=cash_low,
            )
            for sym in held
            if sym in signals
        ]
        open_slots = max(0, max_positions - len(held))
        recs += decision.scan_watchlist(signals, held, mkt, cfg, open_slots)

        cash = _execute(recs, shares, prices, total_value, cfg, cash, cash_band)

        equity = portfolio.portfolio_value(cash, _holdings(shares), prices)
        out_dates.append(t.isoformat())
        equity_curve.append(equity)
        spy_prices.append(prices.get("SPY", spy_prices[-1] if spy_prices else 0.0))

    return _summarize(out_dates, equity_curve, spy_prices, initial_cash)


def _summarize(dates, equity, spy_prices, initial_cash) -> BacktestResult:
    if not equity:
        raise SystemExit("Backtest produced no points — not enough history after warmup.")

    final = equity[-1]
    total_return = final / initial_cash - 1.0

    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    cagr = (final / initial_cash) ** (1 / years) - 1.0 if years > 0 else 0.0

    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)

    spy_return = spy_prices[-1] / spy_prices[0] - 1.0 if spy_prices and spy_prices[0] else 0.0

    return BacktestResult(
        dates=dates,
        equity=equity,
        initial_value=initial_cash,
        final_value=final,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        spy_return=spy_return,
    )
