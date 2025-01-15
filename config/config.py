import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 10))
    REPO_PATH = os.getenv("REPO_PATH")
    PRIMARY_BRANCH = os.getenv("PRIMARY_BRANCH", "master")
    OIOIOI_BASE_URL = os.getenv("OIOIOI_BASE_URL")
    OIOIOI_USERNAME = os.getenv("OIOIOI_USERNAME")
    OIOIOI_PASSWORD = os.getenv("OIOIOI_PASSWORD")
    OIOIOI_API_KEYS = json.loads(os.getenv("OIOIOI_API_KEYS", "{}").replace('\n', '').replace('\r', ''))  # Parse contest-to-API-key mapping, removing newlines to allow multiline JSON
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS", "").split(",") # Load multiple chat IDs from .env
