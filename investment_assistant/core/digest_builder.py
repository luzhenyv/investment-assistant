"""
Digest builder: assembles end-of-day Telegram reports using ORM objects.
Returns ORM objects directly, no dict conversion.
"""
from __future__ import annotations
from datetime import date, datetime

from investment_assistant.core.price_feed import get_latest_close, get_latest_open
from investment_assistant.core.zone_store import get_all_active_zones
from investment_assistant.core.alert_engine import run_alert_check, Alert
from investment_assistant.core.database import get_session, Alert as AlertModel
from investment_assistant.config import SETTINGS


def _macro_snapshot() -> str:
    lines = ["📊 *宏观市场*"]
    labels = {
        "SPX":  "S&P 500",
        "VIX":  "VIX",
        "DXY":  "美元指数",
        "OIL":  "原油",
        "GOLD": "黄金",
    }
    for key, ticker in SETTINGS.macro_symbols.items():
        price = get_latest_close(ticker)
        label = labels.get(key, key)
        val = f"${price:,.2f}" if price else "N/A"
        lines.append(f"  {label}: {val}")
    return "\n".join(lines)


def _save_alert(alert: Alert) -> AlertModel:
    """Persist an alert to the database. Returns the AlertModel ORM object."""
    # Convert ISO string to datetime object for SQLAlchemy DateTime type
    sent_at = datetime.fromisoformat(alert.sent_at.replace('Z', '+00:00')) if isinstance(alert.sent_at, str) else alert.sent_at
    
    with get_session() as session:
        db_alert = AlertModel(
            symbol=alert.symbol,
            price=alert.price,
            zone_id=alert.zone["id"],
            trigger_type=alert.trigger_type,
            flip_suggested=int(alert.flip_suggested),
            sent_at=sent_at,
        )
        session.add(db_alert)
        session.flush()
        alert_id = db_alert.id
    
    # Fetch and return the persisted object
    with get_session() as session:
        return session.query(AlertModel).filter(AlertModel.id == alert_id).first()


def build_digest() -> tuple[str, list[Alert]]:
    """
    Build end-of-day digest. Returns (message_text, list of Alert dataclass objects).
    Caller decides where to send the message.
    """
    today = date.today().isoformat()
    all_zones = get_all_active_zones()
    triggered: list[Alert] = []

    for symbol in SETTINGS.watchlist:
        zones = all_zones.get(symbol, [])
        if not zones:
            continue
        open_px  = get_latest_open(symbol)
        close_px = get_latest_close(symbol)
        
        # alert_engine returns Alert dataclass objects
        alerts = run_alert_check(symbol, zones, open_px, close_px)
        
        # Persist each alert and collect triggered
        for a in alerts:
            _save_alert(a)
        triggered.extend(alerts)

    # ── Build message ────────────────────────────────────────────────────────
    lines = [
        f"📅 *每日复盘 · {today}*",
        "",
        _macro_snapshot(),
        "",
    ]

    if triggered:
        lines.append("🎯 *触及区间*")
        for a in triggered:
            note = f" — {a.zone['note']}" if a.zone.get("note") else ""
            flip = "  ⚠️ 建议确认是否翻转" if a.flip_suggested else ""
            lines.append(
                f"  {a.direction_emoji} *{a.symbol}*  ${a.price:.2f}  "
                f"触及 {a.zone_label}{note}{flip}"
            )
    else:
        lines.append("✅ 今日无股票触及支撑/压力区")

    lines += ["", "─────────────────────"]

    return "\n".join(lines), triggered


def build_single_alert_message(alert: Alert) -> str:
    """Format a single alert for immediate Telegram delivery."""
    note = f"\n备注: {alert.zone['note']}" if alert.zone.get("note") else ""
    flip = "\n⚠️ 建议确认是否翻转" if alert.flip_suggested else ""
    return (
        f"{alert.direction_emoji} *{alert.symbol}*\n"
        f"{alert.trigger_type.capitalize()} 价格: ${alert.price:.2f}\n"
        f"区间: {alert.zone_label}{note}{flip}"
    )

