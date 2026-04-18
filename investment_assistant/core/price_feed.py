"""
Price feed layer.

Design: PriceFeed is an abstract interface. YahooFeed is the default
implementation. To add AlphaVantage, implement PriceFeed and point
PRICE_FEED_BACKEND in config.py at the new class — nothing else changes.
"""
from __future__ import annotations
import abc
from datetime import date, timedelta, datetime
from typing import Optional
import pandas as pd
import yfinance as yf

from investment_assistant.core.database import get_conn
from investment_assistant.config import SETTINGS


# ── Abstract interface ────────────────────────────────────────────────────────

class PriceFeed(abc.ABC):
    """Minimal contract every feed must satisfy."""

    @abc.abstractmethod
    def fetch_history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return OHLCV DataFrame with DatetimeIndex. Columns: open high low close volume."""

    @abc.abstractmethod
    def fetch_latest(self, symbol: str) -> Optional[dict]:
        """Return latest available OHLCV as a plain dict, or None on failure."""


# ── Yahoo Finance implementation ──────────────────────────────────────────────

class YahooFeed(PriceFeed):

    def fetch_history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index.date)           # strip timezone
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_latest(self, symbol: str) -> Optional[dict]:
        df = self.fetch_history(symbol, date.today() - timedelta(days=5), date.today())
        if df.empty:
            return None
        row = df.iloc[-1]
        return {
            "date":   df.index[-1].strftime("%Y-%m-%d"),
            "open":   round(float(row["open"]),  4),
            "high":   round(float(row["high"]),  4),
            "low":    round(float(row["low"]),   4),
            "close":  round(float(row["close"]), 4),
            "volume": int(row["volume"]),
        }


# ── OHLCV cache helpers (feed-agnostic) ───────────────────────────────────────

def get_feed() -> PriceFeed:
    """Instantiate the configured feed backend."""
    module_path, class_name = SETTINGS.price_feed_backend.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _last_stored_date(symbol: str) -> Optional[date]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM ohlcv WHERE symbol = ?", (symbol,)
        ).fetchone()
    val = row[0] if row else None
    return date.fromisoformat(val) if val else None


def _upsert_ohlcv(symbol: str, df: pd.DataFrame) -> int:
    """Write dataframe rows to DB. Returns number of rows written."""
    if df.empty:
        return 0
    rows = [
        (symbol, idx.strftime("%Y-%m-%d"),
         row["open"], row["high"], row["low"], row["close"], int(row["volume"]))
        for idx, row in df.iterrows()
    ]
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO ohlcv
               (symbol, date, open, high, low, close, volume)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def sync_symbol(symbol: str, feed: Optional[PriceFeed] = None) -> int:
    """
    Incremental sync for one symbol.
    - First run: pulls OHLCV_HISTORY_YEARS of history.
    - Subsequent runs: pulls only missing dates.
    Returns number of new rows written.
    """
    if feed is None:
        feed = get_feed()

    last = _last_stored_date(symbol)
    if last is None:
        start = date.today() - timedelta(days=365 * SETTINGS.ohlcv_history_years)
    else:
        start = last + timedelta(days=1)   # incremental

    end = date.today()
    if start > end:
        return 0   # already up to date

    df = feed.fetch_history(symbol, start, end)
    written = _upsert_ohlcv(symbol, df)
    if written:
        print(f"[feed] {symbol}: +{written} rows (up to {end})")
    return written


def sync_all(symbols: list[str], feed: Optional[PriceFeed] = None) -> None:
    """Sync a list of symbols (watchlist + macro) using one feed instance."""
    if feed is None:
        feed = get_feed()
    for sym in symbols:
        try:
            sync_symbol(sym, feed)
        except Exception as exc:
            print(f"[feed] ERROR {sym}: {exc}")


def get_ohlcv(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    Read cached OHLCV from DB. Used by the rest of the system —
    no network calls at alert/digest time.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date, open, high, low, close, volume
               FROM ohlcv WHERE symbol = ? AND date >= ?
               ORDER BY date""",
            (symbol, cutoff),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def get_latest_close(symbol: str) -> Optional[float]:
    """Quick lookup: most recent close price from local DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT close FROM ohlcv WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return float(row["close"]) if row else None


def get_latest_open(symbol: str) -> Optional[float]:
    """Quick lookup: most recent open price from local DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT open FROM ohlcv WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return float(row["open"]) if row else None


if __name__ == "__main__":
    # Quick smoke test
    from investment_assistant.config import SETTINGS
    from core.database import init_db
    init_db()
    feed = YahooFeed()
    sync_symbol("AAPL", feed)
    df = get_ohlcv("AAPL", days=10)
    print(df.tail())
