import os
import json
from uuid import uuid4

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

import asyncio
import threading
import time as time_module
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta

import pytz
import requests
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI

from handlers.client import client_main_keyboard, client_buttons

BOT_TOKEN = os.getenv("BOT_TOKEN")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

FB_PAGE_ID = os.getenv("FB_PAGE_ID")
IG_USER_ID = os.getenv("IG_USER_ID")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

BASE_URL = os.getenv("BASE_URL", "https://hireua-bot.onrender.com")

KYIV_TZ = pytz.timezone("Europe/Kyiv")
GRAPH_URL = "https://graph.facebook.com/v25.0"

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

# Автоматичні вікна публікацій.
# Бот сам ставить публікації у найближчий вільний слот кожні 5 хвилин.
SCHEDULE_FILE = "scheduled_posts.json"
SLOT_WINDOWS = [
    (8, 10),
    (12, 14),
    (16, 18),
    (18, 20),
]
SLOT_STEP_MINUTES = 5

sessions = {}
web_app = Flask(__name__)


# ---------- CLIENT KEYBOARDS / BUTTONS ----------
# Цей блок спеціально дублює клієнтську логіку всередині bot.py,
# щоб Start / Business гарантовано запускали бриф vacancy_promo.
# Адмінська публікація банерів / Reels нижче не змінюється.

def client_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💼 Розмістити вакансію", callback_data="client_vacancy")],
        [InlineKeyboardButton("👷 Додати резюме", callback_data="client_resume")],
        [InlineKeyboardButton("📢 Реклама / Акції / Відкриття", callback_data="client_promo")],
        [InlineKeyboardButton("💰 Тарифи / Співпраця", callback_data="client_prices")],
        [InlineKeyboardButton("📞 Звʼязатися з HR менеджером", url="https://t.me/HireUkraine")],
    ])


def vacancy_tariffs_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆓 Безкоштовна текстова вакансія", callback_data="vacancy_free")],
        [InlineKeyboardButton("🚀 Start — просування 7 днів", callback_data="vacancy_start")],
        [InlineKeyboardButton("💼 Business — активне просування 7 днів", callback_data="vacancy_business")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="client_back")],
    ])


def promo_order_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Банер", callback_data="content_banner")],
        [InlineKeyboardButton("🎬 Reels / Shorts", callback_data="content_reels")],
        [InlineKeyboardButton("🤖 Відео з Тімом", callback_data="content_tim_video")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="client_back")],
    ])


async def client_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "client_back":
        await query.message.reply_text("Оберіть потрібний розділ нижче 👇", reply_markup=client_main_keyboard())
        return

    if data == "client_vacancy":
        await query.message.reply_text(
            "👨‍💼 Розміщення вакансії\n\n"
            "Оберіть формат розміщення:",
            reply_markup=vacancy_tariffs_keyboard(),
        )
        return

    if data == "vacancy_free":
        context.user_data["client_form"] = {
            "type": "vacancy",
            "tariff": "Безкоштовна текстова вакансія",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text("🏢 Вкажіть назву компанії:")
        return

    if data == "vacancy_start":
        context.user_data["client_form"] = {
            "type": "vacancy_promo",
            "tariff": "Start",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text(
            "🚀 Пакет Start\n\n"
            "Зараз заповнимо вакансію і бриф для банера / Reels / Shorts.\n\n"
            "🏢 Вкажіть назву компанії:"
        )
        return

    if data == "vacancy_business":
        context.user_data["client_form"] = {
            "type": "vacancy_promo",
            "tariff": "Business",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text(
            "💼 Пакет Business\n\n"
            "Зараз заповнимо вакансію і розширений бриф для банера / Reels / Shorts.\n\n"
            "🏢 Вкажіть назву компанії:"
        )
        return

    if data == "client_promo":
        await query.message.reply_text(
            "📢 Реклама / Акції / Відкриття\n\n"
            "Що потрібно підготувати?",
            reply_markup=promo_order_keyboard(),
        )
        return

    if data in ("content_banner", "content_reels", "content_tim_video"):
        tariff_map = {
            "content_banner": "Банер — 500 грн",
            "content_reels": "Reels / Shorts — 800 грн",
            "content_tim_video": "Відео з Тімом — 800 грн",
        }
        context.user_data["client_form"] = {
            "type": "content_order",
            "tariff": tariff_map.get(data, "Контент"),
            "step": "content_company",
            "data": {},
        }
        await query.message.reply_text("🏢 Вкажіть назву компанії / бренду:")
        return

    if data == "client_prices":
        await query.message.reply_text(
            "💰 Тарифи HireUA\n\n"
            "🆓 Текстові вакансії — безкоштовно 3 рази на добу.\n"
            "🆓 Текстові резюме — безкоштовно 2 рази на добу.\n\n"
            "🖼 Банер — 500 грн / шт.\n"
            "🎬 Reels / Shorts — 800 грн / шт.\n"
            "🤖 Відео з Тімом — 800 грн / шт.\n\n"
            "🚀 Start — 4500 грн / 7 днів.\n"
            "💼 Business — 7500 грн / 7 днів.\n\n"
            "Для деталей напишіть HR менеджеру: @HireUkraine"
        )
        return

    await query.message.reply_text("Оберіть потрібний розділ нижче 👇", reply_markup=client_main_keyboard())


@web_app.route("/")
def home():
    return "HireUA bot is running"


@web_app.route("/youtube-auth")
def youtube_auth():
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
        return "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET", 500

    redirect_uri = f"{BASE_URL}/youtube-callback"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )

    flow.redirect_uri = redirect_uri

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    return f'<h2>YouTube Authorization</h2><a href="{auth_url}">Authorize YouTube</a>'


@web_app.route("/youtube-callback")
def youtube_callback():
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
        return "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET", 500

    redirect_uri = f"{BASE_URL}/youtube-callback"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )

    flow.redirect_uri = redirect_uri
    flow.fetch_token(authorization_response=request.url)

    refresh_token = flow.credentials.refresh_token

    return f"""
    <h2>Скопируй этот YOUTUBE_REFRESH_TOKEN</h2>
    <textarea style="width:100%;height:140px;font-size:16px;">{refresh_token}</textarea>
    """


def run_web():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


def admin_only(update: Update) -> bool:
    return not ADMIN_ID or update.effective_user.id == ADMIN_ID


def new_session():
    return {
        "step": "tg_banner",
        "telegram": {"banner": False, "reels": False, "text": False, "promote": False},
        "facebook": {"banner": False, "reels": False, "text": False, "promote": False},
        "instagram": {"banner": False, "reels": False, "promote": False},
        "youtube": {"reels": False},
        "channels": [],
        "banner_file_id": None,
        "reels_file_id": None,
        "text": "",
        "package": None,
        "days": 1,
    }


def yes_no_keyboard(prefix):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Так", callback_data=f"{prefix}:yes"),
            InlineKeyboardButton("Ні", callback_data=f"{prefix}:no"),
        ]
    ])


def channels_keyboard(selected):
    keyboard = []
    for key, (name, chat) in CHANNELS.items():
        mark = "✅" if key in selected else "☐"
        keyboard.append([InlineKeyboardButton(f"{mark} {name} {chat}", callback_data=f"channel:{key}")])
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="channels_done")])
    return InlineKeyboardMarkup(keyboard)


def packages_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Разово — зараз", callback_data="package:single")],
        [InlineKeyboardButton("Start — 08:00 / 12:00 / 16:00", callback_data="package:start")],
        [InlineKeyboardButton("Business — 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00", callback_data="package:business")],
    ])


def days_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 день", callback_data="days:1")],
        [InlineKeyboardButton("3 дні", callback_data="days:3")],
        [InlineKeyboardButton("7 днів", callback_data="days:7")],
        [InlineKeyboardButton("14 днів", callback_data="days:14")],
        [InlineKeyboardButton("30 днів", callback_data="days:30")],
    ])


def load_schedule_entries():
    if not os.path.exists(SCHEDULE_FILE):
        return []

    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if isinstance(data, list):
        return data

    return []


def save_schedule_entries(entries):
    tmp_file = f"{SCHEDULE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, SCHEDULE_FILE)


def slot_key(dt: datetime) -> str:
    return dt.astimezone(KYIV_TZ).strftime("%Y-%m-%d %H:%M")


def day_slots(day_dt: datetime):
    day_dt = day_dt.astimezone(KYIV_TZ)
    slots = []

    for start_hour, end_hour in SLOT_WINDOWS:
        current = day_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end = day_dt.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        while current < end:
            slots.append(current)
            current += timedelta(minutes=SLOT_STEP_MINUTES)

    return slots


def find_free_slots(count: int, start_from: datetime | None = None):
    entries = load_schedule_entries()
    used = {
        entry.get("slot")
        for entry in entries
        if entry.get("status") in (None, "pending", "running") and entry.get("slot")
    }

    now = start_from or datetime.now(KYIV_TZ)
    earliest = now + timedelta(minutes=1)
    free_slots = []

    for day_offset in range(0, 60):
        day_dt = now + timedelta(days=day_offset)

        for slot in day_slots(day_dt):
            key = slot_key(slot)

            if slot <= earliest:
                continue

            if key in used:
                continue

            used.add(key)
            free_slots.append(slot)

            if len(free_slots) >= count:
                return free_slots

    return free_slots


def add_schedule_entries(session: dict, slots, package_name: str):
    entries = load_schedule_entries()
    new_entries = []

    for slot in slots:
        entry = {
            "id": str(uuid4()),
            "status": "pending",
            "slot": slot_key(slot),
            "run_at": slot.isoformat(),
            "package": package_name,
            "created_at": datetime.now(KYIV_TZ).isoformat(),
            "session": deepcopy(session),
        }
        entries.append(entry)
        new_entries.append(entry)

    save_schedule_entries(entries)
    return new_entries


def update_schedule_entry(entry_id: str, status: str, success=None, failed=None):
    entries = load_schedule_entries()

    for entry in entries:
        if entry.get("id") == entry_id:
            entry["status"] = status
            entry["updated_at"] = datetime.now(KYIV_TZ).isoformat()

            if success is not None:
                entry["success"] = success
            if failed is not None:
                entry["failed"] = failed
            break

    save_schedule_entries(entries)


def register_schedule_job(job_queue, entry):
    run_at_raw = entry.get("run_at")
    if not run_at_raw:
        return False

    try:
        run_at = datetime.fromisoformat(run_at_raw)
    except Exception:
        return False

    if run_at.tzinfo is None:
        run_at = KYIV_TZ.localize(run_at)
    else:
        run_at = run_at.astimezone(KYIV_TZ)

    now = datetime.now(KYIV_TZ)
    when = run_at if run_at > now else now + timedelta(seconds=10)

    job_queue.run_once(
        scheduled_publish,
        when=when,
        data={"id": entry.get("id"), "session": entry.get("session")},
        name=f"scheduled_{entry.get('id')}",
    )
    return True


def restore_pending_schedule_jobs(job_queue):
    restored = 0

    for entry in load_schedule_entries():
        if entry.get("status") == "pending" and entry.get("session"):
            if register_schedule_job(job_queue, entry):
                restored += 1

    print(f"RESTORED SCHEDULED POSTS: {restored}", flush=True)
    return restored


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (
        "👋 Вітаю!\n\n"
        "Я Тім AI — ваш помічник у сервісі HireUA.\n\n"
        "🤖 Тім AI: @HireUA_AI_bot\n"
        "👨‍💼 HR менеджер: @HireUkraine\n\n"
        "Допомагаю роботодавцям знаходити працівників, "
        "а пошукачам — нові можливості для роботи.\n\n"
        "Оберіть потрібний розділ нижче 👇"
    )

    try:
        with open("IMG_7069.mp4", "rb") as video:
            await update.message.reply_video(
                video=video,
                caption=caption,
                reply_markup=client_main_keyboard(),
                supports_streaming=True,
            )
    except Exception:
        await update.message.reply_text(
            caption,
            reply_markup=client_main_keyboard(),
        )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    sessions[update.effective_user.id] = new_session()

    await update.message.reply_text(
        "Telegram канали\n\nБанер буде?",
        reply_markup=yes_no_keyboard("tg_banner")
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
    session = sessions.setdefault(user_id, new_session())
    data = query.data

    if ":" in data:
        key, value = data.split(":", 1)
    else:
        key, value = data, ""

    answer = value == "yes"

    steps = {
        "tg_banner": ("telegram", "banner", "Telegram канали\n\nReels буде?", "tg_reels"),
        "tg_reels": ("telegram", "reels", "Telegram канали\n\nТекст буде?", "tg_text"),
        "tg_text": ("telegram", "text", "Telegram канали\n\nПросувати буде?", "tg_promote"),
        "tg_promote": ("telegram", "promote", "Оберіть Telegram канали:", "choose_channels"),
        "fb_banner": ("facebook", "banner", "Facebook\n\nReels буде?", "fb_reels"),
        "fb_reels": ("facebook", "reels", "Facebook\n\nТекст буде?", "fb_text"),
        "fb_text": ("facebook", "text", "Facebook\n\nПросувати буде?", "fb_promote"),
        "fb_promote": ("facebook", "promote", "Instagram\n\nБанер буде?", "ig_banner"),
        "ig_banner": ("instagram", "banner", "Instagram\n\nReels буде?", "ig_reels"),
        "ig_reels": ("instagram", "reels", "Instagram\n\nПросувати буде?", "ig_promote"),
        "ig_promote": ("instagram", "promote", "YouTube Shorts\n\nВідео буде?", "yt_reels"),
        "yt_reels": ("youtube", "reels", "Перевіряю, які матеріали потрібні...", "after_questions"),
    }

    if key in steps:
        platform, field, next_text, next_step = steps[key]
        session[platform][field] = answer

        if next_step == "choose_channels":
            if session["telegram"]["banner"] or session["telegram"]["reels"] or session["telegram"]["text"]:
                session["step"] = "choose_channels"
                await query.edit_message_text(next_text, reply_markup=channels_keyboard(session["channels"]))
            else:
                session["step"] = "fb_banner"
                await query.edit_message_text("Facebook\n\nБанер буде?", reply_markup=yes_no_keyboard("fb_banner"))
            return

        if next_step == "after_questions":
            await go_to_materials(query, session)
            return

        session["step"] = next_step
        await query.edit_message_text(next_text, reply_markup=yes_no_keyboard(next_step))
        return

    if key == "channel":
        channel_key = value
        if channel_key in session["channels"]:
            session["channels"].remove(channel_key)
        else:
            session["channels"].append(channel_key)

        await query.edit_message_text("Оберіть Telegram канали:", reply_markup=channels_keyboard(session["channels"]))
        return

    if data == "channels_done":
        if (session["telegram"]["banner"] or session["telegram"]["reels"] or session["telegram"]["text"]) and not session["channels"]:
            await query.answer("Оберіть хоча б один Telegram канал", show_alert=True)
            return

        session["step"] = "fb_banner"
        await query.edit_message_text("Facebook\n\nБанер буде?", reply_markup=yes_no_keyboard("fb_banner"))
        return

    if key == "package":
        session["package"] = value

        if value == "single":
            session["days"] = 1
            await query.edit_message_text("⏳ Публікую зараз...")
            success, failed = await send_publication(context, session)
            await query.message.reply_text(make_result(success, failed))
            sessions.pop(user_id, None)
        else:
            session["step"] = "choose_days"
            await query.edit_message_text("На скільки днів публікувати?", reply_markup=days_keyboard())
        return

    if key == "days":
        session["days"] = int(value)
        await schedule_posts(context, query, user_id, session)
        return


async def go_to_materials(query, session):
    need_banner = session["telegram"]["banner"] or session["facebook"]["banner"] or session["instagram"]["banner"]
    need_reels = (
        session["telegram"]["reels"]
        or session["facebook"]["reels"]
        or session["instagram"]["reels"]
        or session["youtube"]["reels"]
    )
    need_text = session["telegram"]["text"] or session["facebook"]["text"]

    if not need_banner and not need_reels and not need_text:
        await query.edit_message_text("❌ Нічого не вибрано для публікації. Натисніть /start заново.")
        return

    if need_banner:
        session["step"] = "wait_banner"
        await query.edit_message_text("Надішліть банер / фото.")
    elif need_reels:
        session["step"] = "wait_reels"
        await query.edit_message_text("Надішліть Reels / відео.")
    elif need_text:
        session["step"] = "wait_text"
        await query.edit_message_text("Надішліть текст публікації.")
    else:
        session["step"] = "choose_package"
        await query.edit_message_text("Оберіть пакет публікації:", reply_markup=packages_keyboard())


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    user_id = update.effective_user.id
    session = sessions.get(user_id)

    if not session:
        await update.message.reply_text("Натисніть /start для нової публікації.")
        return

    step = session.get("step")

    if step == "wait_banner":
        if not update.message.photo:
            await update.message.reply_text("Надішліть саме фото / банер.")
            return

        session["banner_file_id"] = update.message.photo[-1].file_id

        if session["telegram"]["reels"] or session["facebook"]["reels"] or session["instagram"]["reels"] or session["youtube"]["reels"]:
            session["step"] = "wait_reels"
            await update.message.reply_text("✅ Банер отримано.\n\nНадішліть Reels / відео.")
        elif session["telegram"]["text"] or session["facebook"]["text"]:
            session["step"] = "wait_text"
            await update.message.reply_text("✅ Банер отримано.\n\nНадішліть текст публікації.")
        else:
            session["step"] = "choose_package"
            await update.message.reply_text("✅ Банер отримано.\n\nОберіть пакет:", reply_markup=packages_keyboard())
        return

    if step == "wait_reels":
        if not update.message.video:
            await update.message.reply_text("Надішліть саме відео / Reels.")
            return

        session["reels_file_id"] = update.message.video.file_id

        if session["telegram"]["text"] or session["facebook"]["text"]:
            session["step"] = "wait_text"
            await update.message.reply_text("✅ Reels отримано.\n\nНадішліть текст публікації.")
        else:
            session["step"] = "choose_package"
            await update.message.reply_text("✅ Reels отримано.\n\nОберіть пакет:", reply_markup=packages_keyboard())
        return

    await update.message.reply_text("Зараз бот не очікує медіа. Натисніть /start для нової публікації.")


async def client_form_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form = context.user_data.get("client_form")

    if not form:
        return False

    text = update.message.text
    step = form.get("step")
    data = form.get("data", {})
    form_type = form.get("type")

    # ---------- РЕЗЮМЕ ----------
    if form_type == "resume":
        if step == "resume_name":
            data["name"] = text
            form["step"] = "resume_city"
            form["data"] = data
            await update.message.reply_text("📍 Вкажіть місто:")
            return True

        if step == "resume_city":
            data["city"] = text
            form["step"] = "resume_specialty"
            form["data"] = data
            await update.message.reply_text("🛠 Вкажіть спеціальність:")
            return True

        if step == "resume_specialty":
            data["specialty"] = text
            form["step"] = "resume_position"
            form["data"] = data
            await update.message.reply_text("💼 Вкажіть бажану посаду:")
            return True

        if step == "resume_position":
            data["position"] = text
            form["step"] = "resume_education"
            form["data"] = data
            await update.message.reply_text("🎓 Вкажіть освіту:")
            return True

        if step == "resume_education":
            data["education"] = text
            form["step"] = "resume_experience"
            form["data"] = data
            await update.message.reply_text("📋 Опишіть досвід роботи:")
            return True

        if step == "resume_experience":
            data["experience"] = text
            form["step"] = "resume_salary"
            form["data"] = data
            await update.message.reply_text("💰 Вкажіть бажану зарплату:")
            return True

        if step == "resume_salary":
            data["salary"] = text
            form["step"] = "resume_contacts"
            form["data"] = data
            await update.message.reply_text("📞 Вкажіть контакти:")
            return True

        if step == "resume_contacts":
            data["contacts"] = text
            form["data"] = data

            admin_text = (
                "📥 Нове резюме\n\n"
                f"Тариф: {form.get('tariff')}\n"
                f"👤 Ім'я: {data.get('name')}\n"
                f"📍 Місто: {data.get('city')}\n"
                f"🛠 Спеціальність: {data.get('specialty')}\n"
                f"💼 Бажана посада: {data.get('position')}\n"
                f"🎓 Освіта: {data.get('education')}\n"
                f"📋 Досвід роботи: {data.get('experience')}\n"
                f"💰 Бажана зарплата: {data.get('salary')}\n"
                f"📞 Контакти: {data.get('contacts')}"
            )

            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
            await update.message.reply_text(
                "✅ Резюме прийнято.\n"
                "Ми перевіримо інформацію та зв'яжемось з вами."
            )

            context.user_data.pop("client_form", None)
            return True

    # ---------- БАНЕР / REELS / SHORTS ----------
    if form_type == "content_order":
        content_steps = [
            ("content_company", "company", "content_about", "📋 Коротко про компанію:"),
            ("content_about", "about", "content_goal", "🎯 Що просуваємо? Вакансію / акцію / відкриття / компанію / послугу:"),
            ("content_goal", "goal", "content_city", "📍 Вкажіть місто:"),
            ("content_city", "city", "content_address", "📍 Адреса / локація:"),
            ("content_address", "address", "content_main_info", "📝 Основна інформація для реклами:"),
            ("content_main_info", "main_info", "content_benefits", "🎁 Переваги / умови / зарплата / акція / знижка:"),
            ("content_benefits", "benefits", "content_audience", "🎯 Цільова аудиторія? Кого хочемо залучити?"),
            ("content_audience", "audience", "content_tim", "🤖 Використовувати Тіма у контенті? Так / Ні / На розсуд дизайнера"),
            ("content_tim", "tim", "content_style", "🎨 Який стиль реклами? Діловий / сучасний / молодіжний / преміум / смішний"),
            ("content_style", "style", "content_music", "🎵 Музика або стиль музики? Тренди / Rock / Pop / без різниці / свій варіант"),
            ("content_music", "music", "content_urgent", "🔥 Терміново? Так / Ні"),
            ("content_urgent", "urgent", "content_materials", "🖼 Є логотип, фото або відео матеріали? Так / Ні"),
            ("content_materials", "materials", "content_contacts", "📞 Вкажіть контакти:"),
            ("content_contacts", "contacts", "content_wishes", "✏️ Побажання до реклами / банера / відео:"),
        ]

        for current_step, field_name, next_step, question in content_steps:
            if step == current_step:
                data[field_name] = text
                form["step"] = next_step
                form["data"] = data
                await update.message.reply_text(question)
                return True

        if step == "content_wishes":
            data["wishes"] = text
            form["data"] = data

            admin_text = (
                "📥 Нове замовлення контенту\n\n"
                f"Тариф: {form.get('tariff')}\n"
                f"🏢 Компанія: {data.get('company')}\n"
                f"📋 Про компанію: {data.get('about')}\n"
                f"🎯 Що просуваємо: {data.get('goal')}\n"
                f"📍 Місто: {data.get('city')}\n"
                f"📍 Адреса / локація: {data.get('address')}\n"
                f"📝 Основна інформація: {data.get('main_info')}\n"
                f"🎁 Переваги / умови: {data.get('benefits')}\n"
                f"🎯 Цільова аудиторія: {data.get('audience')}\n"
                f"🤖 Тім у контенті: {data.get('tim')}\n"
                f"🎨 Стиль: {data.get('style')}\n"
                f"🎵 Музика: {data.get('music')}\n"
                f"🔥 Терміново: {data.get('urgent')}\n"
                f"🖼 Матеріали: {data.get('materials')}\n"
                f"📞 Контакти: {data.get('contacts')}\n"
                f"✏️ Побажання: {data.get('wishes')}"
            )

            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
            await update.message.reply_text(
                "✅ Заявка на контент прийнята.\n"
                "Ми перевіримо інформацію та зв'яжемось з вами."
            )

            context.user_data.pop("client_form", None)
            return True

    # ---------- START / BUSINESS: ВАКАНСІЯ + ПРОСУВАННЯ ----------
    if form_type == "vacancy_promo":
        vacancy_steps = [
            ("company", "company", "position", "💼 Вкажіть посаду:"),
            ("position", "position", "city", "📍 Вкажіть місто:"),
            ("city", "city", "address", "📍 Вкажіть адресу роботи:"),
            ("address", "address", "education", "🎓 Вкажіть освіту:"),
            ("education", "education", "experience", "📋 Вкажіть досвід роботи:"),
            ("experience", "experience", "schedule", "🕒 Вкажіть графік роботи:"),
            ("schedule", "schedule", "salary", "💰 Вкажіть зарплату:"),
            ("salary", "salary", "duties", "📝 Вкажіть обов'язки:"),
            ("duties", "duties", "benefits", "🎁 Що пропонує компанія?\nНаприклад: харчування, розвозка, житло, бонуси, навчання тощо."),
            ("benefits", "benefits", "contacts", "📞 Вкажіть контакти:"),
            ("contacts", "contacts", "days", "📅 На скільки днів розміщення?\n\n1 / 3 / 7 / 14 / 30"),
            ("days", "days", "promo_about", "📋 Коротко про компанію для реклами:\nНаприклад: чим займається компанія, чому їй можна довіряти."),
            ("promo_about", "promo_about", "promo_audience", "🎯 Цільова аудиторія? Кого хочемо залучити?"),
            ("promo_audience", "promo_audience", "promo_tim", "🤖 Використовувати Тіма у банерах / відео? Так / Ні / На розсуд дизайнера"),
            ("promo_tim", "promo_tim", "promo_style", "🎨 Який стиль реклами? Діловий / сучасний / молодіжний / преміум / смішний"),
            ("promo_style", "promo_style", "promo_music", "🎵 Музика або стиль музики для Reels / Shorts? Тренди / Rock / Pop / без різниці / свій варіант"),
            ("promo_music", "promo_music", "promo_urgent", "🔥 Терміново? Так / Ні"),
            ("promo_urgent", "promo_urgent", "promo_materials", "🖼 Є логотип, фото або відео матеріали? Так / Ні"),
            ("promo_materials", "promo_materials", "promo_wishes", "✏️ Побажання до банера / Reels / Shorts:"),
        ]

        for current_step, field_name, next_step, question in vacancy_steps:
            if step == current_step:
                data[field_name] = text
                form["step"] = next_step
                form["data"] = data
                await update.message.reply_text(question)
                return True

        if step == "promo_wishes":
            data["promo_wishes"] = text
            form["data"] = data

            admin_text = (
                "📥 Нова заявка Start / Business\n\n"
                f"Тариф: {form.get('tariff')}\n\n"
                "👨‍💼 ВАКАНСІЯ\n"
                f"🏢 Компанія: {data.get('company')}\n"
                f"💼 Посада: {data.get('position')}\n"
                f"📍 Місто: {data.get('city')}\n"
                f"📍 Адреса: {data.get('address')}\n"
                f"🎓 Освіта: {data.get('education')}\n"
                f"📋 Досвід роботи: {data.get('experience')}\n"
                f"🕒 Графік роботи: {data.get('schedule')}\n"
                f"💰 Зарплата: {data.get('salary')}\n"
                f"📝 Обов'язки: {data.get('duties')}\n"
                f"🎁 Компанія пропонує: {data.get('benefits')}\n"
                f"📞 Контакти: {data.get('contacts')}\n"
                f"📅 Днів розміщення: {data.get('days')}\n\n"
                "🎨 БРИФ ДЛЯ КОНТЕНТУ\n"
                f"📋 Про компанію: {data.get('promo_about')}\n"
                f"🎯 Цільова аудиторія: {data.get('promo_audience')}\n"
                f"🤖 Тім у контенті: {data.get('promo_tim')}\n"
                f"🎨 Стиль: {data.get('promo_style')}\n"
                f"🎵 Музика: {data.get('promo_music')}\n"
                f"🔥 Терміново: {data.get('promo_urgent')}\n"
                f"🖼 Матеріали: {data.get('promo_materials')}\n"
                f"✏️ Побажання: {data.get('promo_wishes')}"
            )

            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
            await update.message.reply_text(
                "✅ Заявка Start / Business прийнята.\n"
                "Ми перевіримо інформацію та зв'яжемось з вами."
            )

            context.user_data.pop("client_form", None)
            return True

    # ---------- ЗВИЧАЙНА ВАКАНСІЯ ----------
    vacancy_steps = [
        ("company", "company", "position", "💼 Вкажіть посаду:"),
        ("position", "position", "city", "📍 Вкажіть місто:"),
        ("city", "city", "address", "📍 Вкажіть адресу роботи:"),
        ("address", "address", "education", "🎓 Вкажіть освіту:"),
        ("education", "education", "experience", "📋 Вкажіть досвід роботи:"),
        ("experience", "experience", "schedule", "🕒 Вкажіть графік роботи:"),
        ("schedule", "schedule", "salary", "💰 Вкажіть зарплату:"),
        ("salary", "salary", "duties", "📝 Вкажіть обов'язки:"),
        ("duties", "duties", "benefits", "🎁 Що пропонує компанія?\nНаприклад: харчування, розвозка, житло, бонуси, навчання тощо."),
        ("benefits", "benefits", "contacts", "📞 Вкажіть контакти:"),
        ("contacts", "contacts", "days", "📅 На скільки днів розміщення?\n\n1 / 3 / 7 / 14 / 30"),
    ]

    for current_step, field_name, next_step, question in vacancy_steps:
        if step == current_step:
            data[field_name] = text
            form["step"] = next_step
            form["data"] = data
            await update.message.reply_text(question)
            return True

    if step == "days":
        data["days"] = text
        form["data"] = data

        admin_text = (
            "📥 Нова вакансія\n\n"
            f"Тариф: {form.get('tariff')}\n"
            f"🏢 Компанія: {data.get('company')}\n"
            f"💼 Посада: {data.get('position')}\n"
            f"📍 Місто: {data.get('city')}\n"
            f"📍 Адреса: {data.get('address')}\n"
            f"🎓 Освіта: {data.get('education')}\n"
            f"📋 Досвід роботи: {data.get('experience')}\n"
            f"🕒 Графік роботи: {data.get('schedule')}\n"
            f"💰 Зарплата: {data.get('salary')}\n"
            f"📝 Обов'язки: {data.get('duties')}\n"
            f"🎁 Компанія пропонує: {data.get('benefits')}\n"
            f"📞 Контакти: {data.get('contacts')}\n"
            f"📅 Днів розміщення: {data.get('days')}"
        )

        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
        await update.message.reply_text(
            "✅ Заявка прийнята.\n"
            "Ми перевіримо інформацію та зв'яжемось з вами."
        )

        context.user_data.pop("client_form", None)
        return True

    return False


async def tim_ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""

    try:
        response = await asyncio.to_thread(
            openai_client.responses.create,
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "Ти Тім AI, помічник сервісу HireUA. "
                        "Спілкуйся мовою користувача: українською або російською. "
                        "Можеш безкоштовно спілкуватися на загальні теми, відповідати на питання, "
                        "допомагати порадами щодо роботи, резюме та вакансій. "
                        "Можеш допомогти користувачу текстом правильно підготувати заявку на безкоштовну вакансію або резюме. "
                        "Якщо користувач хоче офіційно подати заявку — порадь натиснути /start і вибрати потрібний розділ у меню. "
                        "Без активного пакета Start або Business НЕ створюй банери, промпти для зображень, Reels/Shorts, "
                        "рекламні тексти, контент-плани або готові матеріали для публікації. "
                        "Якщо користувач просить платний контент — поясни, що це доступно в пакетах Start або Business "
                        "і запропонуй зв'язатися з HR менеджером @HireUkraine. "
                        "Усі матеріали для платного контенту можуть створюватися тільки з брендингом HireUA. "
                        "Нічого не публікуй і не обіцяй автоматичну публікацію. Публікацію підтверджує адміністратор HireUA."
                    )
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ]
        )

        await update.message.reply_text(response.output_text)

    except Exception as e:
        print("TIM AI ERROR:", e, flush=True)
        await update.message.reply_text(
            "⚠️ Тим AI тимчасово недоступний. Спробуйте ще раз трохи пізніше."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await client_form_text(update, context):
        return

    if not admin_only(update):
        await tim_ai_reply(update, context)
        return

    user_id = update.effective_user.id
    session = sessions.get(user_id)

    if not session or session.get("step") != "wait_text":
        await tim_ai_reply(update, context)
        return

    session["text"] = update.message.text or ""
    session["step"] = "choose_package"

    await update.message.reply_text("✅ Текст отримано.\n\nОберіть пакет:", reply_markup=packages_keyboard())


async def telegram_file_url(context: ContextTypes.DEFAULT_TYPE, file_id: str):
    tg_file = await context.bot.get_file(file_id)
    file_path = tg_file.file_path

    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path

    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


async def download_telegram_video_to_temp(context: ContextTypes.DEFAULT_TYPE, file_id: str):
    tg_file = await context.bot.get_file(file_id)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    temp_path = temp_file.name
    temp_file.close()

    await tg_file.download_to_drive(temp_path)
    return temp_path


def graph_post(endpoint, data):
    data["access_token"] = PAGE_ACCESS_TOKEN
    response = requests.post(f"{GRAPH_URL}/{endpoint}", data=data, timeout=120)

    try:
        payload = response.json()
    except Exception:
        raise RuntimeError(f"Meta returned non-JSON response: {response.text}")

    if response.status_code >= 400 or "error" in payload:
        raise RuntimeError(payload)

    return payload


def publish_facebook_text(text):
    if not text:
        return
    return graph_post(f"{FB_PAGE_ID}/feed", {"message": text})


def publish_facebook_photo(image_url, caption):
    return graph_post(f"{FB_PAGE_ID}/photos", {"url": image_url, "caption": caption or ""})


def publish_facebook_video(video_url, description):
    return graph_post(f"{FB_PAGE_ID}/videos", {"file_url": video_url, "description": description or ""})


def get_instagram_media_status(creation_id):
    response = requests.get(
        f"{GRAPH_URL}/{creation_id}",
        params={"fields": "status_code", "access_token": PAGE_ACCESS_TOKEN},
        timeout=60,
    )

    payload = response.json()

    if response.status_code >= 400 or "error" in payload:
        raise RuntimeError(payload)

    return payload


def wait_instagram_media_ready(creation_id, max_attempts=60, delay=5):
    last_status = None
    last_response = None

    for attempt in range(1, max_attempts + 1):
        check = get_instagram_media_status(creation_id)

        last_response = check
        last_status = check.get("status_code")

        print(f"Instagram media status attempt {attempt}/{max_attempts}: {last_status}", flush=True)

        if last_status == "FINISHED":
            return True

        if last_status == "ERROR":
            raise RuntimeError(check)

        time_module.sleep(delay)

    raise RuntimeError({
        "message": "Instagram media not ready after waiting",
        "creation_id": creation_id,
        "last_status": last_status,
        "last_response": last_response,
    })


def is_media_not_ready_error(error_text):
    return (
        "Media ID is not available" in error_text
        or "Медиаданные не готовы" in error_text
        or "2207027" in error_text
        or "9007" in error_text
    )


def is_instagram_action_blocked_but_maybe_published(error_text):
    return (
        "2207051" in error_text
        or "Application request limit reached" in error_text
        or "Действие заблокировано" in error_text
    )


def instagram_publish_with_retry(creation_id, attempts=5, delay=20):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            print(f"Instagram publish attempt {attempt}/{attempts}", flush=True)
            return graph_post(f"{IG_USER_ID}/media_publish", {"creation_id": creation_id})
        except Exception as e:
            last_error = e
            error_text = str(e)

            print(f"Instagram publish error attempt {attempt}: {error_text}", flush=True)

            if is_media_not_ready_error(error_text) and attempt < attempts:
                time_module.sleep(delay)
                continue

            raise

    raise RuntimeError(last_error)


def publish_instagram_photo(image_url, caption):
    create = graph_post(f"{IG_USER_ID}/media", {"image_url": image_url, "caption": caption or ""})
    creation_id = create["id"]

    time_module.sleep(20)
    wait_instagram_media_ready(creation_id, max_attempts=60, delay=5)

    return instagram_publish_with_retry(creation_id, attempts=5, delay=20)


def publish_instagram_reels(video_url, caption):
    create = graph_post(f"{IG_USER_ID}/media", {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption or "",
    })

    creation_id = create["id"]

    time_module.sleep(30)
    wait_instagram_media_ready(creation_id, max_attempts=90, delay=5)

    return instagram_publish_with_retry(creation_id, attempts=5, delay=30)


def youtube_available():
    return bool(YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN)


def get_youtube_service():
    creds = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )

    creds.refresh(GoogleRequest())
    return build("youtube", "v3", credentials=creds)


def make_youtube_title(text):
    title = (text or "").strip().split("\n")[0].strip()

    if not title:
        title = "HireUA Shorts"

    if len(title) > 90:
        title = title[:90].strip()

    if "#Shorts" not in title:
        title = f"{title} #Shorts"

    return title


def make_youtube_description(text):
    description = text or ""

    if "#Shorts" not in description:
        description += "\n\n#Shorts #HireUA #Робота #Вакансії"

    return description.strip()


def publish_youtube_short(video_path, text):
    youtube = get_youtube_service()

    body = {
        "snippet": {
            "title": make_youtube_title(text),
            "description": make_youtube_description(text),
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")

    request_upload = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None

    while response is None:
        status, response = request_upload.next_chunk()

    return response


TIM_BOT_URL = "https://t.me/HireUA_AI_bot?start=menu"


def tim_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Написати Тіму", url=TIM_BOT_URL)]
    ])


def add_tim_footer(text: str, platform: str = "social") -> str:
    base = (text or "").strip()

    if "HireUA_AI_bot" in base or "Написати Тіму" in base:
        return base

    if platform == "instagram":
        footer = "🤖 Подати заявку через Telegram: @HireUA_AI_bot"
    else:
        footer = "🤖 Написати Тіму: https://t.me/HireUA_AI_bot"

    return f"{base}\n\n{footer}" if base else footer


async def send_publication(context: ContextTypes.DEFAULT_TYPE, session: dict):
    success = []
    failed = []

    text = session.get("text") or ""
    telegram_keyboard = tim_keyboard()
    facebook_text = add_tim_footer(text, "facebook")
    instagram_text = add_tim_footer(text, "instagram")
    youtube_text = add_tim_footer(text, "youtube")

    banner_url = None
    reels_url = None

    try:
        if session.get("banner_file_id"):
            banner_url = await telegram_file_url(context, session["banner_file_id"])

        if session.get("reels_file_id"):
            reels_url = await telegram_file_url(context, session["reels_file_id"])
    except Exception as e:
        failed.append(f"Telegram file URL: {e}")

    if session["telegram"]["banner"] or session["telegram"]["reels"] or session["telegram"]["text"]:
        for key in session["channels"]:
            name, chat = CHANNELS[key]
            try:
                if session["telegram"]["banner"] and session.get("banner_file_id"):
                    await context.bot.send_photo(
                        chat_id=chat,
                        photo=session["banner_file_id"],
                        caption=text if session["telegram"]["text"] else None,
                        reply_markup=telegram_keyboard,
                    )
                    success.append(f"{chat}: банер")

                if session["telegram"]["reels"] and session.get("reels_file_id"):
                    await context.bot.send_video(
                        chat_id=chat,
                        video=session["reels_file_id"],
                        caption=text if session["telegram"]["text"] and not session["telegram"]["banner"] else None,
                        reply_markup=telegram_keyboard,
                    )
                    success.append(f"{chat}: Reels")

                if session["telegram"]["text"] and text and not session["telegram"]["banner"] and not session["telegram"]["reels"]:
                    await context.bot.send_message(
                        chat_id=chat,
                        text=text,
                        reply_markup=telegram_keyboard,
                    )
                    success.append(f"{chat}: текст")

            except Exception as e:
                failed.append(f"{chat}: {e}")

    if FB_PAGE_ID and PAGE_ACCESS_TOKEN:
        try:
            if session["facebook"]["banner"] and banner_url:
                await asyncio.to_thread(publish_facebook_photo, banner_url, facebook_text if session["facebook"]["text"] else add_tim_footer("", "facebook"))
                success.append("Facebook: банер")

            if session["facebook"]["reels"] and reels_url:
                await asyncio.to_thread(publish_facebook_video, reels_url, facebook_text if session["facebook"]["text"] else add_tim_footer("", "facebook"))
                success.append("Facebook: Reels/відео")

            if session["facebook"]["text"] and text and not session["facebook"]["banner"] and not session["facebook"]["reels"]:
                await asyncio.to_thread(publish_facebook_text, facebook_text)
                success.append("Facebook: текст")

        except Exception as e:
            failed.append(f"Facebook: {e}")
    elif session["facebook"]["banner"] or session["facebook"]["reels"] or session["facebook"]["text"]:
        failed.append("Facebook: немає FB_PAGE_ID або PAGE_ACCESS_TOKEN")

    if IG_USER_ID and PAGE_ACCESS_TOKEN:
        try:
            if session["instagram"]["banner"] and banner_url:
                await asyncio.to_thread(publish_instagram_photo, banner_url, instagram_text)
                success.append("Instagram: банер")

            if session["instagram"]["reels"] and reels_url:
                await asyncio.to_thread(publish_instagram_reels, reels_url, instagram_text)
                success.append("Instagram: Reels")

        except Exception as e:
            error_text = str(e)

            if is_instagram_action_blocked_but_maybe_published(error_text):
                success.append("Instagram: можливо опубліковано, перевір акаунт")
            else:
                failed.append(f"Instagram: {e}")
    elif session["instagram"]["banner"] or session["instagram"]["reels"]:
        failed.append("Instagram: немає IG_USER_ID або PAGE_ACCESS_TOKEN")

    if session.get("youtube", {}).get("reels"):
        if not session.get("reels_file_id"):
            failed.append("YouTube: немає відео / Reels")
        elif not youtube_available():
            failed.append("YouTube: немає YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET або YOUTUBE_REFRESH_TOKEN")
        else:
            video_path = None

            try:
                video_path = await download_telegram_video_to_temp(context, session["reels_file_id"])
                await asyncio.to_thread(publish_youtube_short, video_path, youtube_text)
                success.append("YouTube: Shorts")
            except Exception as e:
                failed.append(f"YouTube: {e}")
            finally:
                if video_path and os.path.exists(video_path):
                    os.remove(video_path)

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
    days = int(session.get("days", 1))

    publications_per_day = len(times)
    total_publications = publications_per_day * days

    slots = find_free_slots(total_publications)

    if len(slots) < total_publications:
        await query.edit_message_text(
            "⚠️ Не вдалося знайти достатньо вільних слотів на 60 днів вперед.\n"
            "Спробуйте меншу кількість днів або очистіть scheduled_posts.json."
        )
        return

    entries = add_schedule_entries(saved_session, slots, package_name)

    for entry in entries:
        register_schedule_job(context.job_queue, entry)

    first_slot = slots[0].strftime("%d.%m.%Y %H:%M")
    last_slot = slots[-1].strftime("%d.%m.%Y %H:%M")
    preview = "\n".join(slot.strftime("%d.%m %H:%M") for slot in slots[:12])

    if len(slots) > 12:
        preview += f"\n... ще {len(slots) - 12} публікацій"

    await query.edit_message_text(
        f"✅ Публікацію заплановано автоматично\n\n"
        f"Пакет: {package_name}\n"
        f"Днів: {days}\n"
        f"Публікацій на платформу: {total_publications}\n\n"
        f"Вікна: 08:00–10:00, 12:00–14:00, 16:00–18:00, 18:00–20:00\n"
        f"Крок: кожні {SLOT_STEP_MINUTES} хвилин\n\n"
        f"Перша: {first_slot}\n"
        f"Остання: {last_slot}\n\n"
        f"Найближчі слоти:\n{preview}"
    )

    sessions.pop(user_id, None)


async def scheduled_publish(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data or {}

    if isinstance(job_data, dict) and "session" in job_data:
        entry_id = job_data.get("id")
        session = job_data.get("session")
    else:
        entry_id = None
        session = job_data

    if not session:
        if entry_id:
            update_schedule_entry(entry_id, "failed", failed=["Немає session у задачі"])
        return

    if entry_id:
        update_schedule_entry(entry_id, "running")

    success, failed = await send_publication(context, session)

    if entry_id:
        update_schedule_entry(entry_id, "done" if not failed else "done_with_errors", success=success, failed=failed)

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text="🕒 Запланована публікація виконана\n\n" + make_result(success, failed),
            )
        except Exception:
            pass


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    await update.message.reply_text("Натисніть /start для створення нової публікації.")


async def client_resume_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["client_form"] = {
        "type": "resume",
        "tariff": "Резюме",
        "step": "resume_name",
        "data": {},
    }

    await query.message.reply_text("👤 Вкажіть імʼя:")


async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    print("STARTING BOT", flush=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(client_resume_start, pattern="^client_resume$"))
    app.add_handler(CallbackQueryHandler(client_buttons, pattern="^(client_|vacancy_|content_)"))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.ALL, fallback))

    await app.initialize()
    await app.start()

    if app.job_queue:
        restore_pending_schedule_jobs(app.job_queue)

    await app.updater.start_polling(drop_pending_updates=True)

    print("POLLING STARTED", flush=True)

    while True:
        await asyncio.sleep(3600)


def main():
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
