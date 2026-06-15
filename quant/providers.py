"""Market-data access. Thin wrapper over yfinance so the source can be swapped
later (paid API) by replacing this one file. Network I/O lives only here."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

# Need >= 200 + 252 trading days for MA200 + 52w window; 2y is a safe margin.
_PERIOD = "2y"


def fetch_history(symbols: list[str], period: str = _PERIOD) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLC DataFrame}. Symbols with no data are skipped."""
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = yf.Ticker(sym).history(period=period, auto_adjust=True)
        if df.empty or len(df) < 200:
            print(f"  ! skipping {sym}: insufficient data ({len(df)} rows)")
            continue
        out[sym] = df[["Open", "High", "Low", "Close"]].dropna()
    return out


def fetch_vix(period: str = "1mo") -> float:
    """Latest VIX close. Falls back to 20 (neutral) if unavailable."""
    df = yf.Ticker("^VIX").history(period=period)
    if df.empty:
        print("  ! VIX unavailable, assuming 20")
        return 20.0
    return float(df["Close"].iloc[-1])
