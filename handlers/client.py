from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def client_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💼 Розмістити вакансію", callback_data="client_vacancy")],
        [InlineKeyboardButton("👷 Додати резюме", callback_data="client_resume")],
        [InlineKeyboardButton("📢 Реклама / Акції / Відкриття", callback_data="client_promo")],
        [InlineKeyboardButton("🚀 Послуги та ціни", callback_data="client_prices")],
        [InlineKeyboardButton("📞 Контакти", callback_data="client_contacts")],
    ])