"""Market-open Telegram kickoff job.

Runs at the start of the configured market session and sends a brief
watchlist snapshot. The job is safe to invoke from a timer because it
skips non-trading days.
"""

from __future__ import annotations

from investment_assistant.config import SETTINGS
from investment_assistant.core.watchlist import get_watchlist_symbols
from investment_assistant.core.zones import get_zones
from investment_assistant.database import init_db
from investment_assistant.infra.log import get_logger, setup_logging
from investment_assistant.infra.time import format_local, get_session_by_name, utc_now
from investment_assistant.notify.telegram_bot import send_message
from investment_assistant.services.prices import get_latest_close


setup_logging(SETTINGS.log_dir, SETTINGS.log_level, service="market-open")
log = get_logger(__name__)


def build_open_message(limit: int = 8) -> str:
    """Build a concise kickoff message from cached watchlist data."""
    symbols = get_watchlist_symbols(active_only=True)
    session = get_session_by_name(SETTINGS.market_session)
    local_now = format_local(utc_now(), SETTINGS.display_timezone, "%Y-%m-%d %H:%M %Z")

    header = [
        "*US Market Open*",
        f"Session: `{session.name}`",
        f"Time: `{local_now}`",
        "",
        "*Watchlist snapshot*",
    ]

    lines: list[str] = []
    for symbol in symbols[:limit]:
        price = get_latest_close(symbol)
        zones = get_zones(symbol)
        support_count = sum(1 for zone in zones if price is not None and zone.high < price)
        resistance_count = sum(1 for zone in zones if price is not None and zone.low > price)
        zone_count = len(zones)

        if price is None:
            lines.append(f"- `{symbol}` no cached close, active zones: {zone_count}")
            continue

        lines.append(
            f"- `{symbol}` ${price:,.2f} | zones: {zone_count} | "
            f"support below: {support_count} | resistance above: {resistance_count}"
        )

    remaining = len(symbols) - min(len(symbols), limit)
    if remaining > 0:
        lines.append(f"- ... and {remaining} more symbols")

    if not lines:
        lines.append("- Watchlist is empty")

    return "\n".join(header + lines)


def run() -> None:
    """Send the open message only on configured trading days."""
    init_db()
    session = get_session_by_name(SETTINGS.market_session)
    if not session.is_trading_day():
        log.info("Skipping market-open job because today is not a trading day.")
        return

    message = build_open_message()
    send_message(message)
    log.info("Sent market-open Telegram message.")


if __name__ == "__main__":
    run()