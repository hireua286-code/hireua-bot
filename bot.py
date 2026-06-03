import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Я HR-бот HireUA.\n\n"
        "Я помогу кандидатам оставить заявку на работу.\n\n"
        "Напиши:\n"
        "1. Имя\n"
        "2. Город\n"
        "3. Возраст\n"
        "4. Желаемую вакансию\n"
        "5. Телефон"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправь данные кандидата одним сообщением:\n\n"
        "Имя\nГород\nВозраст\nВакансия\nТелефон"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    message = update.message.text

    admin_id = os.getenv("ADMIN_ID")

    reply = (
        "✅ Заявка принята!\n\n"
        "Наш менеджер свяжется с вами в ближайшее время."
    )

    await update.message.reply_text(reply)

    if admin_id:
        admin_text = (
            "📩 Новая заявка HireUA\n\n"
            f"👤 Пользователь: @{user.username}\n"
            f"🆔 ID: {user.id}\n\n"
            f"📝 Сообщение:\n{message}"
        )
        await context.bot.send_message(chat_id=int(admin_id), text=admin_text)

def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN не найден. Добавь его в Render Environment Variables.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("HireUA bot запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
