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

    @staticmethod
    def get_api_key_for_contest(contest_id):
        """
        Retrieve the API key for a given contest ID.
        Raises an exception if no API key is found.
        """
        api_key = Config.OIOIOI_API_KEYS.get(contest_id)
        if not api_key:
            message = (
                f"❌ No API key found for contest '{contest_id}'.\n"
                f"Please add the API key for this contest to the `.env` file.\n"
                f"Example:\n\n"
                f"OIOIOI_API_KEYS={{\n"
                f'    "{contest_id}": "your_api_key_here",\n'
                f"    ...\n"
                f"}}"
            )
            raise KeyError(message)
        return api_key