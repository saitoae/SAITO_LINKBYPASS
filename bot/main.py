# bot/main.py
"""
Telegram Bot — full feature set:
  /start /help /bypass /batch /supported /stats /clear (admin) /about
  Inline mode
  Group mode (responds to URLs posted in groups)
  Batch: multi-URL from one message
  Rate limiting per user
"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

import httpx
from telegram import (
    Update, InlineQueryResultArticle,
    InputTextMessageContent, BotCommand,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    InlineQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode

from config import TELEGRAM_TOKEN, ADMIN_IDS, API_BASE_URL, WEBHOOK_URL, WEBHOOK_MODE
from bypasser.sites import SUPPORTED_SITES
from utils.cache import cache

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_BYPASS = f"{API_BASE_URL}/bypass"
API_BATCH  = f"{API_BASE_URL}/batch"
API_CACHE  = f"{API_BASE_URL}/cache/stats"

# Per-user rate limiting (10 req/min)
_user_buckets: dict[int, list[float]] = defaultdict(list)

def user_rate_ok(uid: int, limit: int = 10) -> bool:
    now = time.time()
    bucket = _user_buckets[uid]
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


# ── API calls ─────────────────────────────────────────────────────────────────

async def api_bypass(url: str) -> dict:
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.get(API_BYPASS, params={"url": url})
        return r.json()

async def api_batch(urls: list[str]) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(API_BATCH, json={"urls": urls, "max_concurrent": 3})
        return r.json()


# ── Formatters ────────────────────────────────────────────────────────────────

def fmt_single(data: dict) -> str:
    if not data.get("success"):
        strat = data.get("strategy", "?")
        return f"❌ *Bypass failed*\nStrategy tried: `{strat}`\nSite may require manual interaction."
    dest  = data["destination"]
    strat = data.get("strategy", "?")
    secs  = data.get("elapsed_seconds", "?")
    chain = data.get("redirect_chain", [])
    cached = " *(cached)*" if data.get("from_cache") else ""
    hops  = f"\n🔗 Hops: `{len(chain)}`" if len(chain) > 1 else ""
    return (
        f"✅ *Bypassed*{cached}\n\n"
        f"🎯 *Destination:*\n`{dest}`\n"
        f"⚙️ Strategy: `{strat}`\n"
        f"⏱ Time: `{secs}s`{hops}"
    )


def fmt_batch_results(results: list[dict]) -> str:
    lines = ["📋 *Batch Results*\n"]
    for i, r in enumerate(results, 1):
        orig = r.get("original_url", "?")[:40]
        if r.get("success"):
            dest = r.get("destination", "")[:60]
            lines.append(f"`{i}.` ✅ `{dest}`")
        else:
            lines.append(f"`{i}.` ❌ Failed — `{orig}...`")
    return "\n".join(lines)


def is_url(text: str) -> bool:
    t = text.strip()
    return t.startswith(("http://", "https://", "www."))


def extract_urls(text: str) -> list[str]:
    lines = [l.strip() for l in text.splitlines()]
    return [l for l in lines if is_url(l)]


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔓 *AllBypass Bot v3*\n\n"
        "Universal shortener & paywall bypass — 25+ sites supported.\n\n"
        "*Commands:*\n"
        "/bypass `<url>` — bypass a single link\n"
        "/batch — bypass multiple links (paste next)\n"
        "/supported — list all supported sites\n"
        "/stats — cache & performance stats\n"
        "/about — about this bot\n\n"
        "*Quick use:* just paste any URL directly.\n"
        "*Inline:* `@YourBot <url>` anywhere.\n"
        "*Group:* works in groups too — post a URL."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    count = len(SUPPORTED_SITES)
    await update.message.reply_text(
        f"*AllBypass Engine v3*\n\n"
        f"🌐 `{count}` sites with dedicated handlers\n"
        f"🛡 Cloudflare UAM + Bot Fight Mode bypass\n"
        f"🛡 DDoS-Guard bypass\n"
        f"🤖 hCaptcha / reCAPTCHA / Turnstile auto-solve\n"
        f"🎭 Full browser fingerprint spoofing\n"
        f"⚡ In-memory LRU cache (3600s TTL)\n"
        f"🔗 Redirect chain resolver\n"
        f"📡 Third-party: bypass.vip + bypass.city + bypass.pm",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_bypass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not user_rate_ok(uid):
        await update.message.reply_text("⏳ Slow down — 10 req/min limit.")
        return

    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /bypass <url>")
        return

    url = args[0]
    msg = await update.message.reply_text("⏳ Bypassing...")
    try:
        data = await api_bypass(url)
        await msg.edit_text(fmt_single(data), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_batch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["awaiting_batch"] = True
    await update.message.reply_text(
        "📋 Send your links now, one per line (max 10)."
    )


async def cmd_supported(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chunks = [SUPPORTED_SITES[i:i+10] for i in range(0, len(SUPPORTED_SITES), 10)]
    lines = [f"*Supported Sites ({len(SUPPORTED_SITES)}):*\n"]
    for chunk in chunks:
        lines.append(" · ".join(f"`{s}`" for s in chunk))
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(API_CACHE)
            data = r.json()
        text = (
            f"📊 *Cache Stats*\n\n"
            f"Size: `{data['size']}/{data['maxsize']}`\n"
            f"Hits: `{data['hits']}`\n"
            f"Misses: `{data['misses']}`\n"
            f"Hit rate: `{data['hit_rate']}%`\n"
            f"Total requests: `{data['total_requests']}`\n"
            f"TTL: `{data['ttl_seconds']}s`"
        )
    except Exception as e:
        text = f"❌ Stats error: `{e}`"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("🚫 Admin only.")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.delete(API_CACHE.replace("/stats", "/clear"), params={"admin_key": str(uid)})
        await update.message.reply_text("✅ Cache cleared.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid  = update.effective_user.id
    text = update.message.text.strip()

    # ── Batch mode ──────────────────────────────────────────
    if ctx.user_data.get("awaiting_batch"):
        ctx.user_data["awaiting_batch"] = False
        urls = extract_urls(text)[:10]
        if not urls:
            await update.message.reply_text("No URLs found in your message.")
            return
        if not user_rate_ok(uid, limit=5):
            await update.message.reply_text("⏳ Rate limit — wait a moment.")
            return
        msg = await update.message.reply_text(f"⏳ Processing {len(urls)} links...")
        try:
            data = await api_batch(urls)
            results = data.get("results", [])
            await msg.edit_text(fmt_batch_results(results), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await msg.edit_text(f"❌ Batch error: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # ── Single URL or multi-URL pasted ──────────────────────
    urls = extract_urls(text)

    if len(urls) > 1:
        # Treat as implicit batch
        ctx.user_data["awaiting_batch"] = False
        if not user_rate_ok(uid, limit=5):
            await update.message.reply_text("⏳ Rate limit.")
            return
        msg = await update.message.reply_text(f"⏳ Processing {len(urls[:10])} links...")
        try:
            data = await api_batch(urls[:10])
            results = data.get("results", [])
            await msg.edit_text(fmt_batch_results(results), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    if len(urls) == 1:
        if not user_rate_ok(uid):
            await update.message.reply_text("⏳ Slow down — 10 req/min.")
            return
        msg = await update.message.reply_text("⏳ Bypassing...")
        try:
            data = await api_bypass(urls[0])
            await msg.edit_text(fmt_single(data), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # Not a URL — ignore silently in groups, respond in DM
    if update.message.chat.type == "private":
        await update.message.reply_text("Send me a link to bypass.")


async def inline_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from uuid import uuid4
    query = update.inline_query.query.strip()
    if not is_url(query):
        return
    try:
        data = await api_bypass(query)
        text = fmt_single(data)
        dest = data.get("destination", "")
    except Exception as e:
        text = f"❌ Error: `{e}`"
        dest = ""

    results = [
        InlineQueryResultArticle(
            id=str(uuid4()),
            title="✅ Bypassed" if dest else "❌ Failed",
            description=dest[:100] if dest else "No destination found",
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode=ParseMode.MARKDOWN,
            ),
        )
    ]
    await update.inline_query.answer(results, cache_time=300)


# ── Launch ────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("about",     cmd_about))
    app.add_handler(CommandHandler("bypass",    cmd_bypass))
    app.add_handler(CommandHandler("batch",     cmd_batch))
    app.add_handler(CommandHandler("supported", cmd_supported))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(InlineQueryHandler(inline_handler))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message_handler,
    ))

    if WEBHOOK_MODE and WEBHOOK_URL:
        logger.info(f"Webhook mode: {WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=8443,
            webhook_url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Polling mode — 6767")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()