"""Accumulate daily raw news-headline snapshots (per-ticker + global macro).

    uv run python scripts/snapshot_news.py            # active PROFILE's watchlist + holdings
    uv run python scripts/snapshot_news.py NVDA AVGO  # explicit tickers

yfinance serves only the CURRENT news window (no history), so we capture the raw headlines ourselves,
daily, to build an un-backfillable archive a future algorithm can re-mine (the derived coverage
metrics already land in the observation panel via quant/news.py). Two stores:

    data/news_snapshots/<SYMBOL>/<YYYY-MM-DD>.parquet   (per ticker)
    data/news_snapshots/_global/<YYYY-MM-DD>.parquet    (macro/world headlines)

Idempotent per (key, date): an already-captured key is skipped. Served from the same daily caches the
pipeline lens populated (providers.fetch_news_raw / fetch_global_news_cached) — at most one fetch/day.
Report-only.
"""
from __future__ import annotations

import os
import sys

import polars as pl
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant import clock, profiles, providers  # noqa: E402

STORE = os.path.join(ROOT, "data", "news_snapshots")

_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.Utf8, "scope": pl.Utf8,   # scope: "ticker" | "global"
    "title": pl.Utf8, "summary": pl.Utf8, "publisher": pl.Utf8, "link": pl.Utf8,
    "pub_date": pl.Utf8, "query": pl.Utf8, "as_of_date": pl.Utf8, "captured_at": pl.Utf8,
}


def _load_cfg() -> dict:
    config_path, _p, _w, _o, _out = profiles.resolve(ROOT)
    return yaml.safe_load(open(config_path)) or {}


def _universe() -> list[str]:
    _, portfolio, watchlist, _, _ = profiles.resolve(ROOT)
    watch = (yaml.safe_load(open(watchlist)) or {}).get("symbols", [])
    port = (yaml.safe_load(open(portfolio)) or {}).get("positions", {})
    return sorted(set(watch) | set(port))


def _write(sub: str, name: str, rows: list[dict]) -> str:
    out_dir = os.path.join(STORE, sub)
    out_path = os.path.join(out_dir, f"{name}.parquet")
    if os.path.exists(out_path):
        return "skip (already captured today)"
    if not rows:
        return "no headlines"
    os.makedirs(out_dir, exist_ok=True)
    norm = [{c: r.get(c) for c in _SCHEMA} for r in rows]
    pl.DataFrame(norm, schema=_SCHEMA).write_parquet(out_path)
    return f"ok — {len(rows)} headlines"


def _ticker_rows(sym: str, items: list[dict], today: str, ts: str) -> list[dict]:
    return [{"symbol": sym, "scope": "ticker", "title": h.get("title"), "summary": h.get("summary"),
             "publisher": h.get("publisher"), "link": h.get("link"), "pub_date": h.get("pub_date"),
             "query": None, "as_of_date": today, "captured_at": ts} for h in items]


def _global_rows(items: list[dict], today: str, ts: str) -> list[dict]:
    return [{"symbol": "_GLOBAL", "scope": "global", "title": h.get("title"), "summary": h.get("summary"),
             "publisher": h.get("publisher"), "link": h.get("link"), "pub_date": h.get("pub_date"),
             "query": h.get("query"), "as_of_date": today, "captured_at": ts} for h in items]


def snapshot(symbols: list[str], *, verbose: bool = True) -> tuple[int, int]:
    """Capture per-ticker headlines for `symbols` + the global macro headlines. Returns (per-ticker
    captured, total). Importable so daily_review.py can fold the raw archive into its post-close run."""
    tickers = [s.upper() for s in symbols]
    cfg = _load_cfg()
    today = clock.today().isoformat()
    ts = clock.timestamp()
    if verbose:
        print(f"Snapshotting news for {len(tickers)} symbols for {today} -> {STORE}")
    ok = 0
    for sym in tickers:
        raw = providers.fetch_news_raw(sym, cfg)
        status = "news lens disabled" if raw is None else _write(sym, today, _ticker_rows(sym, raw, today, ts))
        if status.startswith("ok"):
            ok += 1
        if verbose:
            print(f"  {sym:6} {status}")
    # Global macro headlines (one file per date).
    gstatus = _write("_global", today, _global_rows(providers.fetch_global_news_cached(cfg), today, ts))
    if verbose:
        print(f"  {'_global':6} {gstatus}")
    return ok, len(tickers)


def main() -> None:
    tickers = [a.upper() for a in sys.argv[1:]] or _universe()
    ok, total = snapshot(tickers)
    print(f"Done: {ok}/{total} per-ticker captured.")


if __name__ == "__main__":
    main()
