"""All bot handlers: start, menu, meal flow, snack, progress, settings."""
import logging
from datetime import datetime, timedelta, time as dt_time

from telegram import Update
from telegram.ext import ContextTypes

from config import TEST_FAST_TIMERS, BOT_NAME
from database import (
    init_db,
    upsert_user,
    get_settings,
    add_meal,
    add_impulse,
    get_meals_today,
    get_calories_today,
    get_total_eating_time_today,
    get_streak,
    increment_streak,
    get_impulses_waited_today,
)
from keyboards import (
    MAIN_MARKUP,
    WATER_MARKUP,
    HUNGER_MARKUP,
    PLATE_MARKUP,
    MEAL_FINISH_MARKUP,
    STOPPED_80_MARKUP,
    SNACK_AFTER_MARKUP,
    MEAL_TYPE_MAIN_MARKUP,
    RECORD_SNACK_MARKUP,
    BACK_TO_MENU_MARKUP,
)

logger = logging.getLogger(__name__)

# FSM: user_id -> state string
USER_STATE: dict[int, str] = {}
# user_id -> "awaiting_80" so we know to record meal + stopped_at_80 on "Да, вышел"
USER_AWAITING_80: set[int] = set()
# user_id -> (meal_type, stopped_80) пока ждём ввод ккалорий; meal_type может быть None (ещё не выбрал тип)
PENDING_MEAL: dict[int, tuple[str | None, bool]] = {}
# Приём идёт: пользователь ест, пока не нажмёт "Закончил приём пищи"
USER_IN_MEAL: set[int] = set()
# user_id -> datetime начала приёма (для секундомера)
USER_MEAL_START: dict[int, datetime] = {}
# После "Закончил приём пищи": user_id -> {start_at, duration_seconds, meal_type} до сохранения приёма
MEAL_SESSION: dict[int, dict] = {}
# Тип приёма при «Собираюсь поесть» (выбирается до старта секундомера)
USER_MEAL_START_TYPE: dict[int, str] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.username, user.first_name)
    USER_STATE[user.id] = ""
    await update.message.reply_text(
        f"Мяу! Я {BOT_NAME}, кот-помогатор. Помогу тебе есть меньше и осознаннее.\n\n"
        "• Перед едой — короткий чек-лист, потом секундомер; нажми «Закончила приём пищи», когда закончишь.\n"
        "• Хочется перекусить — подождём 10 минут и спрошу снова.\n"
        "• Можно вести дневник приёмов и смотреть прогресс.\n\n"
        "Выбери действие в меню ниже 👇",
        reply_markup=MAIN_MARKUP,
    )


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    USER_STATE[user_id] = ""
    PENDING_MEAL.pop(user_id, None)
    USER_IN_MEAL.discard(user_id)
    USER_MEAL_START.pop(user_id, None)
    USER_MEAL_START_TYPE.pop(user_id, None)
    MEAL_SESSION.pop(user_id, None)
    await update.message.reply_text(f"Мяу! Главное меню. Что делаем? 👇", reply_markup=MAIN_MARKUP)


def _is_after_boundary(user_id: int) -> tuple[bool, str]:
    """Проверяет, прошла ли граница «не есть после». Возвращает (да, граница_строка)."""
    s = get_settings(user_id)
    boundary = s.get("no_eat_after") or "21:00"
    try:
        parts = boundary.replace(".", ":").strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        boundary_time = dt_time(h, m, 0)
    except (ValueError, IndexError):
        return False, boundary
    # Время сервера (поставь TZ на сервере под свой часовой пояс, иначе считается по UTC)
    now = datetime.now().time()
    # Сравниваем: если граница 21:00, то 20:59 ещё можно, 21:00 уже нет
    now_t = now.hour * 60 + now.minute
    bound_t = boundary_time.hour * 60 + boundary_time.minute
    return now_t >= bound_t, boundary


# ----- Meal flow: before meal -> checklist -> 20 min timer -----
MEAL_STATES = "water", "hunger", "plate", "eating"


async def meal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "🍽 Собираюсь поесть":
        return
    user_id = update.effective_user.id
    after, boundary = _is_after_boundary(user_id)
    if after:
        await update.message.reply_text(
            f"Мяу! Сейчас уже после {boundary}. {BOT_NAME} говорит: не есть после {boundary}. Лучше выпей воды или подожди до завтра.",
            reply_markup=MAIN_MARKUP,
        )
        return
    USER_STATE[user_id] = "water"
    await update.message.reply_text(
        "Перед едой — три шага.\n\n1️⃣ Выпила стакан воды?",
        reply_markup=WATER_MARKUP,
    )


async def meal_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, "")
    text = (update.message.text or "").strip()

    if state == "water":
        USER_STATE[user_id] = "hunger"
        await update.message.reply_text(
            "2️⃣ Оцени голод по шкале 1–10 (1 — не голодна, 10 — очень голодна).",
            reply_markup=HUNGER_MARKUP,
        )
        return
    if state == "hunger":
        USER_STATE[user_id] = "plate"
        await update.message.reply_text(
            "3️⃣ По возможности возьми маленькую тарелку — так порция кажется больше.",
            reply_markup=PLATE_MARKUP,
        )
        return
    if state == "plate":
        USER_STATE[user_id] = "meal_choose_type"
        await update.message.reply_text(
            "Какой приём? Выбери: завтрак, обед или ужин.",
            reply_markup=MEAL_TYPE_MAIN_MARKUP,
        )
        return
    if state == "meal_choose_type":
        meal_type = MEAL_BUTTON_TO_MAIN_TYPE.get(text)
        if not meal_type:
            return
        USER_STATE[user_id] = ""
        USER_MEAL_START_TYPE[user_id] = meal_type
        USER_IN_MEAL.add(user_id)
        USER_MEAL_START[user_id] = datetime.utcnow()
        job_queue = context.application.job_queue
        t1 = timedelta(seconds=10) if TEST_FAST_TIMERS else timedelta(minutes=5)
        t2 = timedelta(seconds=20) if TEST_FAST_TIMERS else timedelta(minutes=10)
        if job_queue:
            job_queue.run_once(
                _water_reminder_during_meal,
                t1,
                data={"chat_id": update.effective_chat.id, "user_id": user_id},
            )
            job_queue.run_once(
                _water_reminder_during_meal,
                t2,
                data={"chat_id": update.effective_chat.id, "user_id": user_id},
            )
        await update.message.reply_text(
            "Секундомер запущен. Ешь спокойно. Когда закончишь — нажми «Закончила приём пищи».",
            reply_markup=MEAL_FINISH_MARKUP,
        )
        return
    # Not in meal flow
    await _maybe_meal_80_response(update, context)


async def _water_reminder_during_meal(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if not job or not job.data:
        return
    user_id = job.data["user_id"]
    if user_id not in USER_IN_MEAL:
        return
    await context.bot.send_message(
        job.data["chat_id"],
        "💧 Остановись на минуту, попей воды.",
    )


async def meal_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь нажал «Закончила приём пищи»."""
    user_id = update.effective_user.id
    if user_id not in USER_IN_MEAL:
        return
    start_dt = USER_MEAL_START.pop(user_id, None)
    meal_type = USER_MEAL_START_TYPE.pop(user_id, "meal")
    USER_IN_MEAL.discard(user_id)
    if not start_dt:
        await update.message.reply_text("Ок.", reply_markup=MAIN_MARKUP)
        return
    duration_seconds = int((datetime.utcnow() - start_dt).total_seconds())
    if duration_seconds < 0:
        duration_seconds = 0
    MEAL_SESSION[user_id] = {
        "start_at": start_dt.isoformat(),
        "duration_seconds": duration_seconds,
        "meal_type": meal_type,
    }
    mins = duration_seconds // 60
    secs = duration_seconds % 60
    USER_AWAITING_80.add(user_id)
    await update.message.reply_text(
        f"Приём пищи: {mins} мин {secs} сек.\n\nОстановилась на 80% сытости?",
        reply_markup=STOPPED_80_MARKUP,
    )


async def meal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена приёма пищи (во время еды)."""
    user_id = update.effective_user.id
    USER_IN_MEAL.discard(user_id)
    USER_MEAL_START.pop(user_id, None)
    USER_MEAL_START_TYPE.pop(user_id, None)
    await update.message.reply_text("Приём отменён.", reply_markup=MAIN_MARKUP)


async def _maybe_meal_80_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id not in USER_AWAITING_80:
        return False
    session = MEAL_SESSION.get(user_id)
    meal_type = session.get("meal_type", "meal") if session else "meal"
    text = (update.message.text or "").strip()
    if "Да, вышла" in text or "вышла" in text.lower():
        USER_AWAITING_80.discard(user_id)
        PENDING_MEAL[user_id] = (meal_type, True)
        USER_STATE[user_id] = "log_meal_calories"
        await update.message.reply_text(
            "Супер! Остановилась на 80%. Примерные ккалории? (напиши число)",
            reply_markup=BACK_TO_MENU_MARKUP,
        )
        return True
    if "доела" in text.lower() or "Нет, доела" in text:
        USER_AWAITING_80.discard(user_id)
        PENDING_MEAL[user_id] = (meal_type, False)
        USER_STATE[user_id] = "log_meal_calories"
        await update.message.reply_text(
            "Примерные ккалории? (напиши число)",
            reply_markup=BACK_TO_MENU_MARKUP,
        )
        return True
    return False


# ----- Snack: 10 min wait -----
USER_AWAITING_SNACK: set[int] = set()


async def snack_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "🍪 Хочу перекусить":
        return
    user_id = update.effective_user.id
    after, boundary = _is_after_boundary(user_id)
    if after:
        await update.message.reply_text(
            f"Мяу! Уже после {boundary}. {BOT_NAME} говорит: лучше выпей воды.",
            reply_markup=MAIN_MARKUP,
        )
        return
    USER_AWAITING_SNACK.add(user_id)
    job_queue = context.application.job_queue
    t10 = timedelta(seconds=10) if TEST_FAST_TIMERS else timedelta(minutes=10)
    if job_queue:
        job_queue.run_once(
            _snack_10min,
            t10,
            data={"chat_id": update.effective_chat.id, "user_id": user_id},
        )
    msg = "Подожди 10 секунд. Выпей воды. Через 10 сек спрошу снова." if TEST_FAST_TIMERS else "Подожди 10 минут. Выпей стакан воды. Через 10 минут спрошу снова."
    await update.message.reply_text(msg)


async def _snack_10min(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if not job or not job.data:
        return
    await context.bot.send_message(
        job.data["chat_id"],
        "Прошло 10 минут. Всё ещё хочется перекусить?",
        reply_markup=SNACK_AFTER_MARKUP,
    )


async def snack_after(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    if user_id not in USER_AWAITING_SNACK:
        return
    if "Нет, прошло" in text or "прошло" in text.lower():
        USER_AWAITING_SNACK.discard(user_id)
        add_impulse(user_id, waited_10_min=True)
        n = increment_streak(user_id, "snack_waited")
        await update.message.reply_text(
            f"Отлично! Ты переждала импульс. Серия: {n} дней подряд.",
            reply_markup=MAIN_MARKUP,
        )
        return
    if "перекусила" in text.lower() or "Уже перекусила" in text:
        USER_AWAITING_SNACK.discard(user_id)
        add_impulse(user_id, waited_10_min=False)
        PENDING_MEAL[user_id] = ("snack", False)
        USER_STATE[user_id] = "log_meal_calories"
        await update.message.reply_text(
            "Примерные ккалории перекуса? (напиши число)",
            reply_markup=BACK_TO_MENU_MARKUP,
        )
        return
    if "Да, хочется" in text or "хочется" in text.lower():
        USER_AWAITING_SNACK.discard(user_id)
        USER_STATE[user_id] = "snack_will_log"
        await update.message.reply_text(
            "Ок, тогда перекуси. Когда закончишь — нажми «Записать перекус».",
            reply_markup=RECORD_SNACK_MARKUP,
        )
        return
    # Любой другой ответ — выходим из ожидания
    USER_AWAITING_SNACK.discard(user_id)
    await update.message.reply_text("Выбери действие в меню.", reply_markup=MAIN_MARKUP)


# Тип приёма: только завтрак, обед, ужин (для «Собираюсь поесть»)
MEAL_BUTTON_TO_MAIN_TYPE = {
    "🌅 Завтрак": "breakfast",
    "☀️ Обед": "lunch",
    "🌙 Ужин": "dinner",
}


async def record_snack_ask_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«Записать перекус» — спрашиваем ккалории и сохраняем как snack."""
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "snack_will_log":
        return
    PENDING_MEAL[user_id] = ("snack", False)
    USER_STATE[user_id] = "log_meal_calories"
    await update.message.reply_text(
        "Примерные ккалории перекуса? (напиши число)",
        reply_markup=BACK_TO_MENU_MARKUP,
    )


async def meal_log_calories_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "log_meal_calories" or user_id not in PENDING_MEAL:
        return
    text = (update.message.text or "").strip()
    try:
        kcal = int(text.replace(" ", "").replace(",", ".").split(".")[0])
    except (ValueError, AttributeError):
        await update.message.reply_text("Напиши число ккалорий, например 350.")
        return
    if kcal < 0 or kcal > 10000:
        await update.message.reply_text("Укажи разумное число (0–10000).")
        return
    meal_type, stopped_80 = PENDING_MEAL.pop(user_id)
    USER_STATE[user_id] = ""
    session = MEAL_SESSION.pop(user_id, None)
    start_at = session.get("start_at") if session else None
    duration_seconds = session.get("duration_seconds") if session else None
    add_meal(
        user_id,
        meal_type,
        stopped_at_80=stopped_80,
        calories=kcal,
        start_at=start_at,
        duration_seconds=duration_seconds,
    )
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    total = get_calories_today(user_id)
    msg = f"Записано: +{kcal} ккал. Сегодня: {total} ккал из {limit}."
    if duration_seconds is not None:
        msg += f"\nВремя приёма: {duration_seconds // 60} мин."
    if total > limit:
        msg += f"\n⚠️ Превысила лимит на {total - limit} ккал."
    await update.message.reply_text(msg, reply_markup=MAIN_MARKUP)


# ----- Progress (граница 21:00 только в get_settings, настройки убраны) -----
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "📊 Мой прогресс":
        return
    user_id = update.effective_user.id
    meals_today = get_meals_today(user_id)
    streak_snack = get_streak(user_id, "snack_waited")
    impulses_ok = get_impulses_waited_today(user_id)
    calories_today = get_calories_today(user_id)
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)

    lines = [
        "📊 Прогресс",
        "",
        f"🔥 Ккалории сегодня: {calories_today} из {limit}",
    ]
    if calories_today <= limit:
        lines.append(f"   Осталось: {limit - calories_today} ккал")
    else:
        lines.append(f"   ⚠️ Превышение: +{calories_today - limit} ккал")
    eating_sec = get_total_eating_time_today(user_id)
    eating_min = eating_sec // 60
    lines.extend([
        "",
        f"Приёмов пищи сегодня: {len(meals_today)}",
        f"Время за едой сегодня: {eating_min} мин",
        f"Переждала импульс перекуса: {impulses_ok} раз",
        f"Серия (дни подряд): {streak_snack}",
    ])
    if meals_today:
        by_type = {}
        for m in meals_today:
            t = m["meal_type"]
            by_type[t] = by_type.get(t, 0) + 1
        lines.append("")
        lines.append("По типам: " + ", ".join(f"{t}: {c}" for t, c in sorted(by_type.items())))
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MARKUP)


def is_back_to_menu(update: Update) -> bool:
    return (update.message.text or "").strip() == "◀️ В меню"
