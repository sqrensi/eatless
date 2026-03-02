"""Telegram bot: eat less, mindful eating."""
import asyncio
import logging
from datetime import time as dt_time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from database import init_db
from handlers import (
    start,
    backup,
    report,
    main_menu,
    meal_start,
    meal_checklist,
    meal_hunger_input,
    meal_choose_mode,
    meal_finish,
    meal_cancel,
    meal_log_calories_input,
    snack_start,
    snack_reason_input,
    water_start,
    water_ml_input,
    progress,
    water_reminder_job,
    is_back_to_menu,
    _maybe_meal_80_response,
    USER_STATE,
    USER_AWAITING_80,
    USER_IN_MEAL,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def message_router(update: Update, context) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if is_back_to_menu(update):
        await main_menu(update, context)
        return

    if user_id in USER_AWAITING_80:
        if await _maybe_meal_80_response(update, context):
            return

    if user_id in USER_IN_MEAL:
        if "Закончила приём пищи" in text:
            await meal_finish(update, context)
            return
        if "Отменить" in text:
            await meal_cancel(update, context)
            return
        # Игнорируем остальное во время еды (или можно отправить "Нажми кнопку выше")
        return

    state = USER_STATE.get(user_id, "")
    if state == "log_meal_calories":
        await meal_log_calories_input(update, context)
        return
    if state == "snack_reason":
        await snack_reason_input(update, context)
        return
    if state == "water_ml":
        await water_ml_input(update, context)
        return

    if state == "meal_choose_type":
        await meal_checklist(update, context)
        return
    if state == "meal_hunger":
        await meal_hunger_input(update, context)
        return
    if state == "meal_choose_mode":
        await meal_choose_mode(update, context)
        return

    if text == "🍽 Собираюсь поесть":
        await meal_start(update, context)
        return
    if text == "🍪 Хочу перекусить":
        await snack_start(update, context)
        return
    if text == "💧 Записать воду":
        await water_start(update, context)
        return
    if text == "📊 Мой прогресс":
        await progress(update, context)
        return

    await main_menu(update, context)


def main() -> None:
    # Python 3.10+: в главном потоке нет event loop по умолчанию — создаём явно
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    init_db()
    # Пул соединений и таймауты: чтобы send_photo не ждал в очереди за getUpdates (иначе кот может идти 50+ сек).
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connection_pool_size(8)
        .pool_timeout(30.0)
        .read_timeout(30)
        .write_timeout(30)
        .media_write_timeout(60)
        .build()
    )

    if app.job_queue:
        # Вода: 10, 14, 18, 22 (интервал 4 ч). Напоминаем только если выпито меньше порога за день.
        app.job_queue.run_daily(water_reminder_job, time=dt_time(hour=10, minute=0), data={"threshold": 0})
        app.job_queue.run_daily(water_reminder_job, time=dt_time(hour=14, minute=0), data={"threshold": 400})
        app.job_queue.run_daily(water_reminder_job, time=dt_time(hour=18, minute=0), data={"threshold": 800})
        app.job_queue.run_daily(water_reminder_job, time=dt_time(hour=22, minute=0), data={"threshold": 1200})

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
