import os
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

CHANNELS = [
    "@UkraineHire",
    "@HireKyiv",
    "@HireLviv",
]

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "HireUA bot is running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 HireUA Publisher Bot працює.\n\n"
        "Надішліть фото або відео, потім текст публікації."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Скасовано. Надішліть фото або відео заново.")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        media_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        media_type = "video"
    else:
        await update.message.reply_text("Спочатку надішліть фото або відео.")
        return

    context.user_data["file_id"] = file_id
    context.user_data["media_type"] = media_type

    await update.message.reply_text("✅ Фото/відео отримано. Тепер надішліть текст.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return

    if "file_id" not in context.user_data:
        await update.message.reply_text("Спочатку надішліть фото або відео.")
        return

    text = update.message.text
    file_id = context.user_data["file_id"]
    media_type = context.user_data["media_type"]

    success = []
    failed = []

    for channel in CHANNELS:
        try:
            if media_type == "photo":
                await context.bot.send_photo(
                    chat_id=channel,
                    photo=file_id,
                    caption=text
                )
            else:
                await context.bot.send_video(
                    chat_id=channel,
                    video=file_id,
                    caption=text
                )

            success.append(channel)

        except Exception as e:
            failed.append(f"{channel}: {e}")

    context.user_data.clear()

    result = ""

    if success:
        result += "✅ Опубліковано:\n" + "\n".join(success)

    if failed:
        result += "\n\n⚠️ Помилки:\n" + "\n".join(failed)

    await update.message.reply_text(result)

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Надішліть фото або відео для публікації.\n"
        "Або напишіть /start"
    )

async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    print("BOT_TOKEN exists:", bool(BOT_TOKEN), flush=True)
    print("STARTING TELEGRAM BOT", flush=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.ALL, fallback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    print("POLLING STARTED", flush=True)

    while True:
        await asyncio.sleep(3600)

def main():
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()