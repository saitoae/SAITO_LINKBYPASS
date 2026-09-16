# config.py
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS           = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x]
API_HOST            = os.getenv("API_HOST", "0.0.0.0")
API_PORT            = int(os.getenv("API_PORT", 8000))
API_BASE_URL        = os.getenv("API_BASE_URL", f"http://localhost:{API_PORT}")
TWOCAPTCHA_KEY      = os.getenv("TWOCAPTCHA_KEY", "")
WEBHOOK_URL         = os.getenv("WEBHOOK_URL", "")
WEBHOOK_MODE        = os.getenv("WEBHOOK_MODE", "false").lower() == "true"
RATE_LIMIT_PER_MIN  = int(os.getenv("RATE_LIMIT_PER_MIN", 30))
CACHE_TTL           = int(os.getenv("CACHE_TTL_SECONDS", 3600))
CACHE_MAX_SIZE      = int(os.getenv("CACHE_MAX_SIZE", 500))