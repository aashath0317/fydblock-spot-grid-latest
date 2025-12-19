import os
from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent

# Database Config
DB_NAME = "grid_bot.db"
DB_PATH = BASE_DIR / "database" / DB_NAME
DB_URL = f"sqlite:///{DB_PATH}"

# Order Management
# CRITICAL: Strict prefix to identify bot orders vs manual orders
ORDER_PREFIX = "bot_"  # format: bot_{bot_id}_{nonce}

# Exchange Config (To be expanded)
# Default delays to prevent API bans
API_POLL_INTERVAL = 2  # seconds
MAX_API_RETRIES = 3

# Logging Config
LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)
