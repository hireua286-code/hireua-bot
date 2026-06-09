import os
import threading
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@UkraineHire")

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "HireUA bot is running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Вітаю! Я HireUA Publisher Bot.\n\n"
        "Надішліть мені фото/банер або відео Reels.\n"
        "Потім надішліть текст публікації.\n\n"
        "Я підготую публікацію для Telegram, Facebook та Instagram."
    )
    await update.message.reply_text(text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота.")
        return

    message = update.message

    if message.photo:
        file_id = message.photo[-1].file_id
        context.user_data["media_type"] = "photo"
        context.user_data["file_id"] = file_id
        await message.reply_text("✅ Фото отримано. Тепер надішліть текст публікації.")
        return

    if message.video:
        file_id = message.video.file_id
        context.user_data["media_type"] = "video"
        context.user_data["file_id"] = file_id
        await message.reply_text("✅ Відео отримано. Тепер надішліть текст публікації.")
        return

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота.")
        return

    text = update.message.text

    if "file_id" not in context.user_data:
        await update.message.reply_text("Спочатку надішліть фото або відео.")
        return

    context.user_data["caption"] = text

    keyboard = [
        [InlineKeyboardButton("📢 Опублікувати всюди", callback_data="publish_all")],
        [InlineKeyboardButton("📱 Telegram", callback_data="publish_telegram")],
        [InlineKeyboardButton("📘 Facebook", callback_data="publish_facebook")],
        [InlineKeyboardButton("📷 Instagram", callback_data="publish_instagram")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="cancel")],
    ]

    await update.message.reply_text(
        "✅ Публікація готова. Куди опублікувати?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def publish_to_telegram(context: ContextTypes.DEFAULT_TYPE):
    media_type = context.user_data.get("media_type")
    file_id = context.user_data.get("file_id")
    caption = context.user_data.get("caption", "")

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

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data

    if action == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Публікацію скасовано.")
        return

    if action == "publish_telegram":
        await publish_to_telegram(context)
        await query.edit_message_text("✅ Опубліковано в Telegram.")
        return

    if action == "publish_facebook":
        await query.edit_message_text(
            "⚠️ Facebook ще не підключений у коді. Спочатку запускаємо Telegram."
        )
        return

    if action == "publish_instagram":
        await query.edit_message_text(
            "⚠️ Instagram ще не підключений у коді. Спочатку запускаємо Telegram."
        )
        return

    if action == "publish_all":
        await publish_to_telegram(context)
        await query.edit_message_text(
            "✅ Опубліковано в Telegram.\n\n"
            "⚠️ Facebook та Instagram додамо наступним етапом через Meta API."
        )
        return

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    threading.Thread(target=run_web, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(buttons))

    app.run_polling()

if __name__ == "__main__":
    main()