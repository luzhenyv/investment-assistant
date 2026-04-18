"""
Central configuration. Edit this file to customise the system.
All secrets should be set via environment variables in production.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── Database ──────────────────────────────────────────────
DB_PATH = DATA_DIR / "trading.db"

# ── Price feed ────────────────────────────────────────────
# Swap this class path to switch data sources (e.g. AlphaVantage)
PRICE_FEED_BACKEND = "core.price_feed.YahooFeed"
OHLCV_HISTORY_YEARS = 5

# Watchlist: your ~50 stocks
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD", "NFLX", "PLTR",
    # Add the rest of your symbols here
]

# Macro instruments (Yahoo Finance tickers)
MACRO_SYMBOLS = {
    "SPX":   "^GSPC",
    "VIX":   "^VIX",
    "DXY":   "DX-Y.NYB",
    "OIL":   "CL=F",
    "GOLD":  "GC=F",
}

# ── Alert settings ────────────────────────────────────────
# Price must be inside zone to trigger alert (on open or close)
FLIP_THRESHOLD_PCT = 2.0   # % beyond zone edge to suggest a flip

# ── Telegram ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Scheduler ─────────────────────────────────────────────
# Times are ET (Eastern Time). Market closes 16:00 ET.
DAILY_JOB_TIME_ET = "16:30"   # run 30 min after close
