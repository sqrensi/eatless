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
    main_menu,
    meal_start,
    meal_checklist,
    meal_finish,
    meal_cancel,
    meal_log_calories_input,
    record_snack_ask_calories,
    snack_start,
    snack_can_wait_answer,
    snack_after,
    water_start,
    water_ml_input,
    progress,
    reminder_job,
    water_reminder_job,
    is_back_to_menu,
    _maybe_meal_80_response,
    USER_STATE,
    USER_AWAITING_80,
    USER_AWAITING_SNACK,
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

    if user_id in USER_AWAITING_SNACK:
        await snack_after(update, context)
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
    if state == "snack_will_log":
        if "Записать перекус" in text:
            await record_snack_ask_calories(update, context)
            return
        return
    if state == "snack_can_wait":
        await snack_can_wait_answer(update, context)
        return
    if state == "water_ml":
        await water_ml_input(update, context)
        return

    if state == "meal_choose_type":
        await meal_checklist(update, context)
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
    app = Application.builder().token(BOT_TOKEN).build()

    if app.job_queue:
        # «Ты сейчас не ешь?» — чаще в течение дня
        for hour in (10, 12, 15, 18, 20):
            app.job_queue.run_daily(reminder_job, time=dt_time(hour=hour, minute=0))
        # «Попей воды»
        for hour in (9, 11, 14, 17, 19):
            app.job_queue.run_daily(water_reminder_job, time=dt_time(hour=hour, minute=0))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
