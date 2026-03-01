#!/usr/bin/env python3
"""Отчёт по приёмам пищи из файла bot_data.db (скачанного через /backup).

Использование:
  python scripts/report_from_db.py путь/к/bot_data.db USER_ID
  python scripts/report_from_db.py bot_data.db 1180871036

Вывод — в консоль. Можно перенаправить в файл:
  python scripts/report_from_db.py bot_data.db 1180871036 > report.txt
"""
import sqlite3
import sys
from pathlib import Path


def get_all_meals(conn, user_id: int) -> list:
    cur = conn.execute(
        "SELECT meal_type, at, stopped_at_80, calories, start_at, duration_seconds "
        "FROM meals WHERE user_id = ? ORDER BY at",
        (user_id,),
    )
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in rows]


def format_report(user_id: int, meals: list) -> str:
    if not meals:
        return f"Пользователь {user_id}: записей о приёмах пищи нет."
    main_ru = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}
    lines = [f"Приёмы пищи пользователя {user_id}", ""]
    main_meals = []
    snacks = []
    for m in meals:
        at = (m["at"] or "")[:16].replace("T", " ") or "—"
        kcal = m["calories"] or 0
        dur = m["duration_seconds"]
        row = f"  {at}  |  {kcal} ккал" + (f"  |  {dur // 60} мин" if dur else "")
        if m["meal_type"] == "snack":
            snacks.append(row)
        else:
            main_meals.append((main_ru.get(m["meal_type"], m["meal_type"]), row))
    if main_meals:
        lines.append("Основные приёмы:")
        for name, row in main_meals:
            lines.append(f"  {name}: {row}")
        lines.append("")
    if snacks:
        lines.append("Перекусы:")
        for row in snacks:
            lines.append(row)
    total_kcal = sum(m["calories"] or 0 for m in meals)
    lines.append("")
    lines.append(f"Всего записей: {len(meals)}, сумма ккал: {total_kcal}")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)
    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"Файл не найден: {db_path}", file=sys.stderr)
        sys.exit(1)
    try:
        user_id = int(sys.argv[2])
    except ValueError:
        print("USER_ID должен быть числом.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    meals = get_all_meals(conn, user_id)
    conn.close()
    print(format_report(user_id, meals))


if __name__ == "__main__":
    main()
