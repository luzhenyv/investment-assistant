"""
Daily job — runs once after market close.

Sequence:
  1. Sync OHLCV for watchlist + macro symbols (incremental)
  2. Build digest (zone checks + macro snapshot)
  3. Send via Telegram

Run directly:  python scheduler/daily_job.py
Or via cron:   use ``next_run_utc()`` to compute the correct UTC time dynamically
               (handles DST automatically via market session config).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from investment_assistant.database import init_db
from investment_assistant.services.prices import sync_all, get_feed
from investment_assistant.core.digest import build_digest
from investment_assistant.infra.log import setup_logging, get_logger
from investment_assistant.notify.telegram_bot import send_digest
from investment_assistant.config import SETTINGS
from investment_assistant.infra.time import get_session_by_name

setup_logging(SETTINGS.log_dir, SETTINGS.log_level, service="scheduler")
log = get_logger(__name__)


def next_run_utc() -> str:
    """
    Return the next market close in UTC as an ISO string.
    Useful for external schedulers or display purposes.
    """
    session = get_session_by_name(SETTINGS.market_session)
    close = session.next_close_utc()
    return close.isoformat()


def run() -> None:
    log.info("=== Daily job started ===")
    init_db()

    # 1. Sync prices
    all_symbols = SETTINGS.watchlist + list(SETTINGS.macro_symbols.values())
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
