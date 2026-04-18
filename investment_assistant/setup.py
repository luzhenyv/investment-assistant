"""
First-time setup: initialise DB, sync a small sample of symbols, verify everything works.
Run once:  python setup.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from investment_assistant.core.database import init_db
from investment_assistant.core.price_feed import sync_symbol, get_ohlcv, get_latest_close, YahooFeed
from investment_assistant.core.zone_store import add_zone, get_zones
from investment_assistant.core.alert_engine import run_alert_check
from investment_assistant.core.digest_builder import build_digest

print("1. Initialising database...")
init_db()

print("\n2. Syncing sample symbols (AAPL, MSFT, ^GSPC, ^VIX)...")
feed = YahooFeed()
for sym in ["AAPL", "MSFT", "^GSPC", "^VIX"]:
    n = sync_symbol(sym, feed)
    price = get_latest_close(sym)
    print(f"   {sym}: {n} rows synced, latest close = {price}")

print("\n3. Adding sample zones for AAPL...")
if not get_zones("AAPL"):
    add_zone("AAPL", 170.0, 185.0, "强", "长线支撑")
    add_zone("AAPL", 200.0, 215.0, "中", "压力区")
zones = get_zones("AAPL")
print(f"   {len(zones)} zones: {[(z.low, z.high, z.strength) for z in zones]}")

print("\n4. Running alert check for AAPL...")
price = get_latest_close("AAPL")
open_p = price * 0.998 if price else None
alerts = run_alert_check("AAPL", zones, open_p, price)
print(f"   Alerts triggered: {len(alerts)}")
for a in alerts:
    print(f"   → {a.symbol} ${a.price:.2f} hit {a.zone_label} on {a.trigger_type}")

print("\n5. Building digest (no Telegram send)...")
msg, alerts = build_digest()
print(msg[:600])

print("\n✅ Setup complete. Run the web interface with:  uv run uvicorn investment_assistant.web.app:app --reload")
