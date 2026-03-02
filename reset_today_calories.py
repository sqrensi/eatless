"""Однократный сброс: обнулить ккалории за сегодня и сбросить отметки котов (для проверки)."""
from database import get_conn
from datetime import date

today = date.today().isoformat()
with get_conn() as conn:
    cur = conn.execute("UPDATE meals SET calories = NULL WHERE date(at, 'localtime') = ?", (today,))
    n_meals = cur.rowcount
    cur2 = conn.execute("DELETE FROM cat_goal_sent WHERE date = ?", (today,))
    n_cat = cur2.rowcount
print(f"Обнулены ккалории в {n_meals} приёмах за сегодня. Сброшено отметок котов: {n_cat}.")
