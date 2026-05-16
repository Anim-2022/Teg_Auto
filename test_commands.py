"""Send test commands to the bot via Telegram API."""
import json
import time
from urllib.request import urlopen, Request

TOKEN = "8709241237:AAFhHlgCBrYvT5-aBDWMvdtndufTvDh_nDE"
CHAT = "1069045889"
API = f"https://api.telegram.org/bot{TOKEN}"


def send(text):
    data = json.dumps({"chat_id": CHAT, "text": text}).encode()
    req = Request(f"{API}/sendMessage", data=data, headers={"Content-Type": "application/json"})
    r = json.loads(urlopen(req).read())
    return r["ok"]


commands = ["/start", "/status", "/info", "/check", "/logs"]

for cmd in commands:
    ok = send(cmd)
    print(f"{cmd} -> {'OK' if ok else 'FAIL'}")
    time.sleep(3)  # wait for bot to process

print("\nAll basic commands sent. Check Telegram for responses.")
print("Skipping /calendar test (takes ~15s), /stop, /monitor (affects state)")
