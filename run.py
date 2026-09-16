# run.py
import threading
import asyncio
import logging
import os
import sys

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def start_api():
    import uvicorn
    from api.main import app
    port = int(os.getenv("API_PORT", 10000))
    host = os.getenv("API_HOST", "0.0.0.0")
    logger.info(f"[API] starting on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        # no reload — single worker on Render free tier
    )


def start_bot():
    from bot.main import main as bot_main
    logger.info("[BOT] starting polling")
    bot_main()


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_TOKEN", "")
    if not token or token == "your_bot_token_from_botfather":
        logger.error(
            "[BOT] TELEGRAM_TOKEN not set. "
            "Go to Render Dashboard → Environment → add TELEGRAM_TOKEN"
        )
        # Still start API so Render's health check passes
        # Bot won't run without a token — don't crash the whole service
        start_api()
        sys.exit(0)

    # Start API in background thread
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()
    logger.info("[RUN] API thread launched")

    # Small delay so API is up before bot starts hitting it
    import time
    time.sleep(3)

    # Bot runs in main thread (required by PTB's signal handlers)
    start_bot()