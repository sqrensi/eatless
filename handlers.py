"""All bot handlers: start, menu, meal flow, snack, water, progress."""
import asyncio
import logging
import random
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_NAME, MEAL_PHOTOS_DIR, CAT_PHOTOS_DIR, DB_PATH, BACKUP_USER_ID
from database import (
    init_db,
    upsert_user,
    get_settings,
    add_meal,
    add_water,
    get_meals_today,
    get_all_meals,
    get_calories_today,
    get_calories_for_date,
    get_water_for_date,
    get_total_eating_time_today,
    get_last_meal_time,
    get_water_today_ml,
    get_users_with_chat_id,
    get_cat_sent_today,
    mark_cat_sent,
    get_days_overfed_count,
    WATER_GOAL_ML,
)
from keyboards import (
    MAIN_MARKUP,
    MEAL_FINISH_MARKUP,
    HUNGER_MARKUP,
    MEAL_MODE_MARKUP,
    STOPPED_80_MARKUP,
    SNACK_REASON_MARKUP,
    MEAL_TYPE_MAIN_MARKUP,
    WATER_ML_MARKUP,
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
# Оценка голода 1–10 перед приёмом (до выбора «только ккал» / «с секундомером»)
USER_MEAL_HUNGER: dict[int, int] = {}
# Причина перекуса (hunger/boredom/stress/habit/other) до ввода ккалорий
PENDING_SNACK_REASON: dict[int, str] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not user:
        return
    upsert_user(user.id, user.username, user.first_name, chat_id=chat_id)
    USER_STATE[user.id] = ""
    await update.message.reply_text(
        f"Мяу! Я {BOT_NAME}, кот-помогатор. Помогу тебе есть меньше и осознаннее.\n\n"
        "• Собираешься поесть — выбери завтрак/обед/ужин, запустится секундомер.\n"
        "• Перекус — только через час после последнего приёма; спрошу, сможешь ли подождать 10 минут.\n"
        "• Вода — цель 2 л в день. Записывай, сколько выпила.\n\n"
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
    USER_MEAL_HUNGER.pop(user_id, None)
    PENDING_SNACK_REASON.pop(user_id, None)
    MEAL_SESSION.pop(user_id, None)
    await update.message.reply_text(f"Мяу! Главное меню. Что делаем? 👇", reply_markup=MAIN_MARKUP)


# ----- Meal flow: сразу выбор типа -> секундомер (без чек-листа) -----


async def meal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "🍽 Собираюсь поесть":
        return
    user_id = update.effective_user.id
    USER_STATE[user_id] = "meal_choose_type"
    await update.message.reply_text(
        "Какой приём? Выбери: завтрак, обед или ужин.",
        reply_markup=MEAL_TYPE_MAIN_MARKUP,
    )


async def meal_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выбор типа приёма (завтрак/обед/ужин) → оценка голода 1–10 → только ккал или с секундомером."""
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, "")
    text = (update.message.text or "").strip()
    if state != "meal_choose_type":
        await _maybe_meal_80_response(update, context)
        return
    meal_type = MEAL_BUTTON_TO_MAIN_TYPE.get(text)
    if not meal_type:
        return
    USER_STATE[user_id] = "meal_hunger"
    USER_MEAL_START_TYPE[user_id] = meal_type
    await update.message.reply_text(
        "Оценка голода от 1 до 10? (1 — совсем не голодна, 10 — очень голодна)",
        reply_markup=HUNGER_MARKUP,
    )


# Кнопки оценки голода -> значение для БД (верх границы диапазона)
HUNGER_BUTTON_TO_VALUE = {"1–2": 2, "3–5": 5, "6–7": 7, "8–10": 10}


async def meal_hunger_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принятие оценки голода по кнопке (1–2, 3–5, 6–7, 8–10) и переход к выбору режима приёма."""
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "meal_hunger":
        return
    text = (update.message.text or "").strip()
    h = HUNGER_BUTTON_TO_VALUE.get(text)
    if h is None:
        return
    USER_MEAL_HUNGER[user_id] = h
    USER_STATE[user_id] = "meal_choose_mode"
    await update.message.reply_text(
        "Записать только ккал или поесть с секундомером?",
        reply_markup=MEAL_MODE_MARKUP,
    )


async def meal_choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка выбора: «Только записать ккал» или «Поесть с секундомером»."""
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "meal_choose_mode":
        return
    text = (update.message.text or "").strip()
    meal_type = USER_MEAL_START_TYPE.get(user_id, "meal")
    if "Только записать ккал" in text or "только записать" in text.lower():
        USER_STATE[user_id] = "log_meal_calories"
        PENDING_MEAL[user_id] = (meal_type, False)
        USER_MEAL_START_TYPE.pop(user_id, None)
        await update.message.reply_text(
            "Примерные ккалории? (напиши число)",
            reply_markup=BACK_TO_MENU_MARKUP,
        )
        return
    if "Поесть с секундомером" in text or "секудомером" in text.lower():
        USER_STATE[user_id] = ""
        USER_IN_MEAL.add(user_id)
        USER_MEAL_START[user_id] = datetime.utcnow()
        chat_id = update.effective_chat.id
        bot = context.bot
        MEAL_MOTIVATION = (
            "Ты молодец, что ешь осознанно. Каждый такой приём — шаг к цели. 💪",
            "Не торопись. Еда никуда не денется. 💚",
            "Ты уже сделала много — один осознанный приём за раз. 🌟",
        )
        MEAL_FULL_QUESTIONS = (
            "Мяу! Может ты уже наелась? 🤔",
            "Прислушайся к себе: уже сыто?",
            "Мяу! Как ощущения в животике?",
        )
        asyncio.create_task(_meal_messages_loop(bot, chat_id, user_id, MEAL_MOTIVATION, MEAL_FULL_QUESTIONS))
        await update.message.reply_text(
            "Секундомер запущен. Ешь спокойно. Когда закончишь — нажми «Закончила приём пищи».",
            reply_markup=MEAL_FINISH_MARKUP,
        )
        return


def _get_random_meal_photo_path() -> Path | None:
    """Случайное фото из папки для сообщений во время еды."""
    if not MEAL_PHOTOS_DIR.is_dir():
        logger.debug("meal photos dir not found: %s", MEAL_PHOTOS_DIR)
        return None
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    paths = [p for p in MEAL_PHOTOS_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not paths:
        logger.debug("no images in meal photos dir: %s", MEAL_PHOTOS_DIR)
    return random.choice(paths) if paths else None


async def _send_meal_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Отправить сообщение во время еды: с фото (если есть) или только текст."""
    photo_path = _get_random_meal_photo_path()
    if photo_path:
        try:
            await context.bot.send_photo(chat_id, photo=str(photo_path.resolve()), caption=text)
        except Exception:
            await context.bot.send_message(chat_id, text)
    else:
        await context.bot.send_message(chat_id, text)


async def _send_meal_message_with_bot(bot, chat_id: int, text: str) -> None:
    """Отправить сообщение во время еды с фото (если есть). При ошибке — только текст."""
    photo_path = _get_random_meal_photo_path()
    if photo_path:
        try:
            await bot.send_photo(chat_id, photo=str(photo_path.resolve()), caption=text)
        except Exception as e:
            logger.warning("meal photo send failed, sending text only: %s", e)
            try:
                await bot.send_message(chat_id, text)
            except Exception as e2:
                logger.error("meal message send failed: %s", e2)
    else:
        await bot.send_message(chat_id, text)


async def _meal_messages_loop(bot, chat_id: int, user_id: int, motivation_texts: list, full_questions: list) -> None:
    """Во время еды: 1 мотивация через 8 мин, 1 вопрос «наелась?» через 13 мин."""
    send_lock = asyncio.Lock()
    # 8 мин — мотивация
    await asyncio.sleep(8 * 60)
    if user_id not in USER_IN_MEAL:
        return
    try:
        async with send_lock:
            await _send_meal_message_with_bot(bot, chat_id, random.choice(motivation_texts))
    except Exception as e:
        logger.warning("meal motivation send: %s", e)
    # ещё 5 мин (итого 13 от старта) — вопрос
    await asyncio.sleep(5 * 60)
    if user_id not in USER_IN_MEAL:
        return
    try:
        async with send_lock:
            await _send_meal_message_with_bot(bot, chat_id, random.choice(full_questions))
    except Exception as e:
        logger.warning("meal full question send: %s", e)


async def _meal_chat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сообщение во время еды (вопрос «наелась?» или мотивация). Текст в job.data["text"]."""
    job = context.job
    if not job or not job.data:
        return
    if job.data["user_id"] not in USER_IN_MEAL:
        return
    await _send_meal_message(context, job.data["chat_id"], job.data["text"])


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


# ----- Snack: только через 1+ час после последнего приёма; причина перекуса, без ожидания 10 мин -----
SNACK_MIN_INTERVAL_MINUTES = 60
SNACK_REASON_BUTTON_TO_CODE = {
    "🍽 Голод": "hunger",
    "😐 Скука": "boredom",
    "😤 Стресс": "stress",
    "🔄 Привычка": "habit",
    "✏️ Другое": "other",
}


async def snack_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "🍪 Хочу перекусить":
        return
    user_id = update.effective_user.id
    last = get_last_meal_time(user_id)
    if last:
        now_utc = datetime.utcnow()
        last_naive = last.replace(tzinfo=None) if getattr(last, "tzinfo", None) else last
        elapsed_sec = (now_utc - last_naive).total_seconds()
        need_wait_sec = max(0, SNACK_MIN_INTERVAL_MINUTES * 60 - elapsed_sec)
        if need_wait_sec > 0:
            wait_min = int(need_wait_sec / 60)
            await update.message.reply_text(
                f"Мяу! Перекус можно только через час после последнего приёма. Подожди ещё {wait_min} мин.",
                reply_markup=MAIN_MARKUP,
            )
            return
    USER_STATE[user_id] = "snack_reason"
    await update.message.reply_text(
        "Почему перекус? Выбери причину.",
        reply_markup=SNACK_REASON_MARKUP,
    )


async def snack_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выбор причины перекуса → запрос ккалорий."""
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "snack_reason":
        return
    text = (update.message.text or "").strip()
    reason = SNACK_REASON_BUTTON_TO_CODE.get(text)
    if not reason:
        # «Другое» можно написать текстом — сохраняем как other
        if "Другое" in text or "другое" in text.lower():
            reason = "other"
        else:
            reason = "other"
    PENDING_SNACK_REASON[user_id] = reason
    PENDING_MEAL[user_id] = ("snack", False)
    USER_STATE[user_id] = "log_meal_calories"
    await update.message.reply_text(
        "Примерные ккалории перекуса? (напиши число)",
        reply_markup=BACK_TO_MENU_MARKUP,
    )


# Тип приёма: только завтрак, обед, ужин (для «Собираюсь поесть»)
MEAL_BUTTON_TO_MAIN_TYPE = {
    "🌅 Завтрак": "breakfast",
    "☀️ Обед": "lunch",
    "🌙 Ужин": "dinner",
}


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
    hunger = USER_MEAL_HUNGER.pop(user_id, None)
    snack_reason = PENDING_SNACK_REASON.pop(user_id, None) if meal_type == "snack" else None
    add_meal(
        user_id,
        meal_type,
        stopped_at_80=stopped_80,
        calories=kcal,
        start_at=start_at,
        duration_seconds=duration_seconds,
        hunger=hunger,
        snack_reason=snack_reason,
    )
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    total = get_calories_today(user_id)
    msg = f"Записано: +{kcal} ккал. Сегодня: {total} ккал из {limit}."
    if duration_seconds is not None:
        msg += f"\nВремя приёма: {duration_seconds // 60} мин."
    if total > limit:
        msg += f"\n⚠️ Превысила лимит на {total - limit} ккал."
    await update.message.reply_text(msg, reply_markup=MAIN_MARKUP)
    # Антипрогресс: при переходе границ ккалорий — фото толстеющего кота
    chat_id = update.effective_chat.id
    asyncio.create_task(send_cat_antiprogress_if_needed(context.bot, user_id, chat_id))


# ----- Вода: цель 2 л в день -----
WATER_ML_BUTTONS = {"200 мл": 200, "250 мл": 250, "500 мл": 500, "1000 мл": 1000}


async def water_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "💧 Записать воду":
        return
    user_id = update.effective_user.id
    USER_STATE[user_id] = "water_ml"
    today = get_water_today_ml(user_id)
    await update.message.reply_text(
        f"Сколько выпила? Цель: {WATER_GOAL_ML} мл в день. Сегодня уже: {today} мл.",
        reply_markup=WATER_ML_MARKUP,
    )


async def water_ml_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "water_ml":
        return
    text = (update.message.text or "").strip()
    if "В меню" in text or text == "◀️ В меню":
        USER_STATE[user_id] = ""
        await update.message.reply_text("Ок.", reply_markup=MAIN_MARKUP)
        return
    if text == "✏️ Свои мл":
        await update.message.reply_text("Введи количество в мл (числом, например 350):", reply_markup=WATER_ML_MARKUP)
        return
    ml = WATER_ML_BUTTONS.get(text)
    if ml is None:
        try:
            ml = int(text.replace(" ", "").replace("мл", "").strip())
        except (ValueError, AttributeError):
            await update.message.reply_text("Напиши число мл или выбери кнопку.")
            return
    if ml <= 0 or ml > 5000:
        await update.message.reply_text("Укажи объём от 1 до 5000 мл.")
        return
    add_water(user_id, ml)
    USER_STATE[user_id] = ""
    total = get_water_today_ml(user_id)
    msg = f"Записано +{ml} мл. Сегодня: {total} мл из {WATER_GOAL_ML} мл."
    if total >= WATER_GOAL_ML:
        msg += " Цель достигнута! 💧"
    await update.message.reply_text(msg, reply_markup=MAIN_MARKUP)


def _streak_limit_and_water(user_id: int) -> int:
    """Серия дней подряд (включая сегодня), когда уложилась в лимит ккалорий и выполнила норму воды."""
    from datetime import date, timedelta
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    streak = 0
    d = date.today()
    for _ in range(366):
        day_str = d.isoformat()
        cal = get_calories_for_date(user_id, day_str)
        wat = get_water_for_date(user_id, day_str)
        if cal <= limit and wat >= WATER_GOAL_ML:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


# ----- Progress -----
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "📊 Мой прогресс":
        return
    user_id = update.effective_user.id
    meals_today = get_meals_today(user_id)
    calories_today = get_calories_today(user_id)
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    water_today = get_water_today_ml(user_id)
    streak = _streak_limit_and_water(user_id)

    lines = [
        "📊 Прогресс",
        "",
        f"🔥 Ккалории сегодня: {calories_today} из {limit}",
    ]
    if calories_today <= limit:
        lines.append(f"   Осталось: {limit - calories_today} ккал")
    else:
        lines.append(f"   ⚠️ Превышение: +{calories_today - limit} ккал")
    lines.extend([
        "",
        f"💧 Вода сегодня: {water_today} мл / {WATER_GOAL_ML} мл",
    ])
    eating_sec = get_total_eating_time_today(user_id)
    eating_min = eating_sec // 60
    overfed_days = get_days_overfed_count(user_id)
    lines.extend([
        "",
        f"Приёмов пищи сегодня: {len(meals_today)}",
        f"Время за едой сегодня: {eating_min} мин",
        f"Серия (дни подряд: лимит ккал + вода): {streak}",
        f"Дней раскормили кота: {overfed_days}",
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


# ----- Цель на день и антипрогресс (кот) -----
def _get_cat_photo_path(index: int) -> Path | None:
    """Фото кота по индексу: 0 = худой (цель), 1–5 = толстеющий. Файлы в папке сортируются по имени."""
    if not CAT_PHOTOS_DIR.is_dir():
        return None
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    paths = sorted(p for p in CAT_PHOTOS_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts)
    if index < 0 or index >= len(paths):
        return None
    return paths[index]


def _compress_photo_for_telegram(photo_path: Path, max_size: int = 1280, quality: int = 82) -> BytesIO | None:
    """Сжимает фото для отправки в Telegram (уменьшает таймауты). Возвращает BytesIO с JPEG или None при ошибке."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("PIL not installed, cat photo will be sent uncompressed")
        return None
    try:
        orig_size = photo_path.stat().st_size
        img = Image.open(photo_path)
        w0, h0 = img.size
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_size:
            img.thumbnail((max_size, max_size), getattr(Image, "Resampling", Image).LANCZOS)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        buf.seek(0)
        compressed_size = buf.getbuffer().nbytes
        logger.info(
            "cat photo compressed: path=%s orig=%d bytes (%dx%d) -> %d bytes (%dx%d)",
            photo_path.name, orig_size, w0, h0, compressed_size, img.width, img.height,
        )
        return buf
    except Exception as e:
        logger.warning("compress photo failed %s: %s", photo_path, e, exc_info=True)
        return None


# Полоски ккалорий для антипрогресса: 20% — 1 кот, 40% — 2, 60% — 3, 80% — 4, 110% — 5-й (расскормили).
CAT_CALORIE_BOUNDARY_RATIOS = [0.2, 0.4, 0.6, 0.8, 1.1]


def _current_cat_bracket(total: int, limit: int) -> int:
    """Индекс полочки 0–4 по соотношению total/limit. -1 если ниже 20%."""
    if limit <= 0:
        return -1
    ratio = total / limit
    if ratio < 0.2:
        return -1
    for i, r in enumerate(CAT_CALORIE_BOUNDARY_RATIOS):
        if ratio < r:
            return i - 1
    return 4  # 120%+


async def send_cat_antiprogress_if_needed(bot, user_id: int, chat_id: int) -> None:
    """При повышении ккалорий: присылаем одного кота по ближайшей пройденной границе (текущей полочке). Последний кот — «Кота расскормили», дальше сегодня не присылаем."""
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    total = get_calories_today(user_id)
    sent = get_cat_sent_today(user_id)
    # Уже присылали последнего кота — больше сегодня не присылаем
    if "boundary_4" in sent:
        return
    bracket = _current_cat_bracket(total, limit)
    if bracket < 0:
        return
    key = f"boundary_{bracket}"
    if key in sent:
        return
    photo_path = _get_cat_photo_path(bracket + 1)
    if not photo_path:
        logger.warning("cat photo not found for bracket %s (index %s)", bracket, bracket + 1)
        return
    file_size_bytes = photo_path.stat().st_size
    caption = "Кота расскормили 😿" if bracket == 4 else "Мяу… не расскорми кота 😿"
    t0 = time.perf_counter()
    payload_size = file_size_bytes
    try:
        photo = _compress_photo_for_telegram(photo_path)
        payload_size = photo.getbuffer().nbytes if photo else file_size_bytes
        source = "compressed" if photo else "raw_file"
        logger.info(
            "cat send_photo start: user_id=%s chat_id=%s bracket=%s path=%s source=%s payload_bytes=%s",
            user_id, chat_id, bracket, photo_path.name, source, payload_size,
        )
        if photo:
            await bot.send_photo(chat_id, photo=photo, caption=caption)
        else:
            await bot.send_photo(chat_id, photo=str(photo_path.resolve()), caption=caption)
        elapsed = time.perf_counter() - t0
        logger.info("cat send_photo ok: user_id=%s bracket=%s elapsed_sec=%.2f", user_id, bracket, elapsed)
        mark_cat_sent(user_id, key)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.warning(
            "cat antiprogress send failed: user_id=%s bracket=%s path=%s payload_bytes=%s elapsed_sec=%.2f type=%s msg=%s",
            user_id, bracket, photo_path.name, payload_size, elapsed, type(e).__name__, e,
            exc_info=True,
        )
        # При таймауте Telegram мог уже отправить фото — помечаем отправку, чтобы не слать того же кота повторно
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            mark_cat_sent(user_id, key)


# ----- Напоминания в течение дня -----
async def water_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Напоминание о воде только тем, у кого сегодня выпито меньше порога (job.data['threshold']). Интервал 4 ч: 10, 14, 18, 22."""
    job = context.job
    threshold = (job.data or {}).get("threshold", 0)
    for user_id, chat_id in get_users_with_chat_id():
        if get_water_today_ml(user_id) < threshold:
            try:
                await context.bot.send_message(chat_id, "💧 Попей воды! Цель — 2 л в день.")
            except Exception:
                pass


async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /backup: отправить файл БД в чат (только если BACKUP_USER_ID в .env совпадает с user_id)."""
    if not update.effective_user:
        return
    if BACKUP_USER_ID is None or update.effective_user.id != BACKUP_USER_ID:
        await update.message.reply_text("Недоступно.")
        return
    if not DB_PATH.exists():
        await update.message.reply_text("Файл БД не найден.")
        return
    try:
        with open(DB_PATH, "rb") as f:
            await update.message.reply_document(document=f, filename=DB_PATH.name)
    except Exception as e:
        logger.exception("backup send failed")
        await update.message.reply_text(f"Ошибка: {e}")


# user_id по умолчанию для /report (отчёт по дням)
REPORT_DEFAULT_USER_ID = 1180871036


def _format_meals_report(user_id: int) -> str:
    """Отчёт по дням: приёмы и перекусы + сумма ккал за каждый день (дни от новых к старым)."""
    meals = get_all_meals(user_id)
    if not meals:
        return f"Пользователь {user_id}: записей о приёмах пищи нет."
    main_ru = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}
    by_day: dict[str, list] = {}
    for m in meals:
        day = m.get("day") or (m["at"][:10] if m.get("at") else "?")
        by_day.setdefault(day, []).append(m)
    days_sorted = sorted(by_day.keys(), reverse=True)
    lines = [f"📋 Приёмы пищи (user {user_id})", ""]
    for day in days_sorted:
        day_meals = by_day[day]
        lines.append(f"📅 {day}")
        lines.append("")
        for m in day_meals:
            at = m.get("at") or ""
            time_str = at[11:16] if len(at) >= 16 else "—"
            kcal = m["calories"] or 0
            dur = m.get("duration_seconds")
            name = main_ru.get(m["meal_type"], "Перекус" if m["meal_type"] == "snack" else m["meal_type"])
            line = f"  {time_str}  {name}: {kcal} ккал"
            if dur:
                line += f"  ({dur // 60} мин)"
            lines.append(line)
        day_total = sum(m["calories"] or 0 for m in day_meals)
        lines.append(f"  Итого за день: {day_total} ккал")
        lines.append("")
    return "\n".join(lines).strip()


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /report — отчёт по пользователю 1180871036 по дням. Только для BACKUP_USER_ID."""
    if not update.effective_user:
        return
    if BACKUP_USER_ID is None or update.effective_user.id != BACKUP_USER_ID:
        await update.message.reply_text("Недоступно.")
        return
    args = context.args or []
    if args and args[0].isdigit():
        user_id = int(args[0])
    else:
        user_id = REPORT_DEFAULT_USER_ID
    try:
        text = _format_meals_report(user_id)
        await update.message.reply_text(text)
    except Exception as e:
        logger.exception("report failed")
        await update.message.reply_text(f"Ошибка: {e}")
