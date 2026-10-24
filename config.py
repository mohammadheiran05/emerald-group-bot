import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/group_bot.db").strip()
XP_PER_MESSAGE = max(1, int(os.getenv("XP_PER_MESSAGE", "10")))
XP_COOLDOWN_SECONDS = max(0, int(os.getenv("XP_COOLDOWN_SECONDS", "60")))
DEFAULT_ADMIN_LEVEL = min(100, max(1, int(os.getenv("ADMIN_LEVEL", "70"))))

try:
    OWNER_ID = int(OWNER_ID_RAW)
except (TypeError, ValueError):
    OWNER_ID = 0

def validate_config():
    errors = []
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        errors.append("BOT_TOKEN را در فایل .env وارد کن.")
    if OWNER_ID <= 0:
        errors.append("OWNER_ID باید شناسه عددی تلگرام خودت باشد.")
    return errors
