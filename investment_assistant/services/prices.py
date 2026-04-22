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

from investment_assistant.infra.time import utc_today
import yfinance as yf
from sqlalchemy import func

from investment_assistant.database import get_session, OHLCV
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
        df = self.fetch_history(symbol, utc_today() - timedelta(days=5), utc_today())
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


def probe_yfinance_symbol(symbol: str) -> bool:
    """Return True when yfinance can fetch non-empty recent history for a symbol."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1mo", interval="1d", auto_adjust=True)
        return not df.empty
    except Exception:
        return False


# ── OHLCV cache helpers (feed-agnostic) ───────────────────────────────────────

def get_feed() -> PriceFeed:
    """Instantiate the configured feed backend."""
    module_path, class_name = SETTINGS.price_feed_backend.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _last_stored_date(symbol: str) -> Optional[date]:
    """Get the most recent cached date for a symbol using ORM."""
    with get_session() as session:
        row = session.query(func.max(OHLCV.date)).filter(
            OHLCV.symbol == symbol
        ).first()
    val = row[0] if row and row[0] else None
    return date.fromisoformat(val) if val else None


def _upsert_ohlcv(symbol: str, df: pd.DataFrame) -> int:
    """Write dataframe rows to DB using ORM. Returns number of rows written."""
    if df.empty:
        return 0
    
    with get_session() as session:
        written = 0
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            # Check if exists (upsert pattern)
            existing = session.query(OHLCV).filter(
                OHLCV.symbol == symbol,
                OHLCV.date == date_str
            ).first()
            
            if existing:
                existing.open = row["open"]
                existing.high = row["high"]
                existing.low = row["low"]
                existing.close = row["close"]
                existing.volume = int(row["volume"])
            else:
                ohlcv = OHLCV(
                    symbol=symbol,
                    date=date_str,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=int(row["volume"]),
                )
                session.add(ohlcv)
            written += 1
    
    return written


def sync_symbol(symbol: str, feed: Optional[PriceFeed] = None, fetch_symbol: Optional[str] = None) -> int:
    """
    Incremental sync for one symbol.
    - First run: pulls OHLCV_HISTORY_YEARS of history.
    - Subsequent runs: pulls only missing dates.
    Returns number of new rows written.
    """
    if feed is None:
        feed = get_feed()

    source_symbol = fetch_symbol or symbol

    last = _last_stored_date(symbol)
    if last is None:
        start = utc_today() - timedelta(days=365 * SETTINGS.ohlcv_history_years)
    else:
        start = last + timedelta(days=1)   # incremental

    end = utc_today()
    if start > end:
        return 0   # already up to date

    df = feed.fetch_history(source_symbol, start, end)
    written = _upsert_ohlcv(symbol, df)
    if written:
        if source_symbol == symbol:
            print(f"[feed] {symbol}: +{written} rows (up to {end})")
        else:
            print(f"[feed] {symbol} <= {source_symbol}: +{written} rows (up to {end})")
    return written


def sync_all(symbols: list[str] | list[tuple[str, str]], feed: Optional[PriceFeed] = None) -> None:
    """Sync canonical symbols with optional source-symbol mappings."""
    if feed is None:
        feed = get_feed()
    for entry in symbols:
        if isinstance(entry, tuple):
            sym, source_sym = entry
        else:
            sym, source_sym = entry, None
        try:
            sync_symbol(sym, feed, fetch_symbol=source_sym)
        except Exception as exc:
            print(f"[feed] ERROR {sym}: {exc}")


def get_ohlcv(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    Read cached OHLCV from DB using ORM. Used by the rest of the system —
    no network calls at alert/digest time.
    """
    cutoff = (utc_today() - timedelta(days=days)).isoformat()
    with get_session() as session:
        rows = session.query(OHLCV).filter(
            OHLCV.symbol == symbol,
            OHLCV.date >= cutoff
        ).order_by(OHLCV.date).all()
    
    if not rows:
        return pd.DataFrame()
    
    data = [
        {
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for r in rows
    ]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def get_latest_close(symbol: str) -> Optional[float]:
    """Quick lookup: most recent close price from local DB using ORM."""
    with get_session() as session:
        row = session.query(OHLCV).filter(
            OHLCV.symbol == symbol
        ).order_by(OHLCV.date.desc()).first()
    return float(row.close) if row else None


def get_latest_open(symbol: str) -> Optional[float]:
    """Quick lookup: most recent open price from local DB using ORM."""
    with get_session() as session:
        row = session.query(OHLCV).filter(
            OHLCV.symbol == symbol
        ).order_by(OHLCV.date.desc()).first()
    return float(row.open) if row else None


if __name__ == "__main__":
    # Quick smoke test
    from investment_assistant.database import init_db
    init_db()
    feed = YahooFeed()
    sync_symbol("AAPL", feed)
    df = get_ohlcv("AAPL", days=10)
    print(df.tail())

