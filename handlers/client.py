from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def client_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💼 Розмістити вакансію", callback_data="client_vacancy")],
        [InlineKeyboardButton("👷 Додати резюме", callback_data="client_resume")],
        [InlineKeyboardButton("📢 Просування бізнесу", callback_data="client_promo")],
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
            "🆓 Текстова вакансія — безкоштовно\n\n"
            "Вкажіть інформацію про вакансію:\n\n"
            "🏢 Назва компанії:\n"
            "💼 Посада:\n"
            "📍 Місто:\n"
            "💰 Зарплата:\n"
            "📋 Обов'язки:\n"
            "📞 Контакти:\n\n"
            "Після перевірки ми розмістимо текстову вакансію у відповідному Telegram каналі HireUA.",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_resume":
        await query.message.reply_text(
            "🆓 Текстове резюме — безкоштовно\n\n"
            "Вкажіть інформацію про резюме:\n\n"
            "👤 Ім'я:\n"
            "📍 Місто:\n"
            "💼 Бажана посада:\n"
            "💰 Бажана зарплата:\n"
            "📞 Контакти:\n\n"
            "Після перевірки ми розмістимо текстове резюме у відповідному Telegram каналі HireUA.",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_promo":
        await query.message.reply_text(
            "📢 Просування бізнесу\n\n"
            "Вкажіть інформацію для просування:\n\n"
            "🏢 Назва компанії:\n"
            "📍 Місто:\n"
            "📞 Контакти:\n\n"
            "🎯 Що потрібно просувати?\n"
            "(компанію, вакансію, акцію, відкриття, товар або послугу)\n\n"
            "🖼 Логотип компанії (за наявності):\n"
            "🎨 Банер (за наявності):\n"
            "🎬 Reels / Shorts (за наявності):\n"
            "🔗 Сайт / соцмережі (за наявності):\n\n"
            "📝 Опис або побажання:",
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
            "🤖 Відео з Тімом AI — 800 грн\n\n"
            "📞 Замовити:\n"
            "🤖 Тім AI: @HireUA_AI_bot\n"
            "👨‍💼 HR менеджер: @HireUkraine",
            reply_markup=back_home_keyboard(),
        )

    elif data == "client_contacts":
        await query.message.reply_text(
            "🤖 Тім AI: @HireUA_AI_bot\n"
            "👨‍💼 HR менеджер: @HireUkraine",
            reply_markup=back_home_keyboard(),
        )