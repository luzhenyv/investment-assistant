"""
Telegram Bot — two modes:

1. PUSH (used by daily_job.py)
   send_message(text)  →  fire-and-forget async send

2. POLL (run this file directly)
   python notify/telegram_bot.py
   Listens for commands:

   /price AAPL          → latest close from local DB
   /zones AAPL          → list active zones for a symbol
   /flip <zone_id>      → confirm a flip suggestion
   /digest              → trigger today's digest on demand
   /help                → show available commands
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from investment_assistant.config import SETTINGS
from investment_assistant.infra.log import setup_logging, get_logger
from investment_assistant.services.prices import get_latest_close
from investment_assistant.core.zones import get_zones, flip_zone, get_zone_by_id
from investment_assistant.core.digest import build_digest

setup_logging(SETTINGS.log_dir, SETTINGS.log_level, service="telegram")
log = get_logger(__name__)


# ── Push (fire-and-forget) ─────────────────────────────────────────────────────

async def _send_async(text: str) -> None:
    if not SETTINGS.telegram_bot_token or not SETTINGS.telegram_chat_id:
        log.warning("Telegram credentials are not configured. Printing digest to terminal.")
        log.info("[telegram fallback]\n%s", text)
        return
    async with Bot(token=SETTINGS.telegram_bot_token) as bot:
        await bot.send_message(
            chat_id=SETTINGS.telegram_chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )


def send_message(text: str) -> None:
    """Sync wrapper — safe to call from scheduler or FastAPI handlers."""
    asyncio.run(_send_async(text))


def send_digest(message: str) -> None:
    send_message(message)


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Trading Assistant — Commands*\n\n"
        "`/price AAPL` — Show latest close from local cache\n"
        "`/zones AAPL` — List active zones for a symbol\n"
        "`/flip <zone_id>` — Confirm a zone flip\n"
        "`/digest` — Build and send today's digest now\n"
        "`/help` — Show this help\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: `/price AAPL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = ctx.args[0].upper()
    price = get_latest_close(symbol)
    if price is None:
        await update.message.reply_text(f"No cached data for {symbol}. Run a sync first.")
        return

    zones = get_zones(symbol)
    zone_info = ""
    for z in zones:
        if z.low <= price <= z.high:
            zone_info += f"\n🎯 In zone: ${z.low}–${z.high} ({z.strength})"
        elif price < z.low and (z.low - price) / price < 0.05:
            zone_info += f"\n📈 Near resistance: ${z.low}–${z.high} ({z.strength})"
        elif price > z.high and (price - z.high) / price < 0.05:
            zone_info += f"\n📉 Near support: ${z.low}–${z.high} ({z.strength})"

    text = f"*{symbol}*  Latest close: `${price:,.2f}`{zone_info}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_zones(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: `/zones AAPL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = ctx.args[0].upper()
    zones = get_zones(symbol)
    price = get_latest_close(symbol)

    if not zones:
        await update.message.reply_text(f"{symbol} has no active zones.")
        return

    lines = [f"*{symbol}* active zones (last: ${price:,.2f})\n" if price
             else f"*{symbol}* active zones\n"]

    for z in zones:
        if price:
            if z.low <= price <= z.high:
                pos = "🎯 in zone"
            elif price < z.low:
                pos = "↑ resistance"
            else:
                pos = "↓ support"
        else:
            pos = ""

        note = f" — {z.note}" if z.note else ""
        lines.append(
            f"`[{z.id}]` ${z.low}–${z.high} ({z.strength}) {pos}{note}"
        )

    lines.append("\n_Use /flip <zone\\_id> to confirm a flip_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_flip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: `/flip <zone_id>`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    zone_id = int(ctx.args[0])
    zone = get_zone_by_id(zone_id)
    if not zone:
        await update.message.reply_text(f"Zone id={zone_id} not found")
        return

    flip_zone(zone_id)
    await update.message.reply_text(
        f"✅ Flipped: *{zone.symbol}* ${zone.low}–${zone.high} ({zone.strength})\n"
        f"Note updated, zone remains active.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Building digest...")
    msg, _ = build_digest()
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ── Bot runner (polling mode) ──────────────────────────────────────────────────

def run_bot() -> None:
    setup_logging(SETTINGS.log_dir, SETTINGS.log_level, service="telegram")
    if not SETTINGS.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set. Export it and retry.")
        sys.exit(1)

    app = Application.builder().token(SETTINGS.telegram_bot_token).build()
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("price",  cmd_price))
    app.add_handler(CommandHandler("zones",  cmd_zones))
    app.add_handler(CommandHandler("flip",   cmd_flip))
    app.add_handler(CommandHandler("digest", cmd_digest))

    log.info("Telegram bot started. Send /help to your bot.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
