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
import logging
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from investment_assistant.config import SETTINGS
from investment_assistant.core.price_feed import get_latest_close
from investment_assistant.core.zone_store import get_zones, flip_zone, get_zone_by_id
from investment_assistant.core.digest_builder import build_digest

log = logging.getLogger(__name__)


# ── Push (fire-and-forget) ─────────────────────────────────────────────────────

async def _send_async(text: str) -> None:
    if not SETTINGS.telegram_bot_token or not SETTINGS.telegram_chat_id:
        print("[telegram] No credentials — stdout:\n" + text)
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
        "*Trading Assistant — 可用指令*\n\n"
        "`/price AAPL` — 查询最新收盘价\n"
        "`/zones AAPL` — 列出该股所有活跃区间\n"
        "`/flip <zone_id>` — 确认翻转某个区间\n"
        "`/digest` — 立即生成今日复盘\n"
        "`/help` — 显示此帮助\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("用法: `/price AAPL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = ctx.args[0].upper()
    price = get_latest_close(symbol)
    if price is None:
        await update.message.reply_text(f"找不到 {symbol} 的数据，请先运行同步。")
        return

    zones = get_zones(symbol)
    zone_info = ""
    for z in zones:
        if z["low"] <= price <= z["high"]:
            zone_info += f"\n🎯 价格在区间内: ${z['low']}–${z['high']}（{z['strength']}）"
        elif price < z["low"] and (z["low"] - price) / price < 0.05:
            zone_info += f"\n📉 接近支撑: ${z['low']}–${z['high']}（{z['strength']}）"
        elif price > z["high"] and (price - z["high"]) / price < 0.05:
            zone_info += f"\n📈 接近压力: ${z['low']}–${z['high']}（{z['strength']}）"

    text = f"*{symbol}*  最新收盘: `${price:,.2f}`{zone_info}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_zones(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("用法: `/zones AAPL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = ctx.args[0].upper()
    zones = get_zones(symbol)
    price = get_latest_close(symbol)

    if not zones:
        await update.message.reply_text(f"{symbol} 暂无活跃区间。")
        return

    lines = [f"*{symbol}* 活跃区间 (当前: ${price:,.2f})\n" if price
             else f"*{symbol}* 活跃区间\n"]

    for z in zones:
        if price:
            if z["low"] <= price <= z["high"]:
                pos = "🎯 价格在内"
            elif price < z["low"]:
                pos = "↑ 支撑"
            else:
                pos = "↓ 压力"
        else:
            pos = ""

        note = f" — {z['note']}" if z.get("note") else ""
        lines.append(
            f"`[{z['id']}]` ${z['low']}–${z['high']} ({z['strength']}) {pos}{note}"
        )

    lines.append("\n_用 /flip <zone\\_id> 确认翻转_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_flip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("用法: `/flip <zone_id>`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    zone_id = int(ctx.args[0])
    zone = get_zone_by_id(zone_id)
    if not zone:
        await update.message.reply_text(f"找不到 zone id={zone_id}")
        return

    flip_zone(zone_id)
    await update.message.reply_text(
        f"✅ 已翻转: *{zone['symbol']}* ${zone['low']}–${zone['high']}（{zone['strength']}）\n"
        f"备注已更新，区间保持激活状态。",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ 生成复盘中...")
    msg, _ = build_digest()
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ── Bot runner (polling mode) ──────────────────────────────────────────────────

def run_bot() -> None:
    if not SETTINGS.telegram_bot_token:
        print("[telegram] TELEGRAM_BOT_TOKEN not set. Export it and retry.")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = Application.builder().token(SETTINGS.telegram_bot_token).build()
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("price",  cmd_price))
    app.add_handler(CommandHandler("zones",  cmd_zones))
    app.add_handler(CommandHandler("flip",   cmd_flip))
    app.add_handler(CommandHandler("digest", cmd_digest))

    print("[telegram] Bot started. Send /help to your bot.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
