import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привіт! Я HR-бот HireUA.\n\n"
        "🔹 Пошук вакансії\n"
        "🔹 Пошук кандидатів\n"
        "🔹 Розміщення вакансій\n"
        "🔹 HR-консультації\n\n"
        "Напишіть одним повідомленням:\n"
        "1. Імʼя\n"
        "2. Місто\n"
        "3. Вік\n"
        "4. Бажана вакансія\n"
        "5. Телефон"
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Надішліть дані одним повідомленням:\n\n"
        "Імʼя\nМісто\nВік\nВакансія\nТелефон"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    message = update.message.text

    await update.message.reply_text(
        "✅ Заявка прийнята!\n\n"
        "Наш менеджер звʼяжеться з вами найближчим часом."
    )

    if ADMIN_ID:
        admin_text = (
            "📩 Нова заявка HireUA\n\n"
            f"👤 Користувач: @{user.username}\n"
            f"🆔 ID: {user.id}\n\n"
            f"📝 Повідомлення:\n{message}"
        )
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=admin_text)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не знайдено")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("HireUA bot запущено...")
    app.run_polling()


if __name__ == "__main__":
    main()
