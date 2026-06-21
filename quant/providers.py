"""Market-data access. Thin wrapper over yfinance backed by a Parquet cache, so a
run survives a flaky download by reusing local data. Network I/O lives only here.

yfinance returns pandas; we convert to Polars at this boundary and everything
downstream is Polars. Canonical frame schema: date (Date) + OHLC columns."""
from __future__ import annotations

import json

import polars as pl
import yfinance as yf

from quant import cache

_SECTOR_CACHE = cache.CACHE_DIR / "sectors.json"


def _to_polars(pdf, columns: list[str]) -> pl.DataFrame:
    """yfinance pandas frame -> Polars frame with a tz-free `date` column."""
    pf = pl.from_pandas(pdf.reset_index())
    date_col = "Date" if "Date" in pf.columns else pf.columns[0]
    return (
        pf.rename({date_col: "date"})
        .with_columns(pl.col("date").cast(pl.Date))
        .select(["date", *columns])
        .drop_nulls()
    )


def _download_history(symbol: str, period: str) -> pl.DataFrame | None:
    pdf = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if pdf.empty:
        return None
    return _to_polars(pdf, ["Open", "High", "Low", "Close"])


def _download_vix(period: str) -> pl.DataFrame | None:
    pdf = yf.Ticker("^VIX").history(period=period)
    if pdf.empty:
        return None
    return _to_polars(pdf, ["Close"])


def fetch_history(
    symbols: list[str], period: str, min_rows: int
) -> dict[str, pl.DataFrame]:
    """Return {symbol: OHLC Polars frame}. Symbols with no usable data are skipped.

    `period` and `min_rows` come from the `data` section of config.yaml."""
    out: dict[str, pl.DataFrame] = {}
    for sym in symbols:
        df = cache.load_or_fetch(
            sym, lambda s=sym: _download_history(s, period), min_rows=min_rows
        )
        if df is None:
            print(f"  ! skipping {sym}: insufficient data")
            continue
        out[sym] = df
    return out


def fetch_option_chain(symbol: str, expiry: str) -> dict[tuple[str, float], float] | None:
    """Live implied volatility per contract for one expiry: {(right, strike): iv}.

    `expiry` is an ISO date string. Returns None when the expiry isn't listed or the
    download fails (caller degrades to no-Greeks). Deep-ITM / illiquid strikes report
    garbage IV from yfinance, so anything NaN or outside (0.01, 3.0) is dropped."""
    try:
        tk = yf.Ticker(symbol)
        if expiry not in tk.options:
            return None
        chain = tk.option_chain(expiry)
    except Exception:
        return None

    ivs: dict[tuple[str, float], float] = {}
    for right, frame in (("call", chain.calls), ("put", chain.puts)):
        for strike, iv in zip(frame["strike"], frame["impliedVolatility"]):
            iv = float(iv)
            if 0.01 < iv < 3.0:
                ivs[(right, float(strike))] = iv
    return ivs


def _download_sector(symbol: str) -> str | None:
    """The symbol's GICS-style sector from yfinance, or None if unavailable."""
    try:
        return yf.Ticker(symbol).info.get("sector") or None
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None


def _read_sector_cache() -> dict[str, str]:
    if _SECTOR_CACHE.exists():
        try:
            return json.loads(_SECTOR_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_cached_sectors(symbols: list[str]) -> dict[str, str]:
    """Read sectors from the on-disk cache only — no network. Used by the backtester
    so replays are reproducible and offline. Unknown/uncached symbols => "Unknown"."""
    cached = _read_sector_cache()
    return {s: cached.get(s, "Unknown") for s in symbols}


def fetch_sectors(symbols: list[str]) -> dict[str, str]:
    """Return {symbol: sector}, backed by a persistent JSON cache at
    `data/cache/sectors.json`. Sector is effectively static, so only symbols missing
    from the cache are fetched; successful lookups are persisted while failures fall
    back to "Unknown" for this run and retry next time (a transient outage never
    poisons the cache). The on-disk file lets the backtester read sectors without any
    network I/O, keeping replays reproducible."""
    cached = _read_sector_cache()
    fetched = {s: sec for s in symbols if s not in cached if (sec := _download_sector(s))}
    if fetched:
        cached.update(fetched)
        _SECTOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _SECTOR_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True))
    return {s: cached.get(s, "Unknown") for s in symbols}


def fetch_vix_history(period: str) -> pl.DataFrame | None:
    """Full VIX close history (cached) — used by the backtester for as-of lookups."""
    return cache.load_or_fetch("VIX", lambda: _download_vix(period), min_rows=1)


def fetch_vix(period: str) -> float:
    """Latest VIX close. Falls back to 20 (neutral) if unavailable."""
    df = fetch_vix_history(period)
    if df is None:
        print("  ! VIX unavailable, assuming 20")
        return 20.0
    return float(df["Close"].tail(1).item())
