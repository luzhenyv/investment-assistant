"""
Daily job — runs once after market close.

Sequence:
  1. Sync OHLCV for watchlist + macro symbols (incremental)
  2. Build digest (zone checks + macro snapshot)
  3. Send via Telegram

Run directly:  python scheduler/daily_job.py
Or via cron:   30 16 * * 1-5  cd /path/to/trading_assistant && python scheduler/daily_job.py
               (16:30 ET = 21:30 UTC on non-DST days — adjust for your timezone)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import logging
from datetime import datetime

from core.database import init_db
from core.price_feed import sync_all, get_feed
from core.digest_builder import build_digest
from investment_assistant.notify.telegram_bot import send_digest
from config import WATCHLIST, MACRO_SYMBOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run() -> None:
    log.info("=== Daily job started ===")
    init_db()

    # 1. Sync prices
    all_symbols = WATCHLIST + list(MACRO_SYMBOLS.values())
    feed = get_feed()
    log.info("Syncing %d symbols...", len(all_symbols))
    sync_all(all_symbols, feed)

    # 2. Build digest
    log.info("Building digest...")
    message, alerts = build_digest()
    log.info("Triggered alerts: %d", len(alerts))

    # 3. Send
    send_digest(message)
    log.info("=== Daily job done ===")


if __name__ == "__main__":
    run()
