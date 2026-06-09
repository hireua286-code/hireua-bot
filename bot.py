import os
import asyncio
import threading
from copy import deepcopy
from datetime import time

import pytz
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

KYIV_TZ = pytz.timezone("Europe/Kyiv")

CHANNELS = {
    "kyiv": ("Київ", "@HireKyiv"),
    "lviv": ("Львів", "@HireLviv"),
    "odesa": ("Одеса", "@HireOdesa"),
    "dnipro": ("Дніпро", "@HireDnipro"),
    "ukraine": ("Україна", "@UkraineHire"),
}

PACKAGES = {
    "single": ("Разово", []),
    "start": ("Start", ["08:00", "12:00", "16:00"]),
    "business": ("Business", ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]),
}

sessions = {}

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "HireUA bot is running"


def run_web():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


def admin_only(update: Update) -> bool:
    return not ADMIN_ID or update.effective_user.id == ADMIN_ID


def new_session():
    return {
        "step": "ask_media",
        "file_id": None,
        "media_type": None,
        "text": "",
        "channels": [],
        "package": None,
    }


def yes_no_keyboard(prefix):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Так", callback_data=f"{prefix}_yes"),
            InlineKeyboardButton("Ні", callback_data=f"{prefix}_no"),
        ]
    ])


def channels_keyboard(selected):
    keyboard = []

    for key, (name, chat) in CHANNELS.items():
        mark = "✅" if key in selected else "☐"
        keyboard.append([
            InlineKeyboardButton(
                f"{mark} {name} {chat}",
                callback_data=f"channel:{key}",
            )
        ])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="channels_done")])
    return InlineKeyboardMarkup(keyboard)


def packages_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Разово — зараз", callback_data="package:single")],
        [InlineKeyboardButton("Start — 08:00 / 12:00 / 16:00", callback_data="package:start")],
        [InlineKeyboardButton("Business — 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00", callback_data="package:business")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    user_id = update.effective_user.id
    sessions[user_id] = new_session()

    await update.message.reply_text(
        "👋 HireUA Publisher Bot працює.\n\nФото або відео буде?",
        reply_markup=yes_no_keyboard("media"),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Скасовано. Натисніть /start для нової публікації.")


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not admin_only(update):
        return

    user_id = query.from_user.id

    if user_id not in sessions:
        sessions[user_id] = new_session()

    session = sessions[user_id]
    data = query.data

    if data == "media_yes":
        session["step"] = "wait_media"
        await query.edit_message_text("Надішліть фото або відео.")

    elif data == "media_no":
        session["file_id"] = None
        session["media_type"] = None
        session["step"] = "ask_text"
        await query.edit_message_text(
            "Текст буде?",
            reply_markup=yes_no_keyboard("text"),
        )

    elif data == "text_yes":
        session["step"] = "wait_text"
        await query.edit_message_text("Надішліть текст публікації.")

    elif data == "text_no":
        session["text"] = ""
        session["step"] = "choose_channels"
        await query.edit_message_text(
            "Оберіть канали для публікації:",
            reply_markup=channels_keyboard(session["channels"]),
        )

    elif data.startswith("channel:"):
        key = data.split(":", 1)[1]

        if key in session["channels"]:
            session["channels"].remove(key)
        else:
            session["channels"].append(key)

        await query.edit_message_text(
            "Оберіть канали для публікації:",
            reply_markup=channels_keyboard(session["channels"]),
        )

    elif data == "channels_done":
        if not session["channels"]:
            await query.answer("Оберіть хоча б один канал", show_alert=True)
            return

        session["step"] = "choose_package"

        await query.edit_message_text(
            "Оберіть пакет публікації:",
            reply_markup=packages_keyboard(),
        )

    elif data.startswith("package:"):
        package_key = data.split(":", 1)[1]
        session["package"] = package_key

        if package_key == "single":
            await query.edit_message_text("⏳ Публікую зараз...")
            success, failed = await send_publication(context, session)
            await query.message.reply_text(make_result(success, failed))
            sessions.pop(user_id, None)
        else:
            await schedule_posts(context, query, user_id, session)


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    user_id = update.effective_user.id
    session = sessions.get(user_id)

    if not session or session.get("step") != "wait_media":
        await update.message.reply_text("Натисніть /start для нової публікації.")
        return

    if update.message.photo:
        session["file_id"] = update.message.photo[-1].file_id
        session["media_type"] = "photo"
    elif update.message.video:
        session["file_id"] = update.message.video.file_id
        session["media_type"] = "video"
    else:
        await update.message.reply_text("Надішліть саме фото або відео.")
        return

    session["step"] = "ask_text"

    await update.message.reply_text(
        "✅ Фото/відео отримано.\n\nТекст буде?",
        reply_markup=yes_no_keyboard("text"),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    user_id = update.effective_user.id
    session = sessions.get(user_id)

    if not session or session.get("step") != "wait_text":
        await update.message.reply_text("Натисніть /start для нової публікації.")
        return

    session["text"] = update.message.text or ""
    session["step"] = "choose_channels"

    await update.message.reply_text(
        "✅ Текст отримано.\n\nОберіть канали:",
        reply_markup=channels_keyboard(session["channels"]),
    )


async def send_publication(context: ContextTypes.DEFAULT_TYPE, session: dict):
    success = []
    failed = []

    for key in session["channels"]:
        name, chat = CHANNELS[key]

        try:
            if session["file_id"]:
                if session["media_type"] == "photo":
                    await context.bot.send_photo(
                        chat_id=chat,
                        photo=session["file_id"],
                        caption=session["text"] or None,
                    )
                else:
                    await context.bot.send_video(
                        chat_id=chat,
                        video=session["file_id"],
                        caption=session["text"] or None,
                    )
            else:
                if not session["text"]:
                    failed.append(f"{chat}: немає ні фото/відео, ні тексту")
                    continue

                await context.bot.send_message(
                    chat_id=chat,
                    text=session["text"],
                )

            success.append(chat)

        except Exception as e:
            failed.append(f"{chat}: {e}")

    return success, failed


def make_result(success, failed):
    result = "✅ Готово\n\n"

    if success:
        result += "Опубліковано:\n" + "\n".join(success)

    if failed:
        result += "\n\n⚠️ Помилки:\n" + "\n".join(failed)

    return result


async def schedule_posts(context, query, user_id, session):
    package_name, times = PACKAGES[session["package"]]
    saved_session = deepcopy(session)

    for t in times:
        hour, minute = map(int, t.split(":"))

        context.job_queue.run_daily(
            scheduled_publish,
            time=time(hour=hour, minute=minute, tzinfo=KYIV_TZ),
            data=deepcopy(saved_session),
            name=f"{user_id}_{session['package']}_{t}",
        )

    channels_text = "\n".join(CHANNELS[key][1] for key in session["channels"])

    await query.edit_message_text(
        f"✅ Публікацію заплановано\n\n"
        f"Пакет: {package_name}\n\n"
        f"Канали:\n{channels_text}\n\n"
        f"Час:\n" + "\n".join(times)
    )

    sessions.pop(user_id, None)


async def scheduled_publish(context: ContextTypes.DEFAULT_TYPE):
    session = context.job.data
    await send_publication(context, session)


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    await update.message.reply_text("Натисніть /start для створення нової публікації.")


async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    print("STARTING BOT", flush=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(buttons))
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