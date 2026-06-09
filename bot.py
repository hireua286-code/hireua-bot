import os
import asyncio
import threading
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

KYIV_TZ = pytz.timezone("Europe/Kyiv")

CHANNELS = {
    "kyiv": {"name": "Київ", "chat": "@HireKyiv"},
    "lviv": {"name": "Львів", "chat": "@HireLviv"},
    "odesa": {"name": "Одеса", "chat": "@HireOdesa"},
    "dnipro": {"name": "Дніпро", "chat": "@HireDnipro"},
    "ukraine": {"name": "Україна", "chat": "@UkraineHire"},
}

PACKAGES = {
    "single": {"name": "Разово", "times": []},
    "start": {"name": "Start", "times": ["08:00", "12:00", "16:00"]},
    "business": {
        "name": "Business",
        "times": ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"],
    },
}

user_sessions = {}

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "HireUA bot is running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


def is_admin(update: Update):
    return not ADMIN_ID or update.effective_user.id == ADMIN_ID


def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "step": None,
            "need_media": None,
            "need_text": None,
            "media_type": None,
            "file_id": None,
            "text": None,
            "channels": [],
            "package": None,
        }
    return user_sessions[user_id]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    user_id = update.effective_user.id
    user_sessions[user_id] = {}
    session = get_session(user_id)
    session["step"] = "ask_media"

    keyboard = [
        [
            InlineKeyboardButton("Так", callback_data="media_yes"),
            InlineKeyboardButton("Ні", callback_data="media_no"),
        ]
    ]

    await update.message.reply_text(
        "👋 HireUA Publisher Bot\n\nФото або відео буде?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    user_sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Скасовано. Натисніть /start для нової публікації.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        return

    user_id = query.from_user.id
    session = get_session(user_id)
    data = query.data

    if data == "media_yes":
        session["need_media"] = True
        session["step"] = "wait_media"
        await query.edit_message_text("Надішліть фото або відео.")

    elif data == "media_no":
        session["need_media"] = False
        session["step"] = "ask_text"
        await ask_text(query)

    elif data == "text_yes":
        session["need_text"] = True
        session["step"] = "wait_text"
        await query.edit_message_text("Надішліть текст публікації.")

    elif data == "text_no":
        session["need_text"] = False
        session["text"] = ""
        session["step"] = "choose_channels"
        await show_channels(query, session)

    elif data.startswith("channel_"):
        key = data.replace("channel_", "")
        if key in session["channels"]:
            session["channels"].remove(key)
        else:
            session["channels"].append(key)
        await show_channels(query, session)

    elif data == "channels_done":
        if not session["channels"]:
            await query.answer("Оберіть хоча б один канал", show_alert=True)
            return
        session["step"] = "choose_package"
        await show_packages(query)

    elif data.startswith("package_"):
        package_key = data.replace("package_", "")
        session["package"] = package_key

        if package_key == "single":
            await publish_now(context, user_id, query)
        else:
            await schedule_publication(context, user_id, query)


async def ask_text(query):
    keyboard = [
        [
            InlineKeyboardButton("Так", callback_data="text_yes"),
            InlineKeyboardButton("Ні", callback_data="text_no"),
        ]
    ]
    await query.edit_message_text(
        "Текст буде?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_channels(query, session):
    keyboard = []

    for key, info in CHANNELS.items():
        mark = "✅" if key in session["channels"] else "☐"
        keyboard.append([
            InlineKeyboardButton(
                f"{mark} {info['name']} {info['chat']}",
                callback_data=f"channel_{key}",
            )
        ])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="channels_done")])

    await query.edit_message_text(
        "Оберіть канали для публікації:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_packages(query):
    keyboard = [
        [InlineKeyboardButton("Разово — опублікувати зараз", callback_data="package_single")],
        [InlineKeyboardButton("Start — 08:00 / 12:00 / 16:00", callback_data="package_start")],
        [InlineKeyboardButton("Business — 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00", callback_data="package_business")],
    ]

    await query.edit_message_text(
        "Оберіть пакет публікації:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    user_id = update.effective_user.id
    session = get_session(user_id)

    if session.get("step") != "wait_media":
        await update.message.reply_text("Натисніть /start для створення нової публікації.")
        return

    if update.message.photo:
        session["media_type"] = "photo"
        session["file_id"] = update.message.photo[-1].file_id
    elif update.message.video:
        session["media_type"] = "video"
        session["file_id"] = update.message.video.file_id
    else:
        await update.message.reply_text("Надішліть саме фото або відео.")
        return

    session["step"] = "ask_text"

    keyboard = [
        [
            InlineKeyboardButton("Так", callback_data="text_yes"),
            InlineKeyboardButton("Ні", callback_data="text_no"),
        ]
    ]

    await update.message.reply_text(
        "✅ Фото/відео отримано.\n\nТекст буде?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    user_id = update.effective_user.id
    session = get_session(user_id)

    if session.get("step") != "wait_text":
        await update.message.reply_text("Натисніть /start для створення нової публікації.")
        return

    session["text"] = update.message.text or ""
    session["step"] = "choose_channels"

    keyboard = []
    for key, info in CHANNELS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"☐ {info['name']} {info['chat']}",
                callback_data=f"channel_{key}",
            )
        ])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="channels_done")])

    await update.message.reply_text(
        "✅ Текст отримано.\n\nОберіть канали:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_publication(context: ContextTypes.DEFAULT_TYPE, session):
    success = []
    failed = []

    for channel_key in session["channels"]:
        channel = CHANNELS[channel_key]["chat"]

        try:
            if session.get("file_id"):
                if session["media_type"] == "photo":
                    await context.bot.send_photo(
                        chat_id=channel,
                        photo=session["file_id"],
                        caption=session.get("text", ""),
                    )
                elif session["media_type"] == "video":
                    await context.bot.send_video(
                        chat_id=channel,
                        video=session["file_id"],
                        caption=session.get("text", ""),
                    )
            else:
                await context.bot.send_message(
                    chat_id=channel,
                    text=session.get("text", " "),
                )

            success.append(channel)

        except Exception as e:
            failed.append(f"{channel}: {e}")

    return success, failed


async def publish_now(context, user_id, query):
    session = get_session(user_id)

    await query.edit_message_text("⏳ Публікую...")

    success, failed = await send_publication(context, session)

    result = "✅ Публікація завершена\n\n"

    if success:
        result += "Опубліковано:\n" + "\n".join(success)

    if failed:
        result += "\n\n⚠️ Помилки:\n" + "\n".join(failed)

    user_sessions.pop(user_id, None)

    await query.message.reply_text(result)


async def schedule_publication(context, user_id, query):
    session = get_session(user_id)
    package = PACKAGES[session["package"]]
    times = package["times"]

    scheduled_times = []

    for time_str in times:
        hour, minute = map(int, time_str.split(":"))

        job_id = f"{user_id}_{session['package']}_{time_str}_{len(context.job_queue.jobs())}"

        context.job_queue.run_daily(
            scheduled_job,
            time=KYIV_TZ.localize(
                __import__("datetime").datetime(2000, 1, 1, hour, minute)
            ).timetz(),
            data=session.copy(),
            name=job_id,
        )

        scheduled_times.append(time_str)

    channels_text = "\n".join([CHANNELS[key]["chat"] for key in session["channels"]])

    await query.edit_message_text(
        f"✅ Публікацію заплановано\n\n"
        f"Пакет: {package['name']}\n\n"
        f"Канали:\n{channels_text}\n\n"
        f"Час:\n" + "\n".join(scheduled_times)
    )

    user_sessions.pop(user_id, None)


async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    session = context.job.data
    await send_publication(context, session)


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    await update.message.reply_text("Натисніть /start для створення публікації.")


async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    print("BOT_TOKEN exists:", bool(BOT_TOKEN), flush=True)
    print("STARTING TELEGRAM BOT", flush=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
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