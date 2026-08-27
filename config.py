import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

API_ID = int(os.getenv("API_ID", "26213385"))
API_HASH = os.getenv("API_HASH", "a9a801691183f645a881b154b3438222")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost")

DEV_USERNAME = os.getenv("DEV_USERNAME", "")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")
DB_PATH = os.path.join(BASE_DIR, "bot_data.db")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
GOOGLE_PUBSUB_TOPIC = os.getenv("GOOGLE_PUBSUB_TOPIC", "")
