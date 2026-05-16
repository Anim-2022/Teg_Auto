import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TARGET_URL = "https://www.gelsenkirchen.de/de/_meta/buergerservice/onlinedienste/terminvergabe_fuehrerscheinstelle.aspx"

# Direct iframe URL — bypass heavy city page, go straight to the booking form
DIRECT_URL = "https://tempus-termine.com/termine/index.php?anlagennr=14&anwendung=3"

# Check interval in seconds (default: 3 minutes)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "180"))

# Playwright
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
TIMEOUT = int(os.getenv("TIMEOUT", "30000"))

