"""Shared analysis engine for the review entry points.

weekly_review.py and daily_review.py run the same load → fetch → score → decide → positioning
→ roles pipeline; they differ only at the edges (data freshness, breadth, and what they emit).
`run()` is that shared middle, returning one `AnalysisContext`; the three edges are parameters,
not caller branching:

  - force_refresh  : weekly uses cached bars (False); daily re-downloads to capture today's bar (True).
  - breadth        : "actionable" (held + watchlist recs) vs "full" (every name → the observation DB).
  - iv_hist_store  : when set, ATM-IV history from the store enables the IV-rank percentile.

pretrade.py is structurally different (live intraday quotes, per-CLI-symbol, no scan), so it shares
only the leaf helpers `load_inputs` / `book_math`, not `run`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from quant import (
    clock, decision, macro, market, observations, option_flow, options, portfolio, providers,
    roles, scoring, valuation,
)
from quant import sectors as sector_lens  # aliased: `sectors` is a local var below (symbol→GICS map)

if TYPE_CHECKING:
    import polars as pl

    from quant.models import (
        Fundamentals, Holding, MacroState, MarketState, OptionAnalysis, OptionPositioning,
        OptionStrategy, Recommendation, RoleView, SectorState, Signal,
    )


@dataclass(frozen=True)
class AnalysisContext:
    """Everything the shared pipeline produces — consumed by the report and the observation store."""
    cfg: dict
    watch: list[str]
    cash: float
    holdings: dict[str, Holding]
    strategies: list[OptionStrategy]
    history: dict[str, pl.DataFrame]          # includes "SPY"/"QQQ"
    vix: float
    sectors: dict[str, str]
    signals: dict[str, Signal]                # excludes SPY/QQQ
    spy: Signal
    qqq: Signal
    mkt: MarketState
    macro_state: MacroState
    sector_state: SectorState | None            # report-only ETF rotation lens (None when disabled)
    fundamentals: dict[str, Fundamentals]
    prices: dict[str, float]
    total_value: float
    weights: dict[str, float]
    cash_state: str
    cash_low: bool
    cash_frac: float
    deployable: float
    holding_recs: list[Recommendation]
    watchlist_recs: list[Recommendation]
    option_analyses: list[OptionAnalysis]
    positioning: dict[str, OptionPositioning]   # breadth-controlled
    roleviews: dict[str, RoleView]              # breadth-controlled
    summary: dict


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_inputs(config: str, portfolio_path: str, watchlist: str, options_path: str):
    """Read the per-profile YAML inputs. Shared by every entry point (incl. pretrade)."""
    cfg = _load_yaml(config)
    watch = _load_yaml(watchlist).get("symbols", [])
    cash, holdings = portfolio.load_portfolio(portfolio_path)
    strategies = options.load_options(options_path)
    return cfg, watch, cash, holdings, strategies


def book_math(cash: float, holdings: dict, prices: dict, cfg: dict):
    """Price the book → (total_value, weights, cash_state, cash_frac, deployable)."""
    total_value = portfolio.portfolio_value(cash, holdings, prices)
    weights = portfolio.current_weights(holdings, prices, total_value)
    cash_state = portfolio.cash_status(cash, total_value, cfg["cash_band"])
    cash_frac = cash / total_value if total_value else 0.0
    deployable = max(0.0, cash - cfg["cash_band"]["max"] * total_value)
    return total_value, weights, cash_state, cash_frac, deployable


def run(
    config: str, portfolio_path: str, watchlist: str, options_path: str, *,
    force_refresh: bool = False,
    breadth: str = "actionable",
    iv_hist_store: str | None = None,
    include_unconfigured: bool = False,
) -> AnalysisContext:
    """Run the shared pipeline once and return the full analysis context. See module docstring."""
    cfg, watch, cash, holdings, strategies = load_inputs(config, portfolio_path, watchlist, options_path)

    underlyings = {s.underlying for s in strategies}
    symbols = sorted(set(watch) | set(holdings) | underlyings)

    # Report-only sector/macro ETF map. Fetched + scored as context (like SPY/QQQ), never mixed into
    # `signals` — so it can't reach the decision engine or the observation DB, keeping the backtest fixed.
    sectors_cfg = cfg.get("sectors", {})
    etf_syms: list[str] = []
    if sectors_cfg.get("enabled"):
        etf_syms = sorted({s for group in (sectors_cfg.get("groups") or {}).values() for s in group})
    print(f"Fetching data for {len(symbols)} symbols + SPY/QQQ/VIX"
          f"{f' + {len(etf_syms)} sector ETFs' if etf_syms else ''} ...")

    data_cfg = cfg["data"]
    history = providers.fetch_history(
        symbols + ["SPY", "QQQ"] + etf_syms, data_cfg["period"], data_cfg["min_rows"],
        force_refresh=force_refresh,
    )
    vix = providers.fetch_vix(data_cfg["period"])
    sectors = providers.fetch_sectors(symbols)
    raw_fund = providers.fetch_fundamentals(symbols, cfg)

    context_only = {"SPY", "QQQ", *etf_syms}
    signals = {
        sym: scoring.build_signal(sym, df, cfg)
        for sym, df in history.items()
        if sym not in context_only
    }
    if "SPY" not in history or "QQQ" not in history:
        raise SystemExit("Could not fetch SPY/QQQ — cannot determine market regime.")
    spy = scoring.build_signal("SPY", history["SPY"], cfg)
    qqq = scoring.build_signal("QQQ", history["QQQ"], cfg)
    mkt = market.detect_market(spy, qqq, vix)
    macro_state = macro.detect_macro(providers.fetch_macro(cfg), cfg)  # report-only context
    sector_signals = {s: scoring.build_signal(s, history[s], cfg) for s in etf_syms if s in history}
    sector_state = sector_lens.detect_rotation(sector_signals, spy, history, cfg) if sector_signals else None

    fundamentals = {
        sym: valuation.build(sym, raw, signals[sym].price, cfg, stale=raw.get("_stale", False))
        for sym, raw in raw_fund.items()
        if raw and sym in signals
    }

    prices = {sym: s.price for sym, s in signals.items()}
    total_value, weights, cash_state, cash_frac, deployable = book_math(cash, holdings, prices, cfg)
    cash_low = cash_state == "low"

    holding_recs = []
    for sym, h in sorted(holdings.items()):
        if sym not in signals:
            continue
        holding_recs.append(
            decision.decide_holding(
                sig=signals[sym],
                holding=h,
                market=mkt,
                current_weight=weights.get(sym, 0.0),
                target_weight=decision.effective_target(sym, cfg),
                total_value=total_value,
                cfg=cfg,
                cash_low=cash_low,
            )
        )

    if cash_low:
        # At the cash floor: rotate out a laggard to fund the strongest candidate.
        watchlist_recs = decision.rotation(
            signals, set(holdings), weights, mkt, cfg, total_value, cash_low, sectors, history,
        )
    else:
        max_positions = cfg.get("lifecycle", {}).get("max_positions", 8)
        # Count only survivors: names flagged Close this run free their slot now.
        closing = {r.symbol for r in holding_recs if r.intent == "Close"}
        open_slots = max(0, max_positions - (len(holdings) - len(closing)))
        watchlist_recs = decision.scan_watchlist(
            signals, set(holdings), mkt, cfg, open_slots, total_value, sectors, history
        )
    decision.attach_strategy_hints(holding_recs, cfg["intent_strategy_map"])
    decision.attach_strategy_hints(watchlist_recs, cfg["intent_strategy_map"])

    summary = {
        "cash": cash,
        "total_value": total_value,
        "cash_frac": cash_frac,
        "cash_status": cash_state,
        "deployable": deployable,
    }
    if include_unconfigured:
        # Flag held / buy-recommended names with no hand-set target weight (riding the default).
        buy_intents = {"Add Core", "Increase Exposure"}
        configured = cfg.get("target_weights", {})
        default_weight = cfg.get("lifecycle", {}).get("entry_default_weight", 0.05)
        flagged = set(holdings)
        flagged |= {r.symbol for r in holding_recs + watchlist_recs if r.intent in buy_intents}
        unconfigured = sorted(s for s in flagged if s not in configured)
        if unconfigured:
            print(f"⚠️  {len(unconfigured)} symbol(s) using the default {default_weight:.0%} target "
                  f"(no target_weights entry): {', '.join(unconfigured)}")
            print("    → add an explicit weight in config.yaml: target_weights to size them intentionally.")
        summary["unconfigured_targets"] = unconfigured
        summary["default_weight"] = default_weight

    r = cfg.get("backtest", {}).get("costs", {}).get("cash_apy", 0.04)
    chains: dict[tuple[str, str], dict | None] = {}  # (underlying, expiry) -> IV map, memoized
    option_analyses = []
    for s in strategies:
        if s.underlying not in signals:
            print(f"  ! skipping option {s.id}: no price for {s.underlying}")
            continue
        ivs: dict[tuple[str, float, str], float] = {}
        for leg in s.legs:
            if leg.expiry is None:
                continue
            expiry = leg.expiry.isoformat()
            key = (s.underlying, expiry)
            if key not in chains:
                chains[key] = providers.fetch_option_chain(s.underlying, expiry)
                if chains[key] is None:
                    print(f"  ! no option chain for {s.underlying} {expiry} — Greeks unavailable")
            chain = chains[key]
            if chain and (leg.right, float(leg.strike)) in chain:
                ivs[(leg.right, float(leg.strike), expiry)] = chain[(leg.right, float(leg.strike))]
        option_analyses.append(
            options.analyze(s, signals[s.underlying].price, clock.today(), ivs, r)
        )

    # Option-chain positioning. breadth="full" covers every name (daily → the DB); "actionable"
    # covers only held + watchlist recs (weekly report). iv_hist (from the store) enables IV-rank.
    positioning = {}
    if cfg.get("option_positioning", {}).get("enabled", False):
        iv_hist = observations.atm_iv_history(iv_hist_store) if iv_hist_store else {}
        pos_syms = sorted(signals) if breadth == "full" else sorted(
            {r.symbol for r in holding_recs} | {r.symbol for r in watchlist_recs}
        )
        for sym in pos_syms:
            if sym not in signals or sym not in history:
                continue
            p = option_flow.analyze(sym, signals[sym].price, history[sym], cfg, iv_hist=iv_hist.get(sym))
            if p is not None:
                positioning[sym] = p
        print(f"  option positioning: {len(positioning)}/{len(pos_syms)} chains analysed")

    # Horizon roles (cheap, no I/O), same breadth as positioning.
    roleviews = {}
    if cfg.get("role_rules"):
        role_syms = signals if breadth == "full" else (
            {r.symbol for r in holding_recs} | {r.symbol for r in watchlist_recs}
        )
        for sym in role_syms:
            if sym in signals:
                roleviews[sym] = roles.build(sym, signals[sym], fundamentals.get(sym), cfg)
                if sym in holdings:
                    roleviews[sym].user_plan = holdings[sym].plan

    return AnalysisContext(
        cfg=cfg, watch=watch, cash=cash, holdings=holdings, strategies=strategies,
        history=history, vix=vix, sectors=sectors, signals=signals, spy=spy, qqq=qqq,
        mkt=mkt, macro_state=macro_state, sector_state=sector_state,
        fundamentals=fundamentals, prices=prices,
        total_value=total_value, weights=weights, cash_state=cash_state, cash_low=cash_low,
        cash_frac=cash_frac, deployable=deployable, holding_recs=holding_recs,
        watchlist_recs=watchlist_recs, option_analyses=option_analyses,
        positioning=positioning, roleviews=roleviews, summary=summary,
    )
