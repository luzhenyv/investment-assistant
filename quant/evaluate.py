"""Grade stored decisions against their realized forward returns (data-flywheel Phase 2).

The labelled panel (data/daily_observations/<profile>/*.parquet) captures, per symbol per session,
the engine's `state` read and its next-day `intent` — labels whose quality can only be judged once
the market has moved. This module joins each stored label to its N-**trading**-day forward close-to-
close return and scores it under a transparent rule, so the engine's edge (if any) becomes measurable
instead of asserted. See docs/DATA_FLYWHEEL.md.

Pure/testable: no IO except `load_panel`. The root `evaluate.py` wires this to price history + report.
"""
from __future__ import annotations

import glob
import os
from datetime import date

import polars as pl

# Intent → direction the engine is betting on. Directional intents only; options-income/hedge intents
# ("Generate Income", "Hedge") and empty/no-rule rows are left ungraded (grade → None).
LONG_INTENTS = {"Add Core", "Increase Exposure"}
REDUCE_INTENTS = {"Trim", "Close"}
HORIZONS = (5, 20, 60)
HOLD_BAND = 0.03  # a Hold is "right" if the name stayed within ±3% over the horizon


def load_panel(store_dir: str, cadence: str = "daily") -> pl.DataFrame:
    """Read the labelled panel across drifting schemas → the columns the evaluator grades on.

    Reads only the needed columns per file (dodges the extra-column schema error on a glob read) and
    treats pre-`cadence` files as daily — the same discipline as observations._prior_snapshot."""
    cols = ["symbol", "bar_date", "price", "intent", "state"]
    frames = []
    for p in glob.glob(os.path.join(store_dir, "*.parquet")):
        try:
            df = pl.read_parquet(p, columns=cols + ["cadence"])
        except Exception:  # noqa: BLE001 — pre-cadence file: read what's there, default daily
            try:
                df = pl.read_parquet(p, columns=cols).with_columns(pl.lit("daily").alias("cadence"))
            except Exception:  # noqa: BLE001 — file predates a graded column entirely: skip
                continue
        frames.append(df)
    if not frames:
        return pl.DataFrame({c: [] for c in cols + ["cadence"]})
    df = pl.concat(frames, how="vertical_relaxed").with_columns(pl.col("cadence").fill_null("daily"))
    return df.filter(pl.col("cadence") == cadence)


def forward_returns(bars: pl.DataFrame, bar_date: str,
                    horizons: tuple[int, ...] = HORIZONS) -> dict[int, float | None]:
    """{horizon: close[i+h]/close[i] - 1} where i is the position of `bar_date` in the symbol's
    date-sorted bars. Exact N *trading* days (positional), not calendar days. None when the session
    isn't in the frame or fewer than h forward bars exist yet (return still accumulating)."""
    bars = bars.sort("date")
    dates = bars["date"].to_list()
    close = bars["Close"].to_list()
    try:
        i = dates.index(date.fromisoformat(bar_date))
    except ValueError:
        return {h: None for h in horizons}
    n = len(close)
    return {
        h: (close[i + h] / close[i] - 1) if (i + h < n and close[i]) else None
        for h in horizons
    }


def grade(intent: str, fwd_ret: float | None, band: float = HOLD_BAND) -> bool | None:
    """Was the decision right? Long intents want a gain, reduce intents want the name to fall (drawdown
    avoided), Hold wants it to stay within `band`. None = ungraded (no forward return, or a non-
    directional/empty intent)."""
    if fwd_ret is None:
        return None
    if intent in LONG_INTENTS:
        return fwd_ret > 0
    if intent in REDUCE_INTENTS:
        return fwd_ret < 0
    if intent == "Hold":
        return abs(fwd_ret) <= band
    return None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def summarize(graded: list[dict], key: str,
              horizons: tuple[int, ...] = HORIZONS) -> tuple[list[dict], dict[int, float | None]]:
    """Group graded rows by `key` (e.g. "state" or "intent") → per-horizon stats, plus the universe
    base rate per horizon. Each graded row is {..., "fwd": {h: ret|None}, "hit": {h: bool|None}}.
    Stats per (group, horizon): n resolved returns, mean forward return, delta vs base, and — for
    directional groups — n graded and hit-rate."""
    base = {h: _mean([r["fwd"][h] for r in graded if r["fwd"][h] is not None]) for h in horizons}
    groups: dict[str, list[dict]] = {}
    for r in graded:
        groups.setdefault(r[key], []).append(r)
    out = []
    for g in sorted(groups, key=lambda k: (k is None, k)):
        items = groups[g]
        entry: dict = {"key": g if g else "—", "total": len(items)}
        for h in horizons:
            fwds = [it["fwd"][h] for it in items if it["fwd"][h] is not None]
            hits = [it["hit"][h] for it in items if it["hit"][h] is not None]
            mean = _mean(fwds)
            entry[h] = {
                "n": len(fwds),
                "mean": mean,
                "delta_base": (mean - base[h]) if (mean is not None and base[h] is not None) else None,
                "n_graded": len(hits),
                "hit_rate": (sum(hits) / len(hits)) if hits else None,
            }
        out.append(entry)
    return out, base
