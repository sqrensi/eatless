"""SQLite storage: users, settings, meals, impulses, streaks."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, time, timedelta
from pathlib import Path

from config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                username TEXT,
                name TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS water (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                ml INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
                no_eat_after TEXT,
                remind_boundary_minutes INTEGER DEFAULT 30,
                daily_remind_time TEXT,
                timezone_offset INTEGER DEFAULT 0,
                daily_calorie_limit INTEGER DEFAULT 1700
            );
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meal_type TEXT NOT NULL,
                at TEXT NOT NULL,
                stopped_at_80 INTEGER DEFAULT 0,
                calories INTEGER,
                start_at TEXT,
                duration_seconds INTEGER
            );
            CREATE TABLE IF NOT EXISTS impulses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                waited_10_min INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS streaks (
                user_id INTEGER NOT NULL,
                streak_type TEXT NOT NULL,
                current_count INTEGER NOT NULL,
                last_date TEXT NOT NULL,
                PRIMARY KEY (user_id, streak_type)
            );
            CREATE INDEX IF NOT EXISTS idx_meals_user_at ON meals(user_id, at);
            CREATE INDEX IF NOT EXISTS idx_impulses_user_at ON impulses(user_id, at);
        """)
        # Миграция: добавить колонки в существующие БД (игнорируем, если уже есть)
        for sql in [
            "ALTER TABLE settings ADD COLUMN daily_calorie_limit INTEGER DEFAULT 1700",
            "ALTER TABLE meals ADD COLUMN calories INTEGER",
            "ALTER TABLE meals ADD COLUMN start_at TEXT",
            "ALTER TABLE meals ADD COLUMN duration_seconds INTEGER",
            "ALTER TABLE users ADD COLUMN chat_id INTEGER",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass


def upsert_user(user_id: int, username: str | None, name: str | None, chat_id: int | None = None):
    with get_conn() as conn:
        if chat_id is not None:
            conn.execute(
                "INSERT INTO users (user_id, username, name, created_at, chat_id) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET username=?, name=?, chat_id=?",
                (user_id, username or "", name or "", datetime.utcnow().isoformat(), chat_id, username or "", name or "", chat_id),
            )
        else:
            conn.execute(
                "INSERT INTO users (user_id, username, name, created_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET username=?, name=?",
                (user_id, username or "", name or "", datetime.utcnow().isoformat(), username or "", name or ""),
            )
        conn.execute(
            "INSERT OR IGNORE INTO settings (user_id) VALUES (?)",
            (user_id,),
        )


def get_settings(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT no_eat_after, remind_boundary_minutes, daily_remind_time, daily_calorie_limit FROM settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"no_eat_after": "21:00", "remind_boundary_minutes": 30, "daily_remind_time": None, "daily_calorie_limit": 1700}
    return {
        "no_eat_after": row["no_eat_after"] if row["no_eat_after"] is not None else "21:00",
        "remind_boundary_minutes": row["remind_boundary_minutes"] or 30,
        "daily_remind_time": row["daily_remind_time"],
        "daily_calorie_limit": row["daily_calorie_limit"] if row["daily_calorie_limit"] is not None else 1700,
    }


def set_no_eat_after(user_id: int, time_str: str | None):
    with get_conn() as conn:
        conn.execute("UPDATE settings SET no_eat_after = ? WHERE user_id = ?", (time_str, user_id))


def set_daily_remind(user_id: int, time_str: str | None):
    with get_conn() as conn:
        conn.execute("UPDATE settings SET daily_remind_time = ? WHERE user_id = ?", (time_str, user_id))


def add_meal(
    user_id: int,
    meal_type: str,
    stopped_at_80: bool = False,
    calories: int | None = None,
    start_at: str | None = None,
    duration_seconds: int | None = None,
):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meals (user_id, meal_type, at, stopped_at_80, calories, start_at, duration_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                meal_type,
                datetime.utcnow().isoformat(),
                1 if stopped_at_80 else 0,
                calories,
                start_at,
                duration_seconds,
            ),
        )


def add_impulse(user_id: int, waited_10_min: bool):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO impulses (user_id, at, waited_10_min) VALUES (?, ?, ?)",
            (user_id, datetime.utcnow().isoformat(), 1 if waited_10_min else 0),
        )


def _today_utc() -> str:
    return date.today().isoformat()


def get_meals_today(user_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT meal_type, at, stopped_at_80, calories, start_at, duration_seconds FROM meals WHERE user_id = ? AND date(at, 'localtime') = date('now', 'localtime') ORDER BY at",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_meals(user_id: int) -> list:
    """Все приёмы пищи и перекусы пользователя (для отчёта)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT meal_type, at, stopped_at_80, calories, start_at, duration_seconds FROM meals WHERE user_id = ? ORDER BY at",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_total_eating_time_today(user_id: int) -> int:
    """Сумма длительностей приёмов пищи за сегодня, в секундах."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM meals WHERE user_id = ? AND date(at, 'localtime') = date('now', 'localtime') AND duration_seconds IS NOT NULL",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def get_calories_today(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(calories), 0) AS total FROM meals WHERE user_id = ? AND date(at, 'localtime') = date('now', 'localtime') AND calories IS NOT NULL",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def get_streak(user_id: int, streak_type: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT current_count, last_date FROM streaks WHERE user_id = ? AND streak_type = ?",
            (user_id, streak_type),
        ).fetchone()
    if not row:
        return 0
    last = row["last_date"]
    today = _today_utc()
    if last == today:
        return row["current_count"]
    # yesterday = continue streak; else reset
    try:
        last_d = date.fromisoformat(last)
        today_d = date.today()
        if (today_d - last_d).days == 1:
            return row["current_count"]
    except Exception:
        pass
    return 0


def set_streak(user_id: int, streak_type: str, count: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO streaks (user_id, streak_type, current_count, last_date) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(user_id, streak_type) DO UPDATE SET current_count = ?, last_date = ?",
            (user_id, streak_type, count, _today_utc(), count, _today_utc()),
        )


def increment_streak(user_id: int, streak_type: str) -> int:
    current = get_streak(user_id, streak_type)
    today = _today_utc()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_date FROM streaks WHERE user_id = ? AND streak_type = ?",
            (user_id, streak_type),
        ).fetchone()
    if row and row["last_date"] == today:
        return current  # already counted today
    new_count = current + 1 if (not row or _is_yesterday(row["last_date"])) else 1
    set_streak(user_id, streak_type, new_count)
    return new_count


def _is_yesterday(d: str) -> bool:
    try:
        return (date.today() - date.fromisoformat(d)).days == 1
    except Exception:
        return False


def get_impulses_waited_today(user_id: int) -> int:
    with get_conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM impulses WHERE user_id = ? AND waited_10_min = 1 AND date(at, 'localtime') = date('now', 'localtime')",
            (user_id,),
        ).fetchone()[0]
    return n


def get_last_meal_time(user_id: int) -> datetime | None:
    """Время последнего приёма пищи (at) для проверки «перекус через час»."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT at FROM meals WHERE user_id = ? ORDER BY at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
    except Exception:
        return None


WATER_GOAL_ML = 2000


def add_water(user_id: int, ml: int):
    with get_conn() as conn:
        conn.execute("INSERT INTO water (user_id, at, ml) VALUES (?, ?, ?)", (user_id, datetime.utcnow().isoformat(), ml))


def get_water_today_ml(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(ml), 0) AS total FROM water WHERE user_id = ? AND date(at, 'localtime') = date('now', 'localtime')",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def get_all_chat_ids() -> list[int]:
    """Все chat_id для рассылки напоминаний."""
    with get_conn() as conn:
        rows = conn.execute("SELECT chat_id FROM users WHERE chat_id IS NOT NULL").fetchall()
    return [r["chat_id"] for r in rows if r["chat_id"]]
