"""
First-time setup: initialise DB, sync a small sample of symbols, verify everything works.
Run once:  python setup.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from investment_assistant.config import SETTINGS
from investment_assistant.infra.log import setup_logging, get_logger
from investment_assistant.database import init_db
from investment_assistant.services.prices import sync_symbol, get_ohlcv, get_latest_close, YahooFeed
from investment_assistant.core.zones import add_zone, get_zones
from investment_assistant.core.alerts import run_alert_check
from investment_assistant.core.digest import build_digest

setup_logging(SETTINGS.log_dir, SETTINGS.log_level, service="setup")
log = get_logger(__name__)

log.info("1. Initialising database...")
init_db()

log.info("2. Syncing sample symbols (AAPL, MSFT, ^GSPC, ^VIX)...")
feed = YahooFeed()
for sym in ["AAPL", "MSFT", "^GSPC", "^VIX"]:
    n = sync_symbol(sym, feed)
    price = get_latest_close(sym)
    log.info("%s: %d rows synced, latest close = %s", sym, n, price)

log.info("3. Adding sample zones for AAPL...")
if not get_zones("AAPL"):
    add_zone("AAPL", 170.0, 185.0, "strong", "长线支撑")
    add_zone("AAPL", 200.0, 215.0, "medium", "压力区")
zones = get_zones("AAPL")
log.info("%d zones: %s", len(zones), [(z.low, z.high, z.strength) for z in zones])

log.info("4. Running alert check for AAPL...")
price = get_latest_close("AAPL")
open_p = price * 0.998 if price else None
alerts = run_alert_check("AAPL", zones, open_p, price)
log.info("Alerts triggered: %d", len(alerts))
for a in alerts:
    log.info("%s $%.2f hit %s on %s", a.symbol, a.price, a.zone_label, a.trigger_type)

log.info("5. Building digest (no Telegram send)...")
msg, alerts = build_digest()
log.info("Digest preview:\n%s", msg[:600])

log.info("Setup complete. Run: uv run uvicorn investment_assistant.web.app:app --reload")
