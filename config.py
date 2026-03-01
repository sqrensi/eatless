import os
from pathlib import Path

# Load .env manually (no python-dotenv to keep deps minimal)
# Если есть .env.test — используем его (тестовый бот), иначе .env (прод)
_base = Path(__file__).parent
_env_path = _base / ".env.test" if (_base / ".env.test").exists() else _base / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in .env or .env.test")

# Кот-помогатор: Мурлок (мурлычет + «закрывает» холодильник)
BOT_NAME = "Мурлок"

# Тестовый бот — отдельная БД, чтобы не затронуть прод
_is_test = (_base / ".env.test").exists()
DB_PATH = Path(__file__).parent / ("bot_data_test.db" if _is_test else "bot_data.db")

# Папка с фото для сообщений во время еды (jpg, png, webp). Абсолютный путь, чтобы работало при любом cwd.
MEAL_PHOTOS_DIR = _base.resolve() / "assets" / "meal_photos"

# User ID, которому можно выгрузить бэкап БД командой /backup (в .env: BACKUP_USER_ID=123456789)
_backup_id = os.getenv("BACKUP_USER_ID", "").strip()
BACKUP_USER_ID = int(_backup_id) if _backup_id.isdigit() else None
