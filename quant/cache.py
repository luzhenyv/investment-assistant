"""Dead-simple Parquet cache for market data. One file per symbol named
`SYMBOL_START_END.parquet`, so a glance at `data/cache/` shows what's stored.

Policy (daily freshness):
  1. If today's cached file exists and is valid, reuse it — no download.
  2. Otherwise download; if the result is valid, cache and return it.
  3. If the download fails or is invalid, fall back to the newest valid cached
     file for that symbol (any age). This is the resilience the cache exists for.

"Valid" just means the frame has at least `min_rows` rows. If cached data does
not meet a caller's requirement, the caller asks for more rows / re-downloads."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

import polars as pl

from quant import clock

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def _safe(symbol: str) -> str:
    return symbol.replace("^", "").replace("/", "_")


def _files(symbol: str) -> list[Path]:
    return list(CACHE_DIR.glob(f"{_safe(symbol)}_*.parquet"))


def _newest(symbol: str) -> Path | None:
    files = _files(symbol)
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _written_today(path: Path) -> bool:
    # Compare in UTC (project convention) so cache freshness is identical regardless of run timezone.
    written = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).date()
    return written == clock.today()


def write_cache(symbol: str, df: pl.DataFrame) -> Path:
    """Persist `df`, replacing any older files for this symbol to avoid clutter."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for old in _files(symbol):
        old.unlink()
    start = str(df["date"].min())[:10]
    end = str(df["date"].max())[:10]
    path = CACHE_DIR / f"{_safe(symbol)}_{start}_{end}.parquet"
    df.write_parquet(path)
    return path


def load_or_fetch(
    symbol: str,
    fetch: Callable[[], pl.DataFrame | None],
    min_rows: int = 200,
    force_refresh: bool = False,
) -> pl.DataFrame | None:
    """Return a cached-or-freshly-downloaded frame, or None if nothing is usable.

    `force_refresh=True` skips the reuse-if-written-today shortcut and always attempts a fresh
    download (the daily review needs today's bar even if an earlier run cached a stale file today).
    The download-failure fallback to the newest valid cache is preserved either way."""

    def valid(df: pl.DataFrame | None) -> bool:
        return df is not None and df.height >= min_rows

    newest = _newest(symbol)
    if not force_refresh and newest is not None and _written_today(newest):
        cached = pl.read_parquet(newest)
        if valid(cached):
            return cached

    try:
        fresh = fetch()
    except Exception as exc:  # noqa: BLE001 — network/parse failures are expected
        print(f"  ! download failed for {symbol}: {exc}")
        fresh = None

    if valid(fresh):
        write_cache(symbol, fresh)
        return fresh

    # Download unavailable/invalid — fall back to the newest valid cache.
    for path in sorted(_files(symbol), key=lambda p: p.stat().st_mtime, reverse=True):
        cached = pl.read_parquet(path)
        if valid(cached):
            print(f"  ~ reusing cached {symbol} ({path.name}) — download unavailable")
            return cached
    return None
