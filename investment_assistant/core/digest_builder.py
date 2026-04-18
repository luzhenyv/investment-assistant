"""
Digest builder.

Assembles the end-of-day Telegram report:
  • Macro snapshot (SPX, VIX, DXY, OIL, GOLD)
  • Watchlist stocks that touched a zone today
  • Any flip suggestions
"""
from __future__ import annotations
from datetime import date
from core.price_feed import get_latest_close, get_latest_open
from core.zone_store import get_all_active_zones
from core.alert_engine import run_alert_check, Alert
from core.database import get_conn
from config import WATCHLIST, MACRO_SYMBOLS


def _macro_snapshot() -> str:
    lines = ["📊 *宏观市场*"]
    labels = {
        "SPX":  "S&P 500",
        "VIX":  "VIX",
        "DXY":  "美元指数",
        "OIL":  "原油",
        "GOLD": "黄金",
    }
    for key, ticker in MACRO_SYMBOLS.items():
        price = get_latest_close(ticker)
        label = labels.get(key, key)
        val = f"${price:,.2f}" if price else "N/A"
        lines.append(f"  {label}: {val}")
    return "\n".join(lines)


def _save_alert(alert: Alert) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO alerts (symbol, price, zone_id, trigger_type, flip_suggested, sent_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (alert.symbol, alert.price, alert.zone["id"],
             alert.trigger_type, int(alert.flip_suggested), alert.sent_at),
        )


def build_digest() -> tuple[str, list[Alert]]:
    """
    Returns (message_text, alerts_list).
    Caller decides where to send the message.
    """
    today = date.today().isoformat()
    all_zones = get_all_active_zones()
    triggered: list[Alert] = []

    for symbol in WATCHLIST:
        zones = all_zones.get(symbol, [])
        if not zones:
            continue
        open_px  = get_latest_open(symbol)
        close_px = get_latest_close(symbol)
        alerts   = run_alert_check(symbol, zones, open_px, close_px)
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
