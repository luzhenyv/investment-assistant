"""Accumulate one comprehensive observation row per symbol into a growing parquet 'database'.

    data/daily_observations/<profile>/<bar_date>.parquet   # one file per session, one row/symbol

This is the point of the daily review: weekly_review/pretrade emit throwaway timestamped reports, but
here we persist a flat, wide time series — every indicator, score, option-positioning level, valuation
hint, role, AND the engine's decision (intent + reason + $gap) for each portfolio/watchlist name. Over
months it becomes a panel the user can mine and, crucially, grade: each row's `intent`/`state` is a
LABEL whose confidence can later be reviewed against forward returns (meta-labeling).

Data-management conventions mirror quant/cache.py and scripts/snapshot_options.py: per-period parquet
files discovered by glob, and an EXPLICIT column→dtype schema so every daily file is identical in shape
even when a column is all-null that day. That stability is what lets the whole history load + concat in
one line: `pl.read_parquet("data/daily_observations/<profile>/*.parquet")`. Files are keyed by the
session's `bar_date`; a re-run for the same session overwrites (last run wins; no duplicate rows).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
from typing import TYPE_CHECKING

import polars as pl

from quant import decision, indicators

if TYPE_CHECKING:
    from quant.pipeline import AnalysisContext

_F = pl.Float64
_S = pl.Utf8
_B = pl.Boolean
_I = pl.Int64

# Explicit schema = stable columns/dtypes across days (clean glob-concat). Order is the on-disk order;
# keep additive (append new columns at the end) so older files still read back.
SCHEMA: dict[str, pl.DataType] = {
    # identity / market context (create_time = run timestamp 'YYYY-MM-DD HH:MM:SS UTC'; bar_date below = session)
    "create_time": _S, "symbol": _S, "membership": _S,   # membership: holding | watchlist | underlying
    "regime": _S, "bull_score": _F, "vix": _F,
    # price / volume (incl. the abnormal-volume overlay)
    "price": _F, "day_change_pct": _F, "volume": _F, "rvol": _F, "vol_z": _F, "vol_state": _S,
    # technical indicators
    "ma20": _F, "ma50": _F, "ma200": _F, "rsi": _F, "atr": _F, "high_52w": _F, "low_52w": _F,
    # scores / asset state
    "trend_score": _F, "momentum_score": _F, "rs": _F, "state": _S,
    # valuation (Fundamentals; any may be null)
    "sector": _S, "pe": _F, "forward_pe": _F, "peg": _F, "pb": _F, "ev_ebitda": _F,
    "analyst_target": _F, "upside_to_target": _F, "valuation_label": _S, "beta": _F,
    # option positioning (OptionPositioning; null when the chain is thin / non-optionable)
    "put_wall": _F, "call_wall": _F, "max_pain": _F, "em": _F, "em_pct": _F,
    "pc_oi": _F, "pc_vol": _F, "atm_iv": _F, "iv_skew": _F, "reward": _F, "risk": _F, "rr_ratio": _F,
    # horizon role
    "role": _S, "suggested_role": _S, "horizon": _S, "tp_price": _F, "sl_price": _F,
    # the system decision (the gradeable label + its rationale)
    "intent": _S, "reason": _S, "dollar_gap": _F, "strategy_hint": _S,
    # --- decision provenance (appended; supervised-learning feature vector) ---
    # decision-context factors that actually GATE the intent (Add/Trim/Hold)
    "current_weight": _F, "target_weight": _F, "ceiling": _F, "pullback": _B, "breakout": _B,
    # position composition (null when the name isn't held)
    "shares": _F, "core": _F, "trading": _F, "avg_cost": _F,
    # book / market context (constant across a day's rows; kept inline for join-free ML)
    "cash": _F, "total_value": _F, "cash_frac": _F, "cash_status": _S, "cash_low": _B,
    "holdings_count": _I, "spy_trend": _F, "qqq_trend": _F,
    # fundamentals fill-out (the rest of the OVERVIEW block)
    "profit_margin": _F, "rev_growth": _F, "eps_growth": _F,
    # reproducibility: which code + which hyperparameter set produced this row
    "git_sha": _S, "config_hash": _S,
    # raw daily bar for human verification (which session + the day's OHLCV; close == price above)
    "bar_date": _S, "open": _F, "high": _F, "low": _F,
    # momentum/volatility indicators (appended; macd_hist gates Trend Acceleration, rest are soft)
    "macd": _F, "macd_signal": _F, "macd_hist": _F,
    "bb_bandwidth": _F, "bb_pct_b": _F, "bb_squeeze": _B, "macd_divergence": _S,
    # macro backdrop (FRED; report-only context, constant across a day's rows — see quant/macro.py)
    "dgs10": _F, "real_yield": _F, "hy_spread": _F, "nfci": _F, "macro_backdrop": _S,
    # extended option positioning (dealer gamma + IV percentile — see quant/option_flow.py)
    "gamma_flip": _F, "net_gex": _F, "iv_rank": _F,
    # cadence of the run that produced this row (appended last; null in pre-cadence files → "daily").
    # Daily runs the full universe; weekly appends its own snapshot — see record()/build_rows().
    "cadence": _S,
}


def git_sha(root: str) -> str | None:
    """Short HEAD SHA for run provenance; None if not a git checkout / git unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def day_change(df: pl.DataFrame) -> float | None:
    """Latest close vs the prior close, as a fraction (None if <2 bars)."""
    close = df["Close"]
    if close.len() < 2:
        return None
    prev = float(close.tail(2).head(1).item())
    return float(close.tail(1).item()) / prev - 1.0 if prev else None


def last_bar(df: pl.DataFrame) -> dict:
    """The latest daily bar (date + OHLCV) for human verification of the record."""
    last = df.tail(1)
    return {
        "bar_date": str(last["date"].item()),
        "open": round(float(last["Open"].item()), 2),
        "high": round(float(last["High"].item()), 2),
        "low": round(float(last["Low"].item()), 2),
        "close": round(float(last["Close"].item()), 2),
        "volume": round(float(last["Volume"].item())),
    }


def _prior_snapshot(store_dir: str, as_of_bar: str, cadence: str, value_col: str) -> dict:
    """Most recent prior same-cadence snapshot (before `as_of_bar`) → {symbol: value_col}. Empty on
    first run / no prior file / files predating `value_col`. Filters by the `cadence` column
    (pre-cadence files are treated as "daily") so weekly suffix files don't perturb daily detection,
    and vice versa."""
    frames = []
    for p in glob.glob(os.path.join(store_dir, "*.parquet")):
        try:
            df = pl.read_parquet(p, columns=["symbol", value_col, "bar_date", "cadence"])
        except Exception:  # noqa: BLE001 — pre-cadence file: read what's there, default cadence
            try:
                df = pl.read_parquet(p, columns=["symbol", value_col, "bar_date"]).with_columns(
                    pl.lit("daily").alias("cadence")
                )
            except Exception:  # noqa: BLE001 — file predates value_col entirely: skip it
                continue
        frames.append(df)
    if not frames:
        return {}
    df = pl.concat(frames, how="vertical_relaxed").with_columns(
        pl.col("cadence").fill_null("daily")
    ).filter((pl.col("cadence") == cadence) & (pl.col("bar_date") < as_of_bar))
    if df.height == 0:
        return {}
    last = df["bar_date"].max()
    df = df.filter(pl.col("bar_date") == last)
    return dict(zip(df["symbol"].to_list(), df[value_col].to_list()))


def prior_states(store_dir: str, as_of_bar: str, cadence: str = "daily") -> dict[str, str]:
    """Most recent prior same-cadence state per symbol (before `as_of_bar`), for detecting state
    flips. Empty dict on the first run / no prior file."""
    return _prior_snapshot(store_dir, as_of_bar, cadence, "state")


def prior_macd_hist(store_dir: str, as_of_bar: str, cadence: str = "daily") -> dict[str, float]:
    """Most recent prior same-cadence MACD histogram per symbol (before `as_of_bar`), for detecting
    golden/death crosses via the histogram sign flip. Empty dict on the first run / files predating
    the column."""
    return _prior_snapshot(store_dir, as_of_bar, cadence, "macd_hist")


def build_rows(ctx: AnalysisContext, *, cadence: str, prior_states: dict[str, str],
               git_sha: str | None, config_hash: str, generated_at: str,
               ohlcv: dict, prior_macd_hist: dict[str, float] | None = None,
               ) -> tuple[list[dict], list[dict]]:
    """Build one comprehensive observation row per symbol (the database) + the outliers list (the
    `daily-review` skill's entry). Identical schema regardless of cadence — `cadence` is stamped on
    every row. `prior_states` (same-cadence) drives the state-change outlier flag; pass {} to skip.
    `prior_macd_hist` (same-cadence) drives the MACD golden/death-cross flag; omit to skip."""
    prior_macd_hist = prior_macd_hist or {}
    cfg = ctx.cfg
    watch_set = set(ctx.watch)
    overbought = cfg["scoring"]["rsi_overbought"]
    oversold = cfg["scoring"]["rsi_oversold"]
    macro_levels = {sid: ctx.macro_state.series.get(sid, {}).get("level") for sid in ctx.macro_state.series}
    rec_by_sym = {r.symbol: r for r in ctx.holding_recs + ctx.watchlist_recs}
    holdings_count = len(ctx.holdings)

    rows, outliers = [], []
    for sym in sorted(ctx.signals):
        s = ctx.signals[sym]
        f = ctx.fundamentals.get(sym)
        p = ctx.positioning.get(sym)
        rv = ctx.roleviews.get(sym)
        rec = rec_by_sym.get(sym)
        h = ctx.holdings.get(sym)
        intent = rec.intent if rec else ""
        membership = "holding" if sym in ctx.holdings else "watchlist" if sym in watch_set else "underlying"
        target_weight = decision.effective_target(sym, cfg)
        rows.append({
            "create_time": generated_at, "symbol": sym, "membership": membership,
            "regime": ctx.mkt.regime, "bull_score": round(ctx.mkt.bull_score, 1), "vix": round(ctx.vix, 1),
            "price": round(s.price, 2), "day_change_pct": day_change(ctx.history[sym]),
            "volume": round(s.volume), "rvol": round(s.rvol, 2), "vol_z": round(s.vol_z, 2),
            "vol_state": s.vol_state,
            "ma20": round(s.ma20, 2), "ma50": round(s.ma50, 2), "ma200": round(s.ma200, 2),
            "rsi": round(s.rsi, 1), "atr": round(s.atr, 2),
            "high_52w": round(s.high_52w, 2), "low_52w": round(s.low_52w, 2),
            "trend_score": s.trend_score, "momentum_score": s.momentum_score, "rs": round(s.rs, 4),
            "state": s.state,
            "sector": f.sector if f else None, "pe": f.pe if f else None,
            "forward_pe": f.forward_pe if f else None, "peg": f.peg if f else None,
            "pb": f.pb if f else None, "ev_ebitda": f.ev_ebitda if f else None,
            "analyst_target": f.analyst_target if f else None,
            "upside_to_target": f.upside_to_target if f else None,
            "valuation_label": f.valuation_label if f else None, "beta": f.beta if f else None,
            "put_wall": p.put_wall if p else None, "call_wall": p.call_wall if p else None,
            "gamma_flip": p.gamma_flip if p else None, "net_gex": p.net_gex if p else None,
            "iv_rank": p.iv_rank if p else None,
            "max_pain": p.max_pain if p else None, "em": p.em if p else None,
            "em_pct": p.em_pct if p else None, "pc_oi": p.pc_oi if p else None,
            "pc_vol": p.pc_vol if p else None, "atm_iv": p.atm_iv if p else None,
            "iv_skew": p.iv_skew if p else None, "reward": p.reward if p else None,
            "risk": p.risk if p else None, "rr_ratio": p.rr_ratio if p else None,
            "role": rv.role if rv else None, "suggested_role": rv.suggested_role if rv else None,
            "horizon": rv.horizon if rv else None, "tp_price": rv.tp_price if rv else None,
            "sl_price": rv.sl_price if rv else None,
            "intent": intent, "reason": rec.reason if rec else "",
            "dollar_gap": rec.dollar_gap if rec else None,
            "strategy_hint": "; ".join(rec.strategy_hint) if rec and rec.strategy_hint else "",
            # decision-context factors that gate the intent
            "current_weight": round(ctx.weights.get(sym, 0.0), 4), "target_weight": round(target_weight, 4),
            "ceiling": round(decision.effective_ceiling(s.state, target_weight, cfg), 4),
            "pullback": s.pullback, "breakout": s.breakout,
            # position composition (null when not held)
            "shares": h.shares if h else None, "core": h.core if h else None,
            "trading": h.trading if h else None, "avg_cost": h.avg_cost if h else None,
            # book / market context (constant across the run's rows)
            "cash": round(ctx.cash), "total_value": round(ctx.total_value), "cash_frac": round(ctx.cash_frac, 4),
            "cash_status": ctx.cash_state, "cash_low": ctx.cash_low, "holdings_count": holdings_count,
            "spy_trend": ctx.spy.trend_score, "qqq_trend": ctx.qqq.trend_score,
            # macro backdrop (report-only context, constant across the run's rows)
            "dgs10": macro_levels.get("DGS10"), "real_yield": macro_levels.get("DFII10"),
            "hy_spread": macro_levels.get("BAMLH0A0HYM2"), "nfci": macro_levels.get("NFCI"),
            "macro_backdrop": ctx.macro_state.backdrop,
            # fundamentals fill-out
            "profit_margin": f.profit_margin if f else None,
            "rev_growth": f.rev_growth if f else None, "eps_growth": f.eps_growth if f else None,
            # reproducibility
            "git_sha": git_sha, "config_hash": config_hash,
            # raw daily bar for verification (close == price, volume == volume above)
            "bar_date": ohlcv[sym]["bar_date"], "open": ohlcv[sym]["open"],
            "high": ohlcv[sym]["high"], "low": ohlcv[sym]["low"],
            # momentum/volatility indicators
            "macd": round(s.macd, 3), "macd_signal": round(s.macd_signal, 3),
            "macd_hist": round(s.macd_hist, 3), "bb_bandwidth": round(s.bb_bandwidth, 4),
            "bb_pct_b": round(s.bb_pct_b, 3), "bb_squeeze": s.bb_squeeze,
            "macd_divergence": s.macd_divergence,
            # cadence of this run (daily | weekly)
            "cadence": cadence,
        })

        prev = prior_states.get(sym)
        flags = []
        if s.vol_state != "Normal":
            flags.append(f"{s.vol_state} volume")
        if prev and prev != s.state:
            flags.append("state change")
        if s.rsi >= overbought:
            flags.append("RSI overbought")
        elif s.rsi <= oversold:
            flags.append("RSI oversold")
        if s.bb_squeeze:
            flags.append("Bollinger squeeze (breakout pending)")
        if s.macd_divergence != "none":
            flags.append(f"{s.macd_divergence} MACD divergence")
        cross = indicators.macd_cross(prior_macd_hist.get(sym), s.macd_hist)
        if cross != "none":
            flags.append(f"MACD {cross} cross")
        if flags:
            outliers.append({
                "symbol": sym, "flags": flags, "day_change_pct": day_change(ctx.history[sym]),
                "rvol": round(s.rvol, 2), "vol_z": round(s.vol_z, 2), "vol_state": s.vol_state,
                "state": s.state, "prev_state": prev, "rsi": round(s.rsi, 1), "intent": intent,
                "macd_hist": round(s.macd_hist, 3), "bb_pct_b": round(s.bb_pct_b, 3),
                "macd_divergence": s.macd_divergence,
            })
    return rows, outliers


def record_run_meta(store_dir: str, bar_date: str, cfg: dict, git_sha: str | None,
                    generated_at: str, cadence: str = "daily") -> str:
    """Snapshot the hyperparameters in force at this run so any historical decision is reproducible.

    Writes <store_dir>/_runs/<bar_date>.json (daily) or <bar_date>__<cadence>.json (non-daily) =
    {bar_date, create_time, git_sha, config_hash, config} and returns a short `config_hash` of the
    resolved config. The hash is stable while the config is unchanged (easy grouping of 'which
    threshold set produced these decisions'), and the `_runs/` subdir is invisible to the
    `*.parquet` glob so the panel load is unaffected. Idempotent per session+cadence (overwrite)."""
    runs_dir = os.path.join(store_dir, "_runs")
    os.makedirs(runs_dir, exist_ok=True)
    canonical = json.dumps(cfg, sort_keys=True, default=str)
    config_hash = hashlib.sha1(canonical.encode()).hexdigest()[:12]
    payload = {"bar_date": bar_date, "create_time": generated_at, "git_sha": git_sha,
               "config_hash": config_hash, "config": cfg}
    suffix = "" if cadence == "daily" else f"__{cadence}"
    with open(os.path.join(runs_dir, f"{bar_date}{suffix}.json"), "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return config_hash


def atm_iv_history(store_dir: str, cadence: str = "daily") -> dict[str, list[float]]:
    """Per-symbol ATM-IV series across accumulated files of one `cadence`, in chronological
    (bar_date) order — feeds the IV-rank percentile in quant/option_flow.py. Filtered to a single
    cadence (default "daily", the full-universe series) so days with both a daily and a weekly file
    don't double-count. Empty dict when the store is empty or has no usable atm_iv column. Files
    missing the needed columns are skipped, not fatal; pre-cadence files are treated as "daily"."""
    frames = []
    for p in sorted(glob.glob(os.path.join(store_dir, "*.parquet"))):
        try:
            df = pl.read_parquet(p, columns=["symbol", "atm_iv", "bar_date", "cadence"])
        except Exception:  # noqa: BLE001 — pre-cadence or incompatible file
            try:
                df = pl.read_parquet(p, columns=["symbol", "atm_iv", "bar_date"]).with_columns(
                    pl.lit("daily").alias("cadence")
                )
            except Exception:  # noqa: BLE001 — an old file without these columns just doesn't contribute
                continue
        frames.append(df)
    if not frames:
        return {}
    df = pl.concat(frames, how="vertical_relaxed").with_columns(
        pl.col("cadence").fill_null("daily")
    ).filter(pl.col("cadence") == cadence).sort("bar_date")
    return {
        sym: [v for v in df.filter(pl.col("symbol") == sym)["atm_iv"].to_list() if v is not None]
        for sym in df["symbol"].unique().to_list()
    }


def record(store_dir: str, bar_date: str, rows: list[dict], cadence: str = "daily") -> str:
    """Write `rows` (one dict per symbol) under the fixed SCHEMA. Daily writes
    <store_dir>/<bar_date>.parquet; non-daily cadences get a `__<cadence>` filename suffix so they
    never overwrite the daily file for the same session.

    Idempotent per session+cadence: a re-run overwrites its own file (last run wins). Each row dict
    may omit keys → they land as null. Returns a short status string for the caller to print."""
    if not rows:
        return "no rows — nothing written"
    os.makedirs(store_dir, exist_ok=True)
    suffix = "" if cadence == "daily" else f"__{cadence}"
    out_path = os.path.join(store_dir, f"{bar_date}{suffix}.parquet")
    existed = os.path.exists(out_path)
    # Normalize every row to exactly the schema keys (missing → None) so the frame matches SCHEMA.
    norm = [{c: r.get(c) for c in SCHEMA} for r in rows]
    pl.DataFrame(norm, schema=SCHEMA).write_parquet(out_path)
    verb = "overwrote" if existed else "wrote"
    return f"{verb} {len(norm)} rows × {len(SCHEMA)} cols -> {out_path}"
