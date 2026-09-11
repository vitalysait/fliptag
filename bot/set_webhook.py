import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def get_token():
    if len(sys.argv) > 1 and sys.argv[1].startswith("TELEGRAM_TOKEN="):
        return sys.argv[1].split("=", 1)[1].strip()
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_TOKEN="):
                return line.split("=", 1)[1].strip()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("Токен не найден. Укажи: python bot/set_webhook.py https://… TELEGRAM_TOKEN=…")
    return token


def call(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Укажи URL: python bot/set_webhook.py https://your-app.vercel.app/api/bot [секрет]")
    url = sys.argv[1]
    secret = sys.argv[2] if len(sys.argv) > 2 else ""
    TOKEN = get_token()
    r = call("setWebhook", url=url, secret_token=secret or None, drop_pending_updates=True)
    print("setWebhook:", r.get("ok"), r.get("description", ""))
    try:
        info = call("getWebhookInfo")
        print("Webhook URL:", info["result"].get("url"))
        print("Проверка:", "OK" if info["result"].get("url") == url else "НЕ ОК!")
    except Exception as e:
        print("getWebhookInfo error:", e)