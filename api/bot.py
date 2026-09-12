import base64
import json
import os
import time
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
REPO = os.environ.get("GITHUB_REPO", "vitalysait/fliptag").strip()
BRANCH = os.environ.get("GITHUB_BRANCH", "master").strip()

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


# ---------------- Telegram API ----------------

def tg_api(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def tg_send(chat_id, text):
    try:
        tg_api("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)
    except Exception as e:
        print("send error:", repr(e), flush=True)


def tg_download(file_path):
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


# ---------------- GitHub API ----------------

def gh_get(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(path)}?ref={BRANCH}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "fliptag-bot")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def gh_put(path, raw_bytes, message):
    info = gh_get(path)
    payload = {
        "message": message,
        "content": base64.b64encode(raw_bytes).decode("ascii"),
        "branch": BRANCH,
    }
    if info:
        payload["sha"] = info.get("sha")
    url = f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, method="PUT",
                                 data=json.dumps(payload).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "fliptag-bot")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def gh_delete(path, message):
    info = gh_get(path)
    if not info:
        return
    payload = {"message": message, "branch": BRANCH, "sha": info.get("sha")}
    url = f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, method="DELETE",
                                 data=json.dumps(payload).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "fliptag-bot")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def gh_get_config():
    info = gh_get("config.json")
    if not info:
        return {"image": "", "sound": "", "video": "", "video_on": False}
    content = base64.b64decode(info["content"]).decode("utf-8")
    try:
        return json.loads(content)
    except Exception:
        return {"image": "", "sound": "", "video": "", "video_on": False}


def gh_save_config(cfg):
    raw = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
    gh_put("config.json", raw, "update config")


# ---------------- файлы ----------------

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


def publish(chat_id, kind, data, mime, fname):
    cfg = gh_get_config()
    old = cfg.get(kind)
    ext = ext_for(mime, fname, kind)
    name = f"{kind}_{int(time.time() * 1000)}{ext}"
    rel = f"assets/{name}"

    gh_put(rel, data, f"update {kind}: {rel}")
    if old and old != rel and old.startswith("assets/"):
        try:
            gh_delete(old, "remove old " + old)
        except Exception:
            pass
    cfg[kind] = rel
    if kind == "video":
        cfg["video_on"] = True
    gh_save_config(cfg)

    if kind == "image":
        tg_send(chat_id, "🖼 Готово! Картинка поменялась.\nЧерез минуту она появится на сайте.")
    elif kind == "sound":
        tg_send(chat_id, "🎵 Готово! Звук поменялся.\nЧерез минуту он будет на сайте.")
    else:
        tg_send(chat_id, "🎬 Готово! Видео поменялось.\nЧерез минуту оно появится на сайте.")


# ---------------- команды ----------------

def handle_message(msg):
    text = (msg.get("text") or "").strip()
    chat_id = msg["chat"]["id"]

    if text in ("/start", "старт", "привет", "здравствуй", "хай", "hello"):
        tg_send(chat_id, "Привет! Я меняю картинку, звук и видео на сайте.\n\n" + GUIDE)
        return
    if text in ("/help", "помощь", "что делать", "как"):
        tg_send(chat_id, GUIDE)
        return
    if text in ("/status", "статус", "что на сайте"):
        cfg = gh_get_config()
        video = cfg.get("video") or "пока нет"
        if cfg.get("video_on"):
            video += " ✅ вкл"
        else:
            video += " ❌ выкл"
        tg_send(chat_id,
                f"Сейчас на сайте:\n"
                f"🖼 Картинка: {cfg.get('image') or 'пока нет'}\n"
                f"🎵 Звук: {cfg.get('sound') or 'пока нет'}\n"
                f"🎬 Видео: {video}")
        return
    if text.startswith("/video"):
        words = text.split()
        if len(words) < 2 or words[1].lower() not in ("on", "off"):
            tg_send(chat_id, "/video on — включить видео\n/video off — выключить видео")
            return
        cfg = gh_get_config()
        cfg["video_on"] = (words[1].lower() == "on")
        gh_save_config(cfg)
        if cfg["video_on"]:
            tg_send(chat_id, "🎬 Видео включено. Через минуту появится на сайте.")
        else:
            tg_send(chat_id, "🎬 Видео выключено.")
        return
    if text.startswith("/"):
        tg_send(chat_id, "Не знаю такую команду. Просто отправь фото 🖼, аудио 🎵 или видео 🎬")
        return

    photo = msg.get("photo")
    if photo:
        fid = photo[-1]["file_id"]
        path = tg_api("getFile", file_id=fid)["result"]["file_path"]
        ext = Path(path).suffix or ".jpg"
        data = tg_download(path)
        publish(chat_id, "image", data, "image/" + ext.lstrip("."), "")
        return

    doc = msg.get("document")
    if doc:
        mime = doc.get("mime_type") or ""
        fname = doc.get("file_name") or ""
        path = tg_api("getFile", file_id=doc["file_id"])["result"]["file_path"]
        data = tg_download(path)
        if mime.startswith("image/"):
            publish(chat_id, "image", data, mime, fname)
        elif mime.startswith("audio/"):
            publish(chat_id, "sound", data, mime, fname)
        elif mime.startswith("video/"):
            publish(chat_id, "video", data, mime, fname)
        else:
            tg_send(chat_id, "Это не фото, не музыка и не видео. Мне нужно фото 🖼, аудио 🎵 или видео 🎬")
        return

    audio = msg.get("audio") or msg.get("voice")
    if audio:
        mime = audio.get("mime_type") if isinstance(audio, dict) else None
        fname = audio.get("file_name") if isinstance(audio, dict) else ""
        path = tg_api("getFile", file_id=audio["file_id"])["result"]["file_path"]
        data = tg_download(path)
        publish(chat_id, "sound", data, mime, fname)
        return

    video = msg.get("video")
    if video:
        mime = video.get("mime_type")
        fname = video.get("file_name") or ""
        path = tg_api("getFile", file_id=video["file_id"])["result"]["file_path"]
        data = tg_download(path)
        publish(chat_id, "video", data, mime, fname)
        return

    video_note = msg.get("video_note")
    if video_note:
        path = tg_api("getFile", file_id=video_note["file_id"])["result"]["file_path"]
        data = tg_download(path)
        ext = Path(path).suffix or ".mp4"
        publish(chat_id, "video", data, "video/" + ext.lstrip("."), "")
        return

    tg_send(chat_id, "Отправь фото 🖼, аудио 🎵 или видео 🎬 — и я всё сделаю.\nЕсли не понятно — напиши «как».")


# ---------------- Vercel handler ----------------

_MENU_DONE = False


def _ensure_menu():
    global _MENU_DONE
    if _MENU_DONE:
        return
    _MENU_DONE = True
    try:
        tg_api("setMyCommands", commands=json.dumps([
            {"command": "start", "description": "Приветствие"},
            {"command": "help", "description": "Как менять картинку и звук"},
            {"command": "status", "description": "Что сейчас на сайте"},
            {"command": "video", "description": "Видео on|off"},
        ]))
    except Exception:
        _MENU_DONE = False


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body=b"ok", ctype="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _ensure_menu()
        self._send(200, b"bot ok")

    def do_POST(self):
        _ensure_menu()
        if SECRET:
            received = self.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
            if received != SECRET:
                self._send(403, b"forbidden")
                return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            update = json.loads(body.decode("utf-8"))
            msg = update.get("message")
            if msg:
                handle_message(msg)
        except Exception as e:
            print("handler error:", repr(e), flush=True)
            traceback.print_exc()
        self._send(200, b"ok")