import os
from dotenv import load_dotenv
from datetime import timedelta

# Load environment variables from .env file
load_dotenv()


class Config:
    CHECK_INTERVAL = 10
    BACKOFF_TIME = timedelta(minutes=10)
    OIOIOI_BASE_URL = "https://algeng.inet.tu-berlin.de"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
