from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def client_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💼 Розмістити вакансію", callback_data="client_vacancy")],
        [InlineKeyboardButton("🚀 Послуги та ціни", callback_data="client_prices")],
        [InlineKeyboardButton("👷 Додати резюме", callback_data="client_resume")],
        [InlineKeyboardButton("📢 Просування бізнесу", callback_data="client_promo")],
        [InlineKeyboardButton("📞 Контакти", callback_data="client_contacts")],
    ])


def vacancy_tariff_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆓 БЕЗКОШТОВНО", callback_data="vacancy_free")],
        [InlineKeyboardButton("🚀 Start — 4500 грн", callback_data="vacancy_start")],
        [InlineKeyboardButton("🚀🚀 Business — 7500 грн", callback_data="vacancy_business")],
        [InlineKeyboardButton("🎨 Замовити банер — 500 грн", callback_data="vacancy_banner")],
        [InlineKeyboardButton("🎥 Замовити Reels / Shorts — 800 грн", callback_data="vacancy_reels")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="client_home")],
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
            "👨‍💼 Розмістити вакансію\n\n"
            "Оберіть тариф або послугу 👇",
            reply_markup=vacancy_tariff_keyboard(),
        )

    elif data == "vacancy_free":
        await query.message.reply_text(
            "🆓 БЕЗКОШТОВНО\n\n"
            "Починаємо заповнення вакансії.\n\n"
            "🏢 Вкажіть назву компанії:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "vacancy_start":
        await query.message.reply_text(
            "🚀 Start — 4500 грн\n\n"
            "Починаємо заповнення заявки.\n\n"
            "🏢 Вкажіть назву компанії:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "vacancy_business":
        await query.message.reply_text(
            "🚀🚀 Business — 7500 грн\n\n"
            "Починаємо заповнення заявки.\n\n"
            "🏢 Вкажіть назву компанії:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "vacancy_banner":
        await query.message.reply_text(
            "🎨 Замовити банер — 500 грн\n\n"
            "Починаємо заповнення заявки.\n\n"
            "🏢 Вкажіть назву компанії:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "vacancy_reels":
        await query.message.reply_text(
            "🎥 Замовити Reels / Shorts — 800 грн\n\n"
            "Починаємо заповнення заявки.\n\n"
            "🏢 Вкажіть назву компанії:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_resume":
        await query.message.reply_text(
            "🆓 Текстове резюме — безкоштовно\n\n"
            "Вкажіть інформацію про резюме:\n\n"
            "👤 Ім'я:\n"
            "📍 Місто:\n"
            "🛠 Спеціальність:\n"
            "💼 Бажана посада:\n"
            "📋 Досвід роботи:\n"
            "💰 Бажана зарплата:\n"
            "📞 Контакти:",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_promo":
        await query.message.reply_text(
            "📢 Просування бізнесу\n\n"
            "Для просування компанії, акції, відкриття або бренду напишіть HR менеджеру:\n\n"
            "👨‍💼 @HireUkraine",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_prices":
        await query.message.reply_text(
            "🆓 БЕЗКОШТОВНО\n\n"
            "📢 Текстові вакансії — 3 публікації на день\n"
            "👷 Текстові резюме — 2 публікації на день\n\n"
            "✅ Telegram канал обраного міста\n\n"
            "📅 Термін розміщення:\n"
            "1 • 3 • 7 • 14 • 21 • 30 днів\n\n"
            "🔄 Якщо вакансія залишається актуальною, термін розміщення можна продовжити\n\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🚀 Start — 4500 грн / 7 днів\n\n"
            "📢 63 публікації за 7 днів\n"
            "(3 публікації на день у Telegram, Facebook та Instagram)\n\n"
            "✅ Telegram\n"
            "✅ Facebook\n"
            "✅ Instagram\n"
            "🎬 YouTube Shorts — тільки для відеоформату\n\n"
            "🎨 Банер — просування готового банера\n\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🚀🚀 Business — 7500 грн / 7 днів\n\n"
            "📢 126 публікацій за 7 днів\n"
            "(6 публікацій на день у Telegram, Facebook та Instagram)\n\n"
            "✅ Telegram\n"
            "✅ Facebook\n"
            "✅ Instagram\n"
            "🎬 YouTube Shorts — тільки для відеоформату\n\n"
            "🎨 Банер — просування готового банера\n"
            "🎥 Reels / Shorts — просування готового відео\n"
            "🤖 Відео з Тімом AI — за окремим замовленням\n\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💰 Створення контенту\n\n"
            "🎨 Банер — 500 грн\n"
            "🎥 Reels / Shorts — 800 грн\n"
            "🤖 Відео з Тімом AI — 800 грн",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_contacts":
        await query.message.reply_text(
            "🤖 Тім AI: @HireUA_AI_bot\n"
            "👨‍💼 HR менеджер: @HireUkraine",
            reply_markup=back_home_keyboard(),
        )