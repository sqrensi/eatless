"""Reply and inline keyboards for the bot."""
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

MAIN_KEYS = [
    [KeyboardButton("🍽 Собираюсь поесть")],
    [KeyboardButton("🍪 Хочу перекусить")],
    [KeyboardButton("💧 Записать воду")],
    [KeyboardButton("📊 Мой прогресс")],
]
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYS, resize_keyboard=True)

# Причина перекуса
SNACK_REASON_KEYS = [
    [KeyboardButton("🍽 Голод"), KeyboardButton("😐 Скука")],
    [KeyboardButton("😤 Стресс"), KeyboardButton("🔄 Привычка")],
    [KeyboardButton("✏️ Другое")],
]
SNACK_REASON_MARKUP = ReplyKeyboardMarkup(SNACK_REASON_KEYS, resize_keyboard=True)

# Быстрый выбор объёма воды (мл)
WATER_ML_KEYS = [
    [KeyboardButton("200 мл"), KeyboardButton("250 мл"), KeyboardButton("500 мл")],
    [KeyboardButton("1000 мл"), KeyboardButton("✏️ Свои мл")],
    [KeyboardButton("◀️ В меню")],
]
WATER_ML_MARKUP = ReplyKeyboardMarkup(WATER_ML_KEYS, resize_keyboard=True)

# Во время приёма пищи: закончила / отменить
MEAL_FINISH_KEYS = [
    [KeyboardButton("✅ Закончила приём пищи")],
    [KeyboardButton("◀️ Отменить")],
]
MEAL_FINISH_MARKUP = ReplyKeyboardMarkup(MEAL_FINISH_KEYS, resize_keyboard=True)

# After "Закончила приём пищи"
STOPPED_80_KEYS = [
    [KeyboardButton("✅ Да, вышла из-за стола")],
    [KeyboardButton("🍴 Нет, доела всё")],
]
STOPPED_80_MARKUP = ReplyKeyboardMarkup(STOPPED_80_KEYS, resize_keyboard=True)

# After 10 min snack wait
SNACK_AFTER_KEYS = [
    [KeyboardButton("✅ Нет, прошло")],
    [KeyboardButton("🍪 Уже перекусила :(")],
    [KeyboardButton("😋 Да, хочется")],
]
SNACK_AFTER_MARKUP = ReplyKeyboardMarkup(SNACK_AFTER_KEYS, resize_keyboard=True)

# Тип приёма только для «Собираюсь поесть» (завтрак, обед, ужин)
MEAL_TYPE_MAIN_KEYS = [
    [KeyboardButton("🌅 Завтрак"), KeyboardButton("☀️ Обед")],
    [KeyboardButton("🌙 Ужин")],
]
MEAL_TYPE_MAIN_MARKUP = ReplyKeyboardMarkup(MEAL_TYPE_MAIN_KEYS, resize_keyboard=True)

# Оценка голода (диапазоны 1–10)
HUNGER_KEYS = [
    [KeyboardButton("1–2"), KeyboardButton("3–5")],
    [KeyboardButton("6–7"), KeyboardButton("8–10")],
    [KeyboardButton("◀️ В меню")],
]
HUNGER_MARKUP = ReplyKeyboardMarkup(HUNGER_KEYS, resize_keyboard=True)

# После выбора типа: только ккал или поесть с секундомером
MEAL_MODE_KEYS = [
    [KeyboardButton("📝 Только записать ккал")],
    [KeyboardButton("⏱ Поесть с секундомером")],
]
MEAL_MODE_MARKUP = ReplyKeyboardMarkup(MEAL_MODE_KEYS, resize_keyboard=True)

# После «Да, хочется» — записать перекус
RECORD_SNACK_KEYS = [
    [KeyboardButton("📝 Записать перекус")],
    [KeyboardButton("◀️ В меню")],
]
RECORD_SNACK_MARKUP = ReplyKeyboardMarkup(RECORD_SNACK_KEYS, resize_keyboard=True)

BACK_TO_MENU_KEYS = [[KeyboardButton("◀️ В меню")]]
BACK_TO_MENU_MARKUP = ReplyKeyboardMarkup(BACK_TO_MENU_KEYS, resize_keyboard=True)


def inline_meal_after_20(chat_id: int):
    """Inline buttons for 'stopped at 80%' (for job callback)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, вышла из-за стола", callback_data=f"meal_80_yes_{chat_id}")],
        [InlineKeyboardButton("🍴 Нет, доела всё", callback_data=f"meal_80_no_{chat_id}")],
    ])
