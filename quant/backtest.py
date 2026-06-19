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
Decisions are computed as-of a week's close, but trades fill at the next trading
day's open (the first session of the following week) — no same-bar execution.
Transaction costs (per_trade_bps) and cash
interest (cash_apy) are applied when configured under `backtest.costs`; a cash
floor (cash_band.min) is kept. Treat results as a sanity check on the rules, not
a P&L promise.

Survivorship / selection-bias caveat: the traded universe is the hand-picked
watchlist + current holdings, NOT a point-in-time, survivorship-free index. The
names were chosen with hindsight, so historical results are optimistic and not
repeatable on a fresh universe. Fixing this properly needs historical index
membership, which yfinance does not provide. The train/test split (backtest.
train_end) is a partial mitigation, not a cure for this bias."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from quant import decision, market, portfolio, scoring
from quant.models import Holding

WARMUP = 200  # trading days needed before the first signal (MA200 window)
STEP = 5      # rebalance cadence in trading days (~weekly)
PERIODS_PER_YEAR = 52  # equity curve is sampled ~weekly; annualize Sharpe by this


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
    sharpe: float = 0.0
    max_dd_duration: int = 0           # longest peak->recovery run, in weeks
    total_costs: float = 0.0           # cumulative transaction costs paid
    segments: dict = field(default_factory=dict)  # in_sample / out_of_sample metrics
    spy_prices: list[float] = field(default_factory=list)
    composition: list[dict[str, float]] = field(default_factory=list)


def _as_of(df: pl.DataFrame, t: date) -> pl.DataFrame:
    return df.filter(pl.col("date") <= t)


def _price_as_of(df: pl.DataFrame, t: date) -> float | None:
    sub = _as_of(df, t)
    return float(sub["Close"].tail(1).item()) if sub.height else None


def _open_as_of(df: pl.DataFrame, t: date) -> float | None:
    """Open of the first bar on/after t (the execution bar's open)."""
    sub = df.filter(pl.col("date") >= t)
    return float(sub["Open"].head(1).item()) if sub.height else None


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


def _execute(recs, shares, prices, total_value, cfg, cash, cash_band, acc=None) -> float:
    """Apply each recommendation as a move toward its target weight. Returns cash.

    Charges `backtest.costs.per_trade_bps` on every buy/Trim/Close (0 when unset);
    accumulates the charge into `acc["costs"]` when an accumulator dict is passed."""
    rate = cfg.get("backtest", {}).get("costs", {}).get("per_trade_bps", 0.0) / 1e4

    def charge(notional: float) -> float:
        cost = notional * rate
        if acc is not None:
            acc["costs"] += cost
        return cost

    floor = cash_band.get("min", 0.0) * total_value
    for r in recs:
        price = prices.get(r.symbol)
        if not price:
            continue
        if r.intent == "Close":
            qty = shares.get(r.symbol, 0.0)
            if qty > 0:
                proceeds = qty * price
                cash += proceeds - charge(proceeds)
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
                cash -= buy + charge(buy)
        elif r.intent == "Trim":
            # Honor the rec's own sizing when set (rotation trims one step); else
            # sell down to the base target. dollar_gap is signed (negative to trim).
            sell = -r.dollar_gap if r.dollar_gap is not None else (cur_val - target_val)
            if sell > 0:
                qty = min(shares.get(r.symbol, 0.0), sell / price)
                shares[r.symbol] -= qty
                proceeds = qty * price
                cash += proceeds - charge(proceeds)
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

    calendar = spy["date"].to_list()
    cal_pos = {d: i for i, d in enumerate(calendar)}
    rebal_dates = calendar[WARMUP::STEP]
    start = cfg.get("backtest", {}).get("start")
    if start:
        start_date = date.fromisoformat(start)
        rebal_dates = [d for d in rebal_dates if d >= start_date]
    cash_band = cfg["cash_band"]
    max_positions = cfg.get("lifecycle", {}).get("max_positions", 7)
    cash_apy = cfg.get("backtest", {}).get("costs", {}).get("cash_apy", 0.0)

    cash = initial_cash
    shares: dict[str, float] = {}
    out_dates: list[str] = []
    equity_curve: list[float] = []
    spy_prices: list[float] = []
    composition: list[dict[str, float]] = []
    acc = {"costs": 0.0}
    prev_date: date | None = None

    for t in rebal_dates:
        spy_sub, qqq_sub = _as_of(spy, t), _as_of(qqq, t)
        if spy_sub.height < WARMUP or qqq_sub.height < WARMUP:
            continue

        # Accrue interest on idle cash over the days since the last rebalance.
        if cash_apy and prev_date is not None:
            cash *= (1 + cash_apy) ** ((t - prev_date).days / 365.25)
        prev_date = t

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
        if cash_low:
            recs += decision.rotation(
                signals, held, weights, mkt, cfg, total_value, cash_low
            )
        else:
            open_slots = max(0, max_positions - len(held))
            # scan_watchlist may surface a shortlist beyond open slots (selection room for
            # the live report); only the top `open_slots` are buyable, so cap execution here
            # to keep max_positions intact.
            recs += decision.scan_watchlist(
                signals, held, mkt, cfg, open_slots, total_value
            )[:open_slots]

        # Fill on the next trading day's open — decisions are sized as-of the
        # close above, but orders can only execute at the following session.
        nxt = cal_pos[t] + 1
        if nxt >= len(calendar):
            break  # final decision bar has no next day to fill on; stop
        t_exec = calendar[nxt]
        exec_prices = {
            sym: p for sym, df in history.items() if (p := _open_as_of(df, t_exec)) is not None
        }

        cash = _execute(recs, shares, exec_prices, total_value, cfg, cash, cash_band, acc)

        equity = portfolio.portfolio_value(cash, _holdings(shares), exec_prices)
        out_dates.append(t_exec.isoformat())
        equity_curve.append(equity)
        spy_prices.append(exec_prices.get("SPY", spy_prices[-1] if spy_prices else 0.0))

        comp = {s: shares[s] * exec_prices[s] for s in shares if shares[s] > 0 and s in exec_prices}
        comp["Cash"] = cash
        composition.append(comp)

    return _summarize(
        out_dates, equity_curve, spy_prices, composition, initial_cash,
        total_costs=acc["costs"], cfg=cfg,
    )


def _max_dd_and_duration(equity) -> tuple[float, int]:
    """Max drawdown (fraction) and longest peak->recovery run (in sample periods)."""
    peak, max_dd, cur, longest = equity[0], 0.0, 0, 0
    for v in equity:
        if v >= peak:
            peak, cur = v, 0
        else:
            cur += 1
            longest = max(longest, cur)
        max_dd = max(max_dd, (peak - v) / peak)
    return max_dd, longest


def _sharpe(equity, rf_pp: float) -> float:
    """Annualized Sharpe from a return series; rf_pp is the per-period risk-free rate."""
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    if len(rets) < 2:
        return 0.0
    sd = statistics.pstdev(rets)
    if sd == 0:
        return 0.0
    excess = statistics.mean([r - rf_pp for r in rets])
    return math.sqrt(PERIODS_PER_YEAR) * excess / sd


def _segment_metrics(dates, equity, rf_pp: float) -> dict:
    """Return/CAGR/Sharpe/max-DD for one slice of the equity curve (segment-relative)."""
    start_v, final = equity[0], equity[-1]
    total_return = final / start_v - 1.0 if start_v else 0.0
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    cagr = (final / start_v) ** (1 / years) - 1.0 if years > 0 and start_v else 0.0
    max_dd, duration = _max_dd_and_duration(equity)
    return {
        "start": dates[0],
        "end": dates[-1],
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": _sharpe(equity, rf_pp),
        "max_drawdown": max_dd,
        "max_dd_duration": duration,
    }


def _summarize(dates, equity, spy_prices, composition, initial_cash,
               total_costs=0.0, cfg=None) -> BacktestResult:
    if not equity:
        raise SystemExit("Backtest produced no points — not enough history after warmup.")

    cfg = cfg or {}
    rf_pp = cfg.get("backtest", {}).get("costs", {}).get("cash_apy", 0.0) / PERIODS_PER_YEAR

    final = equity[-1]
    total_return = final / initial_cash - 1.0

    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    cagr = (final / initial_cash) ** (1 / years) - 1.0 if years > 0 else 0.0

    max_dd, max_dd_duration = _max_dd_and_duration(equity)
    sharpe = _sharpe(equity, rf_pp)
    spy_return = spy_prices[-1] / spy_prices[0] - 1.0 if spy_prices and spy_prices[0] else 0.0

    # Out-of-sample split: report the in-sample and out-of-sample segments separately.
    segments: dict = {}
    train_end = cfg.get("backtest", {}).get("train_end")
    if train_end:
        boundary = date.fromisoformat(train_end)
        split = next((i for i, d in enumerate(dates) if date.fromisoformat(d) >= boundary), None)
        if split is not None and split >= 2 and len(dates) - split >= 2:
            segments = {
                "in_sample": _segment_metrics(dates[:split], equity[:split], rf_pp),
                "out_of_sample": _segment_metrics(dates[split:], equity[split:], rf_pp),
            }

    return BacktestResult(
        dates=dates,
        equity=equity,
        initial_value=initial_cash,
        final_value=final,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        spy_return=spy_return,
        sharpe=sharpe,
        max_dd_duration=max_dd_duration,
        total_costs=total_costs,
        segments=segments,
        spy_prices=spy_prices,
        composition=composition,
    )
