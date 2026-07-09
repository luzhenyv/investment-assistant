"""Accumulate daily Polymarket prediction-market odds snapshots.

    uv run python scripts/snapshot_prediction_markets.py

Crowd-implied event probabilities move continuously and are not served historically, so we capture
them daily to build an un-backfillable series (the derived backdrop already lands in the report via
quant/prediction_markets.py). One parquet per date, one row per market:

    data/prediction_markets/<YYYY-MM-DD>.parquet

Idempotent per date. Served from the same daily cache the pipeline lens populated
(providers.fetch_prediction_markets_cached). Report-only.
"""
from __future__ import annotations

import os
import sys

import polars as pl
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant import clock, profiles, providers  # noqa: E402

STORE = os.path.join(ROOT, "data", "prediction_markets")

_SCHEMA: dict[str, pl.DataType] = {
    "topic": pl.Utf8, "question": pl.Utf8, "outcome": pl.Utf8, "prob": pl.Float64,
    "volume": pl.Float64, "end_date": pl.Utf8, "week_change": pl.Float64,
    "as_of_date": pl.Utf8, "captured_at": pl.Utf8,
}


def _load_cfg() -> dict:
    config_path, _p, _w, _o, _out = profiles.resolve(ROOT)
    return yaml.safe_load(open(config_path)) or {}


def snapshot(*, verbose: bool = True) -> tuple[int, int]:
    """Capture the current forward-looking Polymarket odds to data/prediction_markets/<date>.parquet.
    Idempotent per date. Returns (rows_written, rows_written). Importable for daily_review.py."""
    cfg = _load_cfg()
    today = clock.today().isoformat()
    ts = clock.timestamp()
    out_path = os.path.join(STORE, f"{today}.parquet")
    if os.path.exists(out_path):
        if verbose:
            print(f"  prediction_markets skip (already captured {today})")
        return 0, 0
    markets = providers.fetch_prediction_markets_cached(cfg)
    if not markets:
        if verbose:
            print("  prediction_markets: none (disabled or unavailable)")
        return 0, 0
    rows = [{**{c: m.get(c) for c in ("topic", "question", "outcome", "prob", "volume",
                                      "end_date", "week_change")},
             "as_of_date": today, "captured_at": ts} for m in markets]
    os.makedirs(STORE, exist_ok=True)
    norm = [{c: r.get(c) for c in _SCHEMA} for r in rows]
    pl.DataFrame(norm, schema=_SCHEMA).write_parquet(out_path)
    if verbose:
        print(f"  prediction_markets ok — {len(rows)} markets -> {out_path}")
    return len(rows), len(rows)


def main() -> None:
    n, _ = snapshot()
    print(f"Done: {n} markets captured.")


if __name__ == "__main__":
    main()
