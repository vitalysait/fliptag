import json
import mimetypes
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
CONFIG_PATH = BASE_DIR / "config.json"


def load_token():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_TOKEN="):
                return line.split("=", 1)[1].strip()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("Токен не найден. Положи его в bot/.env как TELEGRAM_TOKEN=...")
    return token


def api(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def send(chat_id, text):
    try:
        api("sendMessage", chat_id=chat_id, text=text)
    except Exception as e:
        print("send error:", e)


def download(file_path, dest):
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data)
    return data


def ext_for(mime, fname, kind):
    if fname and "." in fname:
        return Path(fname).suffix.lower() or (".jpg" if kind == "image" else ".mp3")
    if mime:
        exts = {
            "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
            "audio/wav": ".wav", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a", "audio/flac": ".flac", "audio/aac": ".aac",
        }
        if mime in exts:
            return exts[mime]
    return ".jpg" if kind == "image" else ".mp3"


def git(action, *args):
    return subprocess.run(
        ["git", action, *args],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def push_changes(message):
    git("add", "-A")
    if git("status", "--porcelain").stdout.strip():
        c = git("commit", "-m", message)
        if c.returncode != 0:
            send(CHAT, f"Commit failed:\n{c.stderr[-500:]}")
            return False
    git("pull", "--rebase")
    p = git("push")
    if p.returncode != 0:
        send(CHAT, f"Push failed (нужна авторизация git?):\n{p.stderr[-400:]}")
        return False
    return True


def read_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"image": "", "sound": ""}


def write_config(cfg):
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cfg = ""  # noqa


def store_file(kind, data, mime, fname):
    ASSETS_DIR.mkdir(exist_ok=True)
    ext = ext_for(mime, fname, kind)
    name = f"{kind}_{int(time.time() * 1000)}{ext}"
    dest = ASSETS_DIR / name
    dest.write_bytes(data)
    return f"assets/{name}"


def save_and_publish(chat_id, kind, data, mime, fname):
    rel = store_file(kind, data, mime, fname)
    cfg = read_config()
    cfg[kind] = rel
    write_config(cfg)
    ok = push_changes(f"update {kind}: {rel}")
    if ok:
        send(chat_id, f"✅ {kind} обновлён → {rel}\nСайт обновится сам через ~1 минуту.")
    return rel


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    if text == "/start" or text == "/help":
        send(chat_id,
             "Привет! Отправь мне:\n"
             "🖼 фото → заменит картинку на сайте\n"
             "🎵 аудио/голосовое → заменит звук\n"
             "📎 файл-картинку или файл-аудио тоже подойдёт.\n\n"
             "Сайт обновится автоматически.")
        return

    # ---- картинка ----
    photo = msg.get("photo")
    if photo:
        fid = photo[-1]["file_id"]
        info = api("getFile", file_id=fid)
        path = info["result"]["file_path"]
        ext = Path(path).suffix or ".jpg"
        data = download(path, Path(ASSETS_DIR) / ("tmp_img" + ext))
        save_and_publish(chat_id, "image", data, "image/" + ext.lstrip("."), "")
        return

    doc = msg.get("document")
    if doc:
        mime = doc.get("mime_type") or ""
        fname = doc.get("file_name") or ""
        if mime.startswith("image/") or mime.startswith("audio/"):
            kind = "image" if mime.startswith("image/") else "sound"
            info = api("getFile", file_id=doc["file_id"])
            data = download(info["result"]["file_path"], Path(ASSETS_DIR) / "tmp")
            save_and_publish(chat_id, kind, data, mime, fname)
        else:
            send(chat_id, "Отправь фото или аудио (mp3/wav/m4a...).")
        return

    audio = msg.get("audio") or msg.get("voice") or msg.get("video_note") or msg.get("video")
    if audio:
        mime = audio.get("mime_type") if isinstance(audio, dict) else None
        fname = audio.get("file_name") if isinstance(audio, dict) else ""
        info = api("getFile", file_id=audio["file_id"])
        data = download(info["result"]["file_path"], Path(ASSETS_DIR) / "tmp")
        save_and_publish(chat_id, "sound", data, mime, fname)
        return

    send(chat_id, "Не понял. Пришли фото или аудио.")


def main():
    global TOKEN, CHAT
    TOKEN = load_token()
    CHAT = None
    offset = 0
    print("Bot started.", flush=True)
    while True:
        try:
            up = api("getUpdates", offset=offset, timeout=25)
            for u in up.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    CHAT = u["message"]["chat"]["id"]
                    print("incoming:", u["message"].keys(), flush=True)
                    handle_message(u["message"])
        except Exception as e:
            print("loop error:", repr(e), flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()