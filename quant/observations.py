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

import hashlib
import json
import os

import polars as pl

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
}


def record_run_meta(store_dir: str, bar_date: str, cfg: dict, git_sha: str | None,
                    generated_at: str) -> str:
    """Snapshot the hyperparameters in force at this run so any historical decision is reproducible.

    Writes <store_dir>/_runs/<bar_date>.json = {bar_date, create_time, git_sha, config_hash,
    config} and returns a short `config_hash` of the resolved config. The hash is stable while the
    config is unchanged (easy grouping of 'which threshold set produced these decisions'), and the
    `_runs/` subdir is invisible to the `*.parquet` glob so the panel load is unaffected. Idempotent
    per session (overwrite)."""
    runs_dir = os.path.join(store_dir, "_runs")
    os.makedirs(runs_dir, exist_ok=True)
    canonical = json.dumps(cfg, sort_keys=True, default=str)
    config_hash = hashlib.sha1(canonical.encode()).hexdigest()[:12]
    payload = {"bar_date": bar_date, "create_time": generated_at, "git_sha": git_sha,
               "config_hash": config_hash, "config": cfg}
    with open(os.path.join(runs_dir, f"{bar_date}.json"), "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return config_hash


def record(store_dir: str, bar_date: str, rows: list[dict]) -> str:
    """Write `rows` (one dict per symbol) to <store_dir>/<bar_date>.parquet under the fixed SCHEMA.

    Idempotent per session: a re-run for the same session overwrites the file (last run wins). Each row
    dict may omit keys → they land as null. Returns a short status string for the caller to print."""
    if not rows:
        return "no rows — nothing written"
    os.makedirs(store_dir, exist_ok=True)
    out_path = os.path.join(store_dir, f"{bar_date}.parquet")
    existed = os.path.exists(out_path)
    # Normalize every row to exactly the schema keys (missing → None) so the frame matches SCHEMA.
    norm = [{c: r.get(c) for c in SCHEMA} for r in rows]
    pl.DataFrame(norm, schema=SCHEMA).write_parquet(out_path)
    verb = "overwrote" if existed else "wrote"
    return f"{verb} {len(norm)} rows × {len(SCHEMA)} cols -> {out_path}"
