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
        api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print("send error:", repr(e), flush=True)


def reply(msg, text):
    send(msg["chat"]["id"], text)


# ---------------- состояние боа ----------------

def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"admins": [], "allowed": [], "filters": {"image": True, "sound": True}}


def save_state(st):
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def is_admin(chat_id):
    return chat_id in state["admins"]


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
    p = git("push")
    return p.returncode == 0


# ---------------- файлы ----------------

def read_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"image": "", "sound": ""}


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


def save_and_publish(chat_id, kind, data, mime, fname):
    ASSETS_DIR.mkdir(exist_ok=True)
    ext = ext_for(mime, fname, kind)
    name = f"{kind}_{int(time.time() * 1000)}{ext}"
    (ASSETS_DIR / name).write_bytes(data)
    rel = f"assets/{name}"
    cfg = read_config()
    cfg[kind] = rel
    write_config(cfg)
    if push_changes(f"update {kind}: {rel}"):
        reply_to_send(chat_id, f"✅ {kind} обновлён → {rel}\nСайт обновится сам через ~1 минуту.")
    else:
        reply_to_send(chat_id, "⚠️ Файл сохранён, но не отправился в git. Проверь авторизацию: gh auth setup-git")
    return rel


def reply_to_send(chat_id, text):
    send(chat_id, text)


# ---------------- команды ----------------

def cmd_start(msg):
    chat_id = msg["chat"]["id"]
    st = load_state()
    if chat_id not in st["allowed"]:
        st["allowed"].append(chat_id)
    if not st["admins"]:
        st["admins"].append(chat_id)
        save_state(st)
        reply(msg, "🚀 Бот запущен и настроен!\n"
                   "<b>Ты назначен админом.</b>\n\n"
                   "Отправь мне фото или аудио — они сразу появятся на сайте.\n"
                   "Нажми / — там все команды.")
        return
    save_state(st)
    reply(msg, "🚀 С возвращением! Отправь фото 🖼 или аудио 🎵 — обновлю сайт.\n"
               "Меню команд: /")


def cmd_help(msg):
    reply(msg,
          "📚 <b>Как пользоваться</b>\n\n"
          "🖼 Отправь <b>фото</b> — заменит картинку на сайте\n"
          "🎵 Отправь <b>аудио/голосовое</b> — заменит звук\n"
          "📎 Файл-картинку или файл-аудио тоже подойдёт\n\n"
          "/status — текущие картинка и звук\n"
          "/settings — фильтры (приём фото/аудио)\n"
          "/admins — управление админами\n"
          "/delchat — удалить чат из настроек")


def cmd_status(msg):
    cfg = read_config()
    fs = {"image": False, "sound": False}
    for k in fs:
        if cfg.get(k) and (BASE_DIR / cfg[k]).exists():
            fs[k] = True
    im = cfg.get("image") or "─ не задано"
    if fs["image"]:
        size = (BASE_DIR / cfg["image"]).stat().st_size
        im = f"{im} ({size // 1024} КБ) ✅"
    so = cfg.get("sound") or "─ не задано"
    if fs["sound"]:
        size = (BASE_DIR / cfg["sound"]).stat().st_size
        so = f"{so} ({size // 1024} КБ) ✅"
    reply(msg,
          "📊 <b>Статус сайта</b>\n\n"
          f"🖼 Картинка: <i>{im}</i>\n"
          f"🎵 Звук: <i>{so}</i>")


def cmd_settings(msg):
    if not is_admin(msg["chat"]["id"]):
        reply(msg, "⛔ Доступно только админу.")
        return
    f = state["filters"]
    reply(msg,
          "⚙️ <b>Настройки фильтров</b>\n\n"
          f"🖼 Приём фото: {'✅ включён' if f.get('image', True) else '❌ выключен'}\n"
          f"🎵 Приём аудио: {'✅ включён' if f.get('sound', True) else '❌ выключен'}\n\n"
          "Команды:\n"
          "/image on | /image off\n"
          "/sound on | /sound off")


def set_filter(msg, key):
    if not is_admin(msg["chat"]["id"]):
        reply(msg, "⛔ Доступно только админу.")
        return
    words = (msg.get("text") or "").split()
    if len(words) < 2 or words[1].lower() not in ("on", "off"):
        reply(msg, f"Использование: /{key} on | off")
        return
    st = load_state()
    st["filters"][key] = (words[1].lower() == "on")
    save_state(st)
    global state
    state = st
    reply(msg, f"✅ Приём <b>{key}</b>: {'включён' if st['filters'][key] else 'выключен'}")


def cmd_admins(msg):
    if not is_admin(msg["chat"]["id"]):
        reply(msg, "⛔ Доступно только админу.")
        return
    st = load_state()
    lst = "".join(f"👑 {a}\n" for a in st["admins"]) if st["admins"] else "<i>нет админов</i>"
    reply(msg,
          "👑 <b>Админы</b>\n\n" + lst +
          "\nДобавить: /addadmin <b>ID</b>\nУдалить: /deladmin <b>ID</b>")


def add_admins(msg, mode):
    if not is_admin(msg["chat"]["id"]):
        reply(msg, "⛔ Доступно только админу.")
        return
    words = (msg.get("text") or "").split()
    if len(words) < 2 or not words[1].isdigit():
        reply(msg, "Введи ID после команды: /addadmin 123456789")
        return
    uid = int(words[1])
    st = load_state()
    if mode == "add":
        if uid not in st["admins"]:
            st["admins"].append(uid)
        save_state(st)
        reply(msg, f"✅ Админ добавлен: {uid}")
    else:
        st["admins"] = [a for a in st["admins"] if a != uid]
        save_state(st)
        reply(msg, f"🗑 Админ удалён: {uid}")
    global state
    state = st


def cmd_delchat(msg):
    if not is_admin(msg["chat"]["id"]):
        reply(msg, "⛔ Доступно только админу.")
        return
    words = (msg.get("text") or "").split()
    current_chat = msg["chat"]["id"]
    if len(words) < 2 or not words[1].isdigit():
        reply(msg, "Введи ID чата после команды: /delchat 123456789")
    uid = int(words[1])
    st = load_state()
    st["allowed"] = [c for c in st["allowed"] if c != uid]
    save_state(st)
    reply(msg, f"🗑 Чат удалён из настроек: {uid}")
    global state
    state = st


# ---------------- обработка ----------------

def handle_message(msg):
    text = (msg.get("text") or "").strip()
    chat_id = msg["chat"]["id"]

    if text == "/start":
        cmd_start(msg)
        return
    if text == "/help":
        cmd_help(msg)
        return
    if text == "/status":
        cmd_status(msg)
        return
    if text == "/settings":
        cmd_settings(msg)
        return
    if text.startswith("/addadmin"):
        add_admins(msg, "add")
        return
    if text.startswith("/deladmin"):
        add_admins(msg, "del")
        return
    if text.startswith("/delchat"):
        cmd_delchat(msg)
        return
    if text.startswith("/image on") or text.startswith("/image off"):
        set_filter(msg, "image")
        return
    if text.startswith("/sound on") or text.startswith("/sound off"):
        set_filter(msg, "sound")
        return
    if text.startswith("/"):
        cmd_help(msg)
        return

    if not state["filters"].get("image", True) and not state["filters"].get("sound", True):
        reply(msg, "⛔ Приём файлов сейчас выключен. Админ: /settings")
        return

    # ---- картинка ----
    photo = msg.get("photo")
    if photo:
        fid = photo[-1]["file_id"]
        info = api("getFile", file_id=fid)
        path = info["result"]["file_path"]
        ext = Path(path).suffix or ".jpg"
        data = download(path)
        save_and_publish(chat_id, "image", data, "image/" + ext.lstrip("."), "")
        return

    doc = msg.get("document")
    if doc:
        mime = doc.get("mime_type") or ""
        fname = doc.get("file_name") or ""
        if mime.startswith("image/"):
            data = download(api("getFile", file_id=doc["file_id"])["result"]["file_path"])
            save_and_publish(chat_id, "image", data, mime, fname)
        elif mime.startswith("audio/"):
            data = download(api("getFile", file_id=doc["file_id"])["result"]["file_path"])
            save_and_publish(chat_id, "sound", data, mime, fname)
        else:
            reply(msg, "Отправь фото или аудио (mp3/wav/m4a...).")
        return

    audio = msg.get("audio") or msg.get("voice") or msg.get("video_note") or msg.get("video")
    if audio:
        mime = audio.get("mime_type") if isinstance(audio, dict) else None
        fname = audio.get("file_name") if isinstance(audio, dict) else ""
        data = download(api("getFile", file_id=audio["file_id"])["result"]["file_path"])
        save_and_publish(chat_id, "sound", data, mime, fname)
        return

    if any(x in msg for x in ("document", "audio", "voice", "video")):
        return

    reply(msg, "Не понял. Пришли фото или аудио.")


# ---------------- main ----------------

def setup_menu():
    try:
        api("setMyCommands", commands=json.dumps([
            {"command": "start", "description": "🚀 Запустить бота и приветствие"},
            {"command": "help", "description": "📚 Помощь по использованию"},
            {"command": "status", "description": "📊 Статус и информация"},
            {"command": "settings", "description": "⚙️ Настройки фильтров"},
            {"command": "admins", "description": "👑 Управление админами"},
            {"command": "delchat", "description": "🗑 Удалить чат из настроек"},
        ]))
        print("Menu set.", flush=True)
    except Exception as e:
        print("menu error:", repr(e), flush=True)


def main():
    global TOKEN, state
    TOKEN = load_token()
    state = load_state()
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