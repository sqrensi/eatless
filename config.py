import os
from pathlib import Path

# Load .env manually (no python-dotenv to keep deps minimal)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in .env")

# Кот-помогатор: Мурлок (мурлычет + «закрывает» холодильник)
BOT_NAME = "Мурлок"

DB_PATH = Path(__file__).parent / "bot_data.db"

# Для теста: 1 минута = 1 секунда (7/15/20 мин → 7/15/20 сек, 10 мин → 10 сек)
TEST_FAST_TIMERS = False
