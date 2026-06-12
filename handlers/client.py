from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def client_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💼 Розмістити вакансію", callback_data="client_vacancy")],
        [InlineKeyboardButton("👷 Додати резюме", callback_data="client_resume")],
        [InlineKeyboardButton("📢 Реклама / Акції / Відкриття", callback_data="client_promo")],
        [InlineKeyboardButton("🚀 Послуги та ціни", callback_data="client_prices")],
        [InlineKeyboardButton("📞 Контакти", callback_data="client_contacts")],
    ])


def back_home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Головне меню", callback_data="client_home")]
    ])


async def client_buttons(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "client_home":
        await query.message.reply_text(
            "🇺🇦 HireUA\n\nОберіть потрібний розділ 👇",
            reply_markup=client_main_keyboard(),
        )

    elif data == "client_vacancy":
        await query.message.reply_text(
            "Вкажіть інформацію про вакансію:\n\n"
            "🏢 Назва компанії:\n"
            "💼 Посада:\n"
            "📍 Місто:\n"
            "💰 Зарплата:\n"
            "📋 Обов'язки:\n"
            "📞 Контакти:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_resume":
        await query.message.reply_text(
            "Вкажіть інформацію про резюме:\n\n"
            "👤 Ім'я:\n"
            "📍 Місто:\n"
            "💼 Бажана посада:\n"
            "💰 Бажана зарплата:\n"
            "📞 Контакти:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_promo":
        await query.message.reply_text(
            "📢 Реклама / Акції / Відкриття\n\n"
            "🏢 Назва компанії:\n"
            "📢 Що рекламуємо:\n"
            "📍 Місто:\n"
            "📅 Дата проведення:\n"
            "📞 Контакти:\n"
            "📝 Опис:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_prices":
        await query.message.reply_text(
            "🆓 БЕЗКОШТОВНО\n\n"
            "📢 3 текстові публікації на день\n\n"
            "✅ Telegram канал обраного міста\n\n"
            "📅 Термін розміщення:\n"
            "1 • 3 • 7 • 14 • 21 • 30 днів\n\n"
            "🔄 Якщо вакансія залишається актуальною, термін розміщення можна продовжити\n\n\n"
            "🚀 Start — 4500 грн / 7 днів\n\n"
            "📢 84 публікації за 7 днів\n"
            "(3 публікації на день на кожній платформі)\n\n"
            "✅ Telegram\n"
            "✅ Facebook\n"
            "✅ Instagram\n"
            "✅ YouTube\n\n"
            "🎨 Банер — розробка та просування включено\n\n\n"
            "🚀🚀 Business — 7500 грн / 7 днів\n\n"
            "📢 168 публікацій за 7 днів\n"
            "(6 публікації на день на кожній платформі)\n\n"
            "✅ Telegram\n"
            "✅ Facebook\n"
            "✅ Instagram\n"
            "✅ YouTube\n\n"
            "🎨 Банер — розробка та просування включено\n"
            "🎥 Reels / Shorts — розробка та просування включено\n"
            "🤖 Відео з Тімом — розробка та просування включено",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_contacts":
        await query.message.reply_text(
            "📞 HR менеджер: @HireUkraine",
            reply_markup=back_home_keyboard(),
        )
        
        