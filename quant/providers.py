"""Market-data access. Thin wrapper over yfinance backed by a Parquet cache, so a
run survives a flaky download by reusing local data. Network I/O lives only here.

yfinance returns pandas; we convert to Polars at this boundary and everything
downstream is Polars. Canonical frame schema: date (Date) + OHLC columns."""
from __future__ import annotations

import polars as pl
import yfinance as yf

from quant import cache


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
