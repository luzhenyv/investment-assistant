"""Accumulate daily raw social-sentiment snapshots (StockTwits + Reddit).

    uv run python scripts/snapshot_sentiment.py            # active PROFILE's watchlist + holdings
    uv run python scripts/snapshot_sentiment.py NVDA AVGO  # explicit tickers

StockTwits serves only the "most recent N" messages and Reddit's search is a 7-day rolling window —
neither can be backfilled, which is exactly why we capture the RAW messages ourselves, daily, so a
future algorithm can recompute any sentiment score from the original text (the derived numeric metrics
already land in the observation panel via quant/sentiment.py). Each run writes one parquet per symbol:

    data/sentiment_snapshots/<SYMBOL>/<YYYY-MM-DD>.parquet

Idempotent per (symbol, date): a symbol already captured today is skipped, so re-running is safe and a
missed day just leaves a gap. The fetch is served from the same daily cache the pipeline lens populated
(providers.fetch_sentiment_raw), so this hits the network at most once per symbol per day. Report-only.
"""
from __future__ import annotations

import os
import sys

import polars as pl
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant import clock, profiles, providers  # noqa: E402

STORE = os.path.join(ROOT, "data", "sentiment_snapshots")

# One row per raw message/post; nullable across sources (StockTwits carries sentiment/user/body,
# Reddit carries sub/title/selftext). Explicit schema keeps every file the same shape for glob-concat.
_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.Utf8, "source": pl.Utf8, "created_at": pl.Utf8,
    "sentiment": pl.Utf8, "user": pl.Utf8, "sub": pl.Utf8, "title": pl.Utf8, "body": pl.Utf8,
    "as_of_date": pl.Utf8, "captured_at": pl.Utf8,
}


def _load_cfg():
    config_path, _portfolio, _watchlist, _options, _out = profiles.resolve(ROOT)
    return yaml.safe_load(open(config_path)) or {}


def _universe() -> list[str]:
    """Default universe = active profile's watchlist + current holdings."""
    _, portfolio, watchlist, _, _ = profiles.resolve(ROOT)
    watch = (yaml.safe_load(open(watchlist)) or {}).get("symbols", [])
    port = (yaml.safe_load(open(portfolio)) or {}).get("positions", {})
    return sorted(set(watch) | set(port))


def _rows(sym: str, raw: dict, today: str, ts: str) -> list[dict]:
    rows = []
    for m in raw.get("stocktwits", []):
        rows.append({
            "symbol": sym, "source": "stocktwits", "created_at": m.get("created_at", ""),
            "sentiment": m.get("sentiment"), "user": m.get("user"), "sub": None, "title": None,
            "body": m.get("body", ""), "as_of_date": today, "captured_at": ts,
        })
    for p in raw.get("reddit", []):
        rows.append({
            "symbol": sym, "source": "reddit", "created_at": p.get("created_utc", ""),
            "sentiment": None, "user": None, "sub": p.get("sub"), "title": p.get("title", ""),
            "body": p.get("selftext", ""), "as_of_date": today, "captured_at": ts,
        })
    return rows


def _snapshot(sym: str, cfg: dict, today: str, ts: str) -> str:
    out_dir = os.path.join(STORE, sym)
    out_path = os.path.join(out_dir, f"{today}.parquet")
    if os.path.exists(out_path):
        return "skip (already captured today)"
    raw = providers.fetch_sentiment_raw(sym, cfg)
    if raw is None:
        return "sentiment lens disabled"
    rows = _rows(sym, raw, today, ts)
    if not rows:
        return "no messages"
    os.makedirs(out_dir, exist_ok=True)
    norm = [{c: r.get(c) for c in _SCHEMA} for r in rows]
    pl.DataFrame(norm, schema=_SCHEMA).write_parquet(out_path)
    n_st = sum(1 for r in rows if r["source"] == "stocktwits")
    n_rd = len(rows) - n_st
    return f"ok — {n_st} stocktwits, {n_rd} reddit"


def snapshot(symbols: list[str], *, verbose: bool = True) -> tuple[int, int]:
    """Capture raw social sentiment for `symbols` into data/sentiment_snapshots/<SYM>/<date>.parquet.

    Idempotent per (symbol, date). Returns (captured, total). Importable so daily_review.py can fold
    the raw archive into its post-close run (served from the same daily cache the lens populated)."""
    tickers = [s.upper() for s in symbols]
    cfg = _load_cfg()
    today = clock.today().isoformat()
    ts = clock.timestamp()
    if verbose:
        print(f"Snapshotting sentiment for {len(tickers)} symbols for {today} -> {STORE}")
    ok = 0
    for sym in tickers:
        status = _snapshot(sym, cfg, today, ts)
        if status.startswith("ok"):
            ok += 1
        if verbose:
            print(f"  {sym:6} {status}")
    return ok, len(tickers)


def main() -> None:
    tickers = [a.upper() for a in sys.argv[1:]] or _universe()
    ok, total = snapshot(tickers)
    print(f"Done: {ok}/{total} captured.")


if __name__ == "__main__":
    main()
