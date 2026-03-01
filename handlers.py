"""All bot handlers: start, menu, meal flow, snack, water, progress."""
import asyncio
import logging
import random
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_NAME, MEAL_PHOTOS_DIR
from database import (
    init_db,
    upsert_user,
    get_settings,
    add_meal,
    add_impulse,
    add_water,
    get_meals_today,
    get_calories_today,
    get_total_eating_time_today,
    get_streak,
    increment_streak,
    get_impulses_waited_today,
    get_last_meal_time,
    get_water_today_ml,
    get_all_chat_ids,
    WATER_GOAL_ML,
)
from keyboards import (
    MAIN_MARKUP,
    MEAL_FINISH_MARKUP,
    STOPPED_80_MARKUP,
    SNACK_AFTER_MARKUP,
    SNACK_CAN_WAIT_MARKUP,
    MEAL_TYPE_MAIN_MARKUP,
    RECORD_SNACK_MARKUP,
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
    """Только выбор типа приёма (завтрак/обед/ужин) и старт секундомера."""
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, "")
    text = (update.message.text or "").strip()
    if state != "meal_choose_type":
        await _maybe_meal_80_response(update, context)
        return
    meal_type = MEAL_BUTTON_TO_MAIN_TYPE.get(text)
    if not meal_type:
        return
    USER_STATE[user_id] = ""
    USER_MEAL_START_TYPE[user_id] = meal_type
    USER_IN_MEAL.add(user_id)
    USER_MEAL_START[user_id] = datetime.utcnow()
    chat_id = update.effective_chat.id
    bot = context.bot
    # Сообщения во время еды: мотивация каждые 3 мин, вопросы «наелась?» с 8-й мин каждые 2 мин. Текст — случайный из пула.
    MEAL_MOTIVATION = (
        "Ты молодец, что ешь осознанно. Каждый такой приём — шаг к цели. 💪",
        "Не торопись. Еда никуда не денется. 💚",
        "Ты уже сделала много — один осознанный приём за раз. 🌟",
        "Осознанная еда — это суперсила. Ты справляешься! ✨",
        "Каждый кусочек, который ты чувствуешь — это победа. 🍽",
        "Мяу! Помни: лучше недоесть и взять добавку, чем переесть. 🐱",
        "Ты делаешь важное дело — учишься слышать своё тело. 💪",
        "Не спеши. Наслаждайся вкусом и текстурой. 🌿",
        "Маленькие шаги каждый день — так и меняются привычки. 👣",
        "Ты уже на правильном пути. Продолжай в том же духе! 🌟",
        "Пауза между кусочками — твой друг. Попробуй сделать её. ⏸",
        "Еда будет и завтра. Сегодня — только то, что нужно телу. 💚",
        "Я горжусь тобой. Осознанное питание — это не про диету, а про заботу. 🐾",
        "Каждый приём — новая возможность прислушаться к себе. 🎯",
        "Ты молодец. Не сравнивай себя с другими — только с собой вчера. 💫",
    )
    MEAL_FULL_QUESTIONS = (
        "Мяу! Может ты уже наелась? 🤔",
        "Прислушайся к себе: уже сыто?",
        "Мяу! Как ощущения в животике?",
        "Ты ещё голодна или уже достаточно?",
        "Проверь: может, организм уже получил сигнал «стоп»? 🐱",
        "Как там внутри — ещё есть место или пора закругляться?",
        "Мяу! Не забывай: можно остановиться на 80% сытости. Как ты сейчас?",
        "Ощущения в теле подсказывают — ещё еда или уже хватит?",
        "Ты по-прежнему голодна или уже комфортно? 💚",
        "Мяу! Пауза: ты действительно ещё хочешь есть?",
        "Попробуй сделать глоток воды и спросить себя: я ещё голодна?",
        "Как тебе сейчас — лёгкость или тяжесть?",
        "Мяу! Не доедать «за компанию» с тарелкой — норма. Ты как?",
        "Ещё хочется или уже пора сказать «спасибо, я сыта»?",
        "Проверь животик: он доволен или просит ещё? 🐾",
    )
    asyncio.create_task(_meal_messages_loop(bot, chat_id, user_id, MEAL_MOTIVATION, MEAL_FULL_QUESTIONS))
    await update.message.reply_text(
        "Секундомер запущен. Ешь спокойно. Когда закончишь — нажми «Закончила приём пищи».",
        reply_markup=MEAL_FINISH_MARKUP,
    )


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
    """Цикл сообщений во время еды: мотивация каждые 3 мин; «наелась?» с 8-й мин каждые 2 мин. Один lock — не слать два фото одновременно (иначе один запрос упирается в таймаут)."""
    interval_sec = 3 * 60
    full_first_sec = 8 * 60
    full_interval_sec = 2 * 60
    send_lock = asyncio.Lock()
    logger.info("meal messages loop started (motivation first in %s sec)", interval_sec)

    async def motivation_task():
        for _ in range(10):
            await asyncio.sleep(interval_sec)
            if user_id not in USER_IN_MEAL:
                return
            try:
                text = random.choice(motivation_texts)
                async with send_lock:
                    await _send_meal_message_with_bot(bot, chat_id, text)
            except Exception as e:
                logger.warning("meal motivation send: %s", e)

    async def full_task():
        await asyncio.sleep(full_first_sec)
        for i in range(10):
            if user_id not in USER_IN_MEAL:
                return
            try:
                text = random.choice(full_questions)
                async with send_lock:
                    await _send_meal_message_with_bot(bot, chat_id, text)
            except Exception as e:
                logger.warning("meal full question send: %s", e)
            if i < 9:
                await asyncio.sleep(full_interval_sec)

    await asyncio.gather(motivation_task(), full_task())


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


# ----- Snack: только через 1+ час после последнего приёма; вопрос «подождать 10 мин?» -----
USER_AWAITING_SNACK: set[int] = set()
SNACK_MIN_INTERVAL_MINUTES = 60


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
    USER_STATE[user_id] = "snack_can_wait"
    await update.message.reply_text(
        "Сможешь подождать 10 минут? Если да — через 10 минут спрошу, не перехотелось ли. Если нет — сразу запишем перекус.",
        reply_markup=SNACK_CAN_WAIT_MARKUP,
    )


async def snack_can_wait_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ответа «Да, подожду» / «Нет, не могу» после вопроса про 10 минут."""
    user_id = update.effective_user.id
    if USER_STATE.get(user_id) != "snack_can_wait":
        return
    text = (update.message.text or "").strip()
    if "Нет, не могу" in text or "не могу" in text.lower():
        USER_STATE[user_id] = "log_meal_calories"
        PENDING_MEAL[user_id] = ("snack", False)
        await update.message.reply_text(
            "Ок, записываем перекус. Примерные ккалории? (напиши число)",
            reply_markup=BACK_TO_MENU_MARKUP,
        )
        return
    if "Да, подожду" in text or "подожду" in text.lower():
        USER_STATE[user_id] = ""
        USER_AWAITING_SNACK.add(user_id)
        job_queue = context.application.job_queue
        t10_sec = 10 * 60
        if job_queue:
            job_queue.run_once(
                _snack_10min,
                t10_sec,
                data={"chat_id": update.effective_chat.id, "user_id": user_id},
            )
        msg = "Подожди 10 минут. Через 10 минут спрошу: не перехотелось ли перекусывать."
        await update.message.reply_text(msg)
        return


async def _snack_10min(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if not job or not job.data:
        return
    await context.bot.send_message(
        job.data["chat_id"],
        "Прошло 10 минут. Не перехотелось перекусывать?",
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


# ----- Progress -----
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != "📊 Мой прогресс":
        return
    user_id = update.effective_user.id
    meals_today = get_meals_today(user_id)
    streak_snack = get_streak(user_id, "snack_waited")
    impulses_ok = get_impulses_waited_today(user_id)
    calories_today = get_calories_today(user_id)
    limit = get_settings(user_id).get("daily_calorie_limit", 1700)
    water_today = get_water_today_ml(user_id)

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


# ----- Напоминания в течение дня -----
async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рассылка: «Ты сейчас случайно не ешь?»"""
    for chat_id in get_all_chat_ids():
        try:
            await context.bot.send_message(chat_id, "Ты сейчас случайно не ешь? 🤔")
        except Exception:
            pass


async def water_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рассылка: «Попей воды»"""
    for chat_id in get_all_chat_ids():
        try:
            await context.bot.send_message(chat_id, "💧 Попей воды!")
        except Exception:
            pass
