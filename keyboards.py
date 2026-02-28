"""Reply and inline keyboards for the bot."""
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

MAIN_KEYS = [
    [KeyboardButton("🍽 Собираюсь поесть")],
    [KeyboardButton("🍪 Хочу перекусить")],
    [KeyboardButton("📊 Мой прогресс")],
]
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYS, resize_keyboard=True)

# Before meal checklist
WATER_KEYS = [[KeyboardButton("✅ Выпила"), KeyboardButton("⏭ Потом")]]
WATER_MARKUP = ReplyKeyboardMarkup(WATER_KEYS, resize_keyboard=True)

HUNGER_KEYS = [
    [KeyboardButton("1-3"), KeyboardButton("4-5"), KeyboardButton("6-7"), KeyboardButton("8-10")],
]
HUNGER_MARKUP = ReplyKeyboardMarkup(HUNGER_KEYS, resize_keyboard=True)

PLATE_KEYS = [[KeyboardButton("✅ Маленькая тарелка"), KeyboardButton("⏭ Обычная")]]
PLATE_MARKUP = ReplyKeyboardMarkup(PLATE_KEYS, resize_keyboard=True)

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
