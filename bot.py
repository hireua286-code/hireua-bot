import os
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@UkraineHire")

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "HireUA bot is running"


def run_web():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 HireUA Publisher Bot працює.\n\n"
        "Надішліть фото або відео, потім текст публікації."
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Немає доступу.")
        return

    if update.message.photo:
        context.user_data["media_type"] = "photo"
        context.user_data["file_id"] = update.message.photo[-1].file_id
        await update.message.reply_text("✅ Фото отримано. Тепер надішліть текст.")
        return

    if update.message.video:
        context.user_data["media_type"] = "video"
        context.user_data["file_id"] = update.message.video.file_id
        await update.message.reply_text("✅ Відео отримано. Тепер надішліть текст.")
        return


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Немає доступу.")
        return

    if "file_id" not in context.user_data:
        await update.message.reply_text("Спочатку надішліть фото або відео.")
        return

    caption = update.message.text
    media_type = context.user_data["media_type"]
    file_id = context.user_data["file_id"]

    if media_type == "photo":
        await context.bot.send_photo(
            chat_id=TELEGRAM_CHANNEL_ID,
            photo=file_id,
            caption=caption,
        )

    elif media_type == "video":
        await context.bot.send_video(
            chat_id=TELEGRAM_CHANNEL_ID,
            video=file_id,
            caption=caption,
        )

    context.user_data.clear()
    await update.message.reply_text("✅ Опубліковано в Telegram.")


async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)


def main():
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()