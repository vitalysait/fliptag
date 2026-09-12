import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BOT_DIR / "state.json"


# ---------------- токен и API ----------------

def load_token():
    env_path = BOT_DIR / ".env"
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
        api("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)
    except Exception as e:
        print("send error:", repr(e), flush=True)


def reply(msg, text):
    send(msg["chat"]["id"], text)


# ---------------- git ----------------

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
            return False
    git("pull", "--rebase")
    return git("push").returncode == 0


# ---------------- файлы ----------------

def read_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"image": "", "sound": "", "video": "", "video_on": False}


def write_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def download(file_path):
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    tmp = BOT_DIR / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / f"dl_{int(time.time() * 1000)}"
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data)
    return data


def ext_for(mime, fname, kind):
    if fname and "." in fname:
        return Path(fname).suffix.lower() or _default_ext(kind)
    if mime:
        exts = {
            "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
            "audio/wav": ".wav", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a", "audio/flac": ".flac", "audio/aac": ".aac",
            "video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogg",
            "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/avi": ".avi",
        }
        if mime in exts:
            return exts[mime]
    return _default_ext(kind)


def _default_ext(kind):
    if kind == "image":
        return ".jpg"
    if kind == "sound":
        return ".mp3"
    return ".mp4"


def save_and_publish(chat_id, kind, data, mime, fname):
    ASSETS_DIR.mkdir(exist_ok=True)
    ext = ext_for(mime, fname, kind)
    name = f"{kind}_{int(time.time() * 1000)}{ext}"
    (ASSETS_DIR / name).write_bytes(data)
    rel = f"assets/{name}"
    cfg = read_config()
    cfg[kind] = rel
    if kind == "video":
        cfg["video_on"] = True
    write_config(cfg)
    if push_changes(f"update {kind}: {rel}"):
        if kind == "image":
            reply_send(chat_id, "🖼 Готово! Картинка поменялась.\nЧерез минуту она появится на сайте.")
        elif kind == "sound":
            reply_send(chat_id, "🎵 Готово! Звук поменялся.\nЧерез минуту он будет на сайте.")
        else:
            reply_send(chat_id, "🎬 Готово! Видео поменялось.\nЧерез минуту оно появится на сайте.")
    else:
        reply_send(chat_id, "⚠️ Что-то пошло не так, файл не загрузился на сайт.\nНапиши сюда об этом.")
    return rel


def reply_send(chat_id, text):
    send(chat_id, text)


# ---------------- команды ----------------

GUIDE = (
    "Как сменить картинку:\n"
    "1. Нажми на скрепку 📎\n"
    "2. Выбери фото\n"
    "3. Нажми отправить\n\n"
    "Как сменить звук:\n"
    "1. Нажми на скрепку 📎\n"
    "2. Выбери аудио (mp3)\n"
    "3. Нажми отправить\n\n"
    "Как сменить видео:\n"
    "1. Нажми на скрепку 📎\n"
    "2. Выбери видео (mp4)\n"
    "3. Нажми отправить\n\n"
    "Включить или выключить видео на сайте:\n"
    "/video on — включить\n"
    "/video off — выключить\n\n"
    "И всё! Через минуту на сайте будут новые картинка, звук и видео."
)


def cmd_start(msg):
    reply(msg,
          "Привет! Я меняю картинку, звук и видео на сайте.\n\n"
          + GUIDE)


def cmd_help(msg):
    reply(msg, GUIDE)


def cmd_status(msg):
    cfg = read_config()
    im = cfg.get("image") or "пока нет"
    so = cfg.get("sound") or "пока нет"
    video = cfg.get("video") or "пока нет"
    if cfg.get("video_on"):
        video += " ✅ вкл"
    else:
        video += " ❌ выкл"
    reply(msg,
          f"Сейчас на сайте:\n"
          f"🖼 Картинка: {im}\n"
          f"🎵 Звук: {so}\n"
          f"🎬 Видео: {video}")


# ---------------- обработка ----------------

def handle_message(msg):
    text = (msg.get("text") or "").strip()
    chat_id = msg["chat"]["id"]

    if text in ("/start", "старт", "привет", "здравствуй", "хай", "hello"):
        cmd_start(msg)
        return
    if text in ("/help", "помощь", "что делать", "как"):
        cmd_help(msg)
        return
    if text in ("/status", "статус", "что на сайте"):
        cmd_status(msg)
        return
    if text.startswith("/video"):
        words = text.split()
        if len(words) < 2 or words[1].lower() not in ("on", "off"):
            reply(msg, "/video on — включить видео\n/video off — выключить видео")
            return
        cfg = read_config()
        cfg["video_on"] = (words[1].lower() == "on")
        write_config(cfg)
        if cfg["video_on"]:
            reply(msg, "🎬 Видео включено. Через минуту появится на сайте.")
        else:
            reply(msg, "🎬 Видео выключено.")
        if push_changes("video " + ("on" if cfg["video_on"] else "off")):
            pass
        return
    if text.startswith("/"):
        reply(msg, "Не знаю такую команду. Просто отправь фото 🖼, аудио 🎵 или видео 🎬")
        return

    # ---- картинка ----
    photo = msg.get("photo")
    if photo:
        fid = photo[-1]["file_id"]
        path = api("getFile", file_id=fid)["result"]["file_path"]
        ext = Path(path).suffix or ".jpg"
        data = download(path)
        save_and_publish(msg["chat"]["id"], "image", data, "image/" + ext.lstrip("."), "")
        return

    # ---- документ ----
    doc = msg.get("document")
    if doc:
        mime = doc.get("mime_type") or ""
        fname = doc.get("file_name") or ""
        data = download(api("getFile", file_id=doc["file_id"])["result"]["file_path"])
        if mime.startswith("image/"):
            save_and_publish(msg["chat"]["id"], "image", data, mime, fname)
            return
        if mime.startswith("audio/"):
            save_and_publish(msg["chat"]["id"], "sound", data, mime, fname)
            return
        if mime.startswith("video/"):
            save_and_publish(msg["chat"]["id"], "video", data, mime, fname)
            return
        reply(msg, "Это не фото, не музыка и не видео. Мне нужно фото 🖼, аудио 🎵 или видео 🎬")
        return

    # ---- аудио / голосовое ----
    audio = msg.get("audio") or msg.get("voice")
    if audio:
        mime = audio.get("mime_type") if isinstance(audio, dict) else None
        fname = audio.get("file_name") if isinstance(audio, dict) else ""
        data = download(api("getFile", file_id=audio["file_id"])["result"]["file_path"])
        save_and_publish(msg["chat"]["id"], "sound", data, mime, fname)
        return

    # ---- видео ----
    video = msg.get("video")
    if video:
        mime = video.get("mime_type")
        fname = video.get("file_name") or ""
        data = download(api("getFile", file_id=video["file_id"])["result"]["file_path"])
        save_and_publish(msg["chat"]["id"], "video", data, mime, fname)
        return

    reply(msg, "Отправь фото 🖼, аудио 🎵 или видео 🎬 — и я всё сделаю.\nЕсли не понятно — напиши «как».")


# ---------------- main ----------------

def setup_menu():
    try:
        api("setMyCommands", commands=json.dumps([
            {"command": "start", "description": "Приветствие"},
            {"command": "help", "description": "Как менять картинку и звук"},
            {"command": "status", "description": "Что сейчас на сайте"},
            {"command": "video", "description": "Видео on|off"},
        ]))
        print("Menu set.", flush=True)
    except Exception as e:
        print("menu error:", repr(e), flush=True)


def main():
    global TOKEN
    TOKEN = load_token()
    offset = 0
    setup_menu()
    print("Bot started.", flush=True)
    while True:
        try:
            up = api("getUpdates", offset=offset, timeout=25)
            for u in up.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    print("incoming:", u["message"].get("text", u["message"].keys()), flush=True)
                    handle_message(u["message"])
        except Exception as e:
            print("loop error:", repr(e), flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()