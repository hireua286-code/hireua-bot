
# === STAGE 5 PLAN (to be integrated) ===
# Publication windows:
# Morning 08:00-11:30
# Day 12:00-16:30
# Evening 17:00-22:00
# Start: 1/1/1
# Business: 2/2/2
# Random slot selection inside window
# Platform min gaps:
# Telegram 5m, Facebook 15m, Instagram 20m, YouTube 20m
# Admin command: /time
# =======================================

import os
import json
import base64
import re
from uuid import uuid4

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

import asyncio
import threading
import time as time_module
import random
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
from telegram.error import TimedOut, NetworkError, RetryAfter

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
from openai import OpenAI
import gspread

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None

from handlers.client import client_main_keyboard, client_buttons

BOT_TOKEN = os.getenv("BOT_TOKEN")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "8734709909"))

FB_PAGE_ID = os.getenv("FB_PAGE_ID")
IG_USER_ID = os.getenv("IG_USER_ID")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

BASE_URL = os.getenv("BASE_URL", "https://hireua-bot.onrender.com")
GOOGLE_SHEET_ID = "1-HxPVaoQmDgNONc5D9yfs1kKt0goDVv8bp1fC3HEpR4"
GOOGLE_CREDENTIALS_FILE = "/etc/secrets/key_users_json"

# Google Drive storage. Uses the same service account JSON as Google Sheets.
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
GOOGLE_DRIVE_ROOT_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_NAME", "HireUa")
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

KYIV_TZ = pytz.timezone("Europe/Kyiv")
GRAPH_URL = "https://graph.facebook.com/v25.0"

CHANNELS = {
    "kyiv": ("Київ", "@HireKyiv"),
    "lviv": ("Львів", "@HireLviv"),
    "odesa": ("Одеса", "@HireOdesa"),
    "dnipro": ("Дніпро", "@HireDnipro"),
    "kharkiv": ("Харків", "@HireKharkiv"),
    "ukraine": ("Україна", "@UkraineHire"),
}

PACKAGES = {
    "single": ("Разово", []),
    "start": ("Start", ["08:00", "12:00", "16:00"]),
    "business": ("Business", ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]),
}

# === STAGE 5: розумний планувальник публікацій ===
# Публікації не летять пачкою. Бот розкладає їх по блоках дня
# і додає випадкове зміщення, щоб розклад виглядав природно.
SCHEDULE_FILE = "scheduled_posts.json"

DAY_PARTS = {
    "morning": (8, 0, 11, 30),
    "day": (12, 0, 16, 30),
    "evening": (17, 0, 22, 0),
}

PACKAGE_DAY_DISTRIBUTION = {
    "single": ["now"],
    "start": ["morning", "day", "evening"],
    "business": ["morning", "morning", "day", "day", "evening", "evening"],
}

PLATFORM_MIN_GAP_MINUTES = {
    "telegram": 5,
    "facebook": 15,
    "instagram": 20,
    "youtube": 20,
}

# Для нового каналу YouTube краще не пробивати денний upload-limit.
YOUTUBE_DAILY_LIMIT = int(os.getenv("YOUTUBE_DAILY_LIMIT", "10"))

# Крок пошуку всередині блоку. Чим менше крок, тим більш природний розклад.
SLOT_STEP_MINUTES = 5

sessions = {}
web_app = Flask(__name__)

# Stage 4: захист від зависань Telegram/OpenAI.
# Якщо Telegram або генерація картинки довго не відповідають, бот не мовчить безкінечно.
IMAGE_GENERATION_TIMEOUT = int(os.getenv("IMAGE_GENERATION_TIMEOUT", "180"))


async def safe_reply_text(update: Update, text: str, **kwargs):
    try:
        return await update.message.reply_text(text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 5)) + 1)
        try:
            return await update.message.reply_text(text, **kwargs)
        except Exception as err:
            print("TELEGRAM SAFE REPLY TEXT ERROR AFTER RETRY:", err, flush=True)
            return None
    except (TimedOut, NetworkError) as e:
        print("TELEGRAM SAFE REPLY TEXT ERROR:", e, flush=True)
        return None
    except Exception as e:
        print("TELEGRAM SAFE REPLY TEXT UNKNOWN ERROR:", e, flush=True)
        return None


async def safe_send_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 5)) + 1)
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as err:
            print("TELEGRAM SAFE SEND MESSAGE ERROR AFTER RETRY:", err, flush=True)
            return None
    except (TimedOut, NetworkError) as e:
        print("TELEGRAM SAFE SEND MESSAGE ERROR:", e, flush=True)
        return None
    except Exception as e:
        print("TELEGRAM SAFE SEND MESSAGE UNKNOWN ERROR:", e, flush=True)
        return None


async def safe_reply_photo(update: Update, photo, caption: str = None, **kwargs):
    try:
        return await update.message.reply_photo(photo=photo, caption=caption, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 5)) + 1)
        try:
            return await update.message.reply_photo(photo=photo, caption=caption, **kwargs)
        except Exception as err:
            print("TELEGRAM SAFE REPLY PHOTO ERROR AFTER RETRY:", err, flush=True)
            return None
    except (TimedOut, NetworkError) as e:
        print("TELEGRAM SAFE REPLY PHOTO ERROR:", e, flush=True)
        try:
            return await update.message.reply_document(document=photo, caption=caption or "Зображення готове ✅")
        except Exception as err:
            print("TELEGRAM SAFE REPLY DOCUMENT FALLBACK ERROR:", err, flush=True)
            await safe_reply_text(update, "⚠️ Зображення готове, але Telegram не зміг його відправити. Спробуйте ще раз через хвилину.")
            return None
    except Exception as e:
        print("TELEGRAM SAFE REPLY PHOTO UNKNOWN ERROR:", e, flush=True)
        await safe_reply_text(update, "⚠️ Telegram не зміг відправити зображення. Спробуйте ще раз через хвилину.")
        return None


async def safe_send_photo(context: ContextTypes.DEFAULT_TYPE, chat_id: int, photo, caption: str = None, **kwargs):
    try:
        return await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 5)) + 1)
        try:
            return await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, **kwargs)
        except Exception as err:
            print("TELEGRAM SAFE SEND PHOTO ERROR AFTER RETRY:", err, flush=True)
            return None
    except (TimedOut, NetworkError) as e:
        print("TELEGRAM SAFE SEND PHOTO ERROR:", e, flush=True)
        try:
            return await context.bot.send_document(chat_id=chat_id, document=photo, caption=caption or "Зображення готове ✅")
        except Exception as err:
            print("TELEGRAM SAFE SEND DOCUMENT FALLBACK ERROR:", err, flush=True)
            return None
    except Exception as e:
        print("TELEGRAM SAFE SEND PHOTO UNKNOWN ERROR:", e, flush=True)
        return None

def detect_user_category(text: str) -> str:
    t = (text or "").lower()

    if any(w in t for w in ["вакансия", "вакансія", "ищу сотрудников", "нужны люди", "роботодавець"]):
        return "employer"

    if any(w in t for w in ["резюме", "ищу работу", "шукаю роботу", "вакансии", "вакансії"]):
        return "job_seeker"

    if any(w in t for w in ["реклама", "просування", "продвижение", "business", "start", "instagram", "facebook"]):
        return "business"

    return "chat"


def save_user_to_sheet(update: Update, last_message: str = ""):
    try:
        user = update.effective_user
        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")

        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Users")

        user_id = str(user.id)
        rows = sheet.get_all_values()

        found_row = None
        for i, row in enumerate(rows[1:], start=2):
            if len(row) >= 3 and row[2] == user_id:
                found_row = i
                break

        category = detect_user_category(last_message)

        if found_row:
            old_count = 0
            try:
                old_count = int(sheet.cell(found_row, 8).value or 0)
            except Exception:
                old_count = 0

            sheet.update(f"B{found_row}:I{found_row}", [[
                now,
                user_id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                category,
                old_count + 1,
                last_message or "",
            ]])
        else:
            sheet.append_row([
                now,
                now,
                user_id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                category,
                1,
                last_message or "",
            ])

    except Exception as e:
        print("GOOGLE SHEETS ERROR:", e, flush=True)


def append_vacancy_to_sheet(data: dict, tariff: str = ""):
    try:
        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Vacancies")

        sheet.append_row([
            now,
            data.get("company", ""),
            data.get("position", ""),
            data.get("city", ""),
            data.get("address", ""),
            data.get("education", ""),
            data.get("experience", ""),
            data.get("schedule", ""),
            data.get("salary", ""),
            data.get("duties", ""),
            data.get("benefits", ""),
            data.get("contacts", ""),
            data.get("days", ""),
            tariff,
            "Новий",
        ])
    except Exception as e:
        print("GOOGLE VACANCY ERROR:", e, flush=True)


def append_client_to_sheet(data: dict, tariff: str = "", user=None):
    try:
        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Clients")

        telegram_id = user.id if user else ""
        username = f"@{user.username}" if user and user.username else ""
        name = " ".join([x for x in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if x]).strip()

        sheet.append_row([
            telegram_id,
            username,
            name,
            data.get("contacts", ""),
            tariff,
            "pending",
            now,
        ])
    except Exception as e:
        print("GOOGLE CLIENTS ERROR:", e, flush=True)


def user_has_paid_package(user) -> bool:
    """Перевіряє доступ клієнта до створення банерів/Reels через вкладку Clients."""
    try:
        if not user:
            return False

        if int(getattr(user, "id", 0)) == OWNER_ID:
            return True

        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Clients")
        rows = sheet.get_all_records()
        user_id = str(user.id).strip()

        for row in rows:
            telegram_id = str(
                row.get("telegram_id")
                or row.get("Telegram ID")
                or row.get("telegram id")
                or row.get("id")
                or ""
            ).strip()
            status = str(
                row.get("status")
                or row.get("Status")
                or row.get("Статус")
                or ""
            ).strip().lower()

            if telegram_id == user_id and status == "paid":
                return True

        return False
    except Exception as e:
        print("GOOGLE CLIENTS ACCESS ERROR:", e, flush=True)
        return False


def paid_required_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("/UsersStart — пакет Start", callback_data="vacancy_start")],
        [InlineKeyboardButton("/UsersBusiness — пакет Business", callback_data="vacancy_business")],
    ])


async def deny_unpaid_content_access(message):
    await message.reply_text(
        "🔒 Створення банерів та Reels доступне клієнтам з активним пакетом Start або Business.\n\n"
        "Для активації пакета зв'яжіться з адміністратором:\n\n"
        "@HireUkraine",
        reply_markup=paid_required_keyboard(),
    )


async def start_paid_content_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, order_type: str = "banner"):
    """Запускає AI-діалог для створення банера або Reels без повторного брифа."""
    message = update.message if update.message else update.callback_query.message
    user = update.effective_user

    if not user_has_paid_package(user):
        await deny_unpaid_content_access(message)
        return

    # Режим створення контенту має пріоритет над анкетами.
    context.user_data.pop("client_form", None)

    if order_type == "reels_series":
        context.user_data["tim_content_order"] = {
            "tariff": "Reels / Shorts",
            "order_type": "reels_series",
            "data": {},
            "status": "В РОБОТІ",
            "stage": "awaiting_idea",
            "last_files": [],
            "client_edits": [],
            "publish_text": "",
        }
        await message.reply_text(
            "🎬 Напишіть задачу для Reels / Shorts в 1–2 реченнях.\n\n"
            "Наприклад:\n"
            "• Рилс для вакансії касира в Києві\n"
            "• Реклама відкриття магазину\n"
            "• Рилс для акції або знижки\n\n"
            "Довгий промпт не потрібен. Я сам запропоную декілька ідей і сценарій."
        )
        return

    context.user_data["tim_content_order"] = {
        "tariff": "Банер",
        "order_type": "banner",
        "data": {},
        "status": "В РОБОТІ",
        "stage": "awaiting_idea",
        "last_files": [],
        "client_edits": [],
        "publish_text": "",
    }
    await message.reply_text(
        "🖼 Напишіть задачу для банера в 1–2 реченнях.\n\n"
        "Наприклад:\n"
        "• Банер для вакансії касира в Києві\n"
        "• Реклама автомийки\n"
        "• Банер відкриття магазину\n\n"
        "Довгий промпт не потрібен. Я сам запропоную кілька концепцій."
    )


def append_resume_to_sheet(data: dict):
    try:
        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Resumes")

        sheet.append_row([
            now,
            data.get("name", ""),
            data.get("city", ""),
            data.get("specialty", ""),
            data.get("position", ""),
            data.get("education", ""),
            data.get("experience", ""),
            data.get("salary", ""),
            data.get("contacts", ""),
            "Новий",
        ])
    except Exception as e:
        print("GOOGLE RESUME ERROR:", e, flush=True)


def append_content_brief_to_sheet(data: dict, tariff: str = "", user_id: int = None, order_type: str = ""):
    try:
        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("ContentBriefs")

        sheet.append_row([
            now,
            user_id or "",
            tariff,
            order_type,
            data.get("company", ""),
            data.get("about", ""),
            data.get("goal", ""),
            data.get("city", ""),
            data.get("address", ""),
            data.get("main_info", ""),
            data.get("benefits", ""),
            data.get("audience", ""),
            data.get("tim", ""),
            data.get("style", ""),
            data.get("music", ""),
            data.get("urgent", ""),
            data.get("materials", ""),
            data.get("contacts", ""),
            data.get("wishes", ""),
            "НА ПОГОДЖЕННІ",
            "",
        ])
    except Exception as e:
        print("GOOGLE CONTENT BRIEF ERROR:", e, flush=True)


def update_content_brief_status_in_sheet(user_id: int, status: str):
    try:
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("ContentBriefs")
        values = sheet.get_all_values()
        if not values:
            return

        # Шукаємо останній рядок цього користувача. За нашою структурою user_id у 2 колонці.
        target_row = None
        for idx in range(len(values), 1, -1):
            row = values[idx - 1]
            if len(row) > 1 and str(row[1]) == str(user_id):
                target_row = idx
                break

        if target_row:
            sheet.update_cell(target_row, 20, status)
            sheet.update_cell(target_row, 21, datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M"))
    except Exception as e:
        print("GOOGLE CONTENT STATUS ERROR:", e, flush=True)


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
        [InlineKeyboardButton("🖼 Банер — 500 грн", callback_data="content_banner")],
        [InlineKeyboardButton("🎬 Серія банерів для Reels / Shorts — 800 грн", callback_data="content_reels")],
        [InlineKeyboardButton("🚀 Start — просування 7 днів", callback_data="content_start")],
        [InlineKeyboardButton("💼 Business — активне просування 7 днів", callback_data="content_business")],
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
        context.user_data.pop("tim_content_order", None)
        context.user_data["client_form"] = {
            "type": "vacancy",
            "tariff": "Безкоштовна текстова вакансія",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text("🏢 Вкажіть назву компанії:")
        return

    if data == "vacancy_start":
        context.user_data.pop("tim_content_order", None)
        context.user_data["client_form"] = {
            "type": "vacancy_promo",
            "tariff": "Start",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text(
            "🚀 Пакет Start\n\n"
            "Зараз заповнимо заявку на пакет Start.\n\n"
            "🏢 Вкажіть назву компанії:"
        )
        return

    if data == "vacancy_business":
        context.user_data.pop("tim_content_order", None)
        context.user_data["client_form"] = {
            "type": "vacancy_promo",
            "tariff": "Business",
            "step": "company",
            "data": {},
        }
        await query.message.reply_text(
            "💼 Пакет Business\n\n"
            "Зараз заповнимо заявку на пакет Business.\n\n"
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

    if data == "content_banner":
        await start_paid_content_chat(update, context, order_type="banner")
        return

    if data == "content_reels":
        await start_paid_content_chat(update, context, order_type="reels_series")
        return

    if data in ("content_start", "content_business"):
        context.user_data.pop("tim_content_order", None)
        tariff_map = {
            "content_start": "Start",
            "content_business": "Business",
        }
        order_type_map = {
            "content_start": "campaign",
            "content_business": "campaign",
        }
        context.user_data["client_form"] = {
            "type": "content_order",
            "tariff": tariff_map.get(data, "Просування"),
            "order_type": order_type_map.get(data, "banner"),
            "step": "content_company",
            "data": {},
        }
        await query.message.reply_text(
            "📢 Просування бізнесу / бренду\n\n"
            "Зараз заповнимо короткий бриф для рекламної кампанії HireUA.\n\n"
            "🏢 Вкажіть назву компанії / бренду:"
        )
        return

    if data == "client_prices":
        await query.message.reply_text(
            "💰 Тарифи HireUA\n\n"
            "🆓 Текстові вакансії — безкоштовно в Telegram каналах HireUA.\n"
            "🆓 Текстові резюме — безкоштовно в Telegram каналах HireUA.\n\n"
            "🚀 Start — 4500 грн / 7 днів\n"
            "• Telegram — 3 публікації щодня\n"
            "• Instagram — 3 публікації щодня\n"
            "• Facebook — 3 публікації щодня\n"
            "• YouTube Shorts — 3 публікації щодня (відео)\n"
            "• Разом: 84 публікації за 7 днів\n\n"
            "💼 Business — 7500 грн / 7 днів\n"
            "• Telegram — 6 публікацій щодня\n"
            "• Instagram — 6 публікацій щодня\n"
            "• Facebook — 6 публікацій щодня\n"
            "• YouTube Shorts — 6 публікацій щодня (відео)\n"
            "• Разом: 168 публікацій за 7 днів\n\n"
            "У пакетах Start та Business вже входять банери, Reels, Shorts, відео з Тімом та супровід зі створення контенту.\n\n"
            "Для запуску напишіть HR менеджеру: @HireUkraine"
        )
        return

    await query.message.reply_text("Оберіть потрібний розділ нижче 👇", reply_markup=client_main_keyboard())


def tim_service_keyboard(intent: str | None = None):
    """Кнопки, которые Тім показывает после GPT-ответа, когда клиент готов оформить заявку."""
    if intent == "vacancy":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("/Free — безкоштовна вакансія", callback_data="vacancy_free")],
            [InlineKeyboardButton("/UsersStart — пакет Start", callback_data="vacancy_start")],
            [InlineKeyboardButton("/UsersBusiness — пакет Business", callback_data="vacancy_business")],
        ])

    if intent == "resume":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("/resume — безкоштовне резюме", callback_data="client_resume")],
        ])

    if intent == "promo":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("/Promo — банер", callback_data="content_banner")],
            [InlineKeyboardButton("/Reels — Reels / Shorts", callback_data="content_reels")],
        ])

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("/Free — безкоштовна вакансія", callback_data="vacancy_free")],
        [InlineKeyboardButton("/resume — безкоштовне резюме", callback_data="client_resume")],
        [InlineKeyboardButton("/UsersStart — пакет Start", callback_data="vacancy_start")],
        [InlineKeyboardButton("/UsersBusiness — пакет Business", callback_data="vacancy_business")],
        [InlineKeyboardButton("/Promo — банер", callback_data="content_banner")],
        [InlineKeyboardButton("/Reels — Reels / Shorts", callback_data="content_reels")],
    ])


def detect_tim_service_intent(text: str):
    """Простое и стабильное определение, какие кнопки показать после ответа Тіма."""
    t = (text or "").lower()

    promo_words = [
        "банер", "баннер", "banner", "reels", "рилс", "shorts", "шортс",
        "реклама", "рекламу", "реклам", "акция", "акція", "акции", "акції",
        "кампания", "кампанія", "продвиж", "просуван", "контент"
    ]
    resume_words = [
        "резюме", "cv", "сі ві", "сиви", "кандидат", "шукаю роботу",
        "ищу работу", "знайти роботу", "найти работу"
    ]
    vacancy_words = [
        "вакансия", "вакансія", "вакансии", "вакансії", "работник",
        "працівник", "сотрудник", "співробітник", "персонал", "найти людей",
        "знайти людей", "ищу людей", "шукаю людей", "разместить вакансию",
        "розмістити вакансію", "пакет старт", "пакет start", "start",
        "business", "бизнес", "бізнес", "usersstart", "usersbusiness"
    ]

    if any(w in t for w in promo_words):
        return "promo"
    if any(w in t for w in resume_words):
        return "resume"
    if any(w in t for w in vacancy_words):
        return "vacancy"
    return None


async def start_free_vacancy_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("tim_content_order", None)
    context.user_data["client_form"] = {
        "type": "vacancy",
        "tariff": "Безкоштовна текстова вакансія",
        "step": "company",
        "data": {},
    }
    await update.message.reply_text("🆓 Безкоштовна вакансія\n\n🏢 Вкажіть назву компанії:")


async def start_resume_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("tim_content_order", None)
    context.user_data["client_form"] = {
        "type": "resume",
        "tariff": "Резюме",
        "step": "resume_name",
        "data": {},
    }
    await update.message.reply_text("👤 Безкоштовне резюме\n\nВкажіть імʼя:")


async def start_users_start_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("tim_content_order", None)
    context.user_data["client_form"] = {
        "type": "vacancy_promo",
        "tariff": "Start",
        "step": "company",
        "data": {},
    }
    await update.message.reply_text(
        "🚀 Пакет Start\n\n"
        "Зараз заповнимо заявку на пакет Start.\n\n"
        "🏢 Вкажіть назву компанії:"
    )


async def start_users_business_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("tim_content_order", None)
    context.user_data["client_form"] = {
        "type": "vacancy_promo",
        "tariff": "Business",
        "step": "company",
        "data": {},
    }
    await update.message.reply_text(
        "💼 Пакет Business\n\n"
        "Зараз заповнимо заявку на пакет Business.\n\n"
        "🏢 Вкажіть назву компанії:"
    )


async def start_promo_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_paid_content_chat(update, context, order_type="banner")


async def start_reels_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_paid_content_chat(update, context, order_type="reels_series")


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


def slot_day_key(dt: datetime) -> str:
    return dt.astimezone(KYIV_TZ).strftime("%Y-%m-%d")


def selected_platforms(session: dict) -> list[str]:
    platforms = []

    if session.get("telegram", {}).get("banner") or session.get("telegram", {}).get("reels") or session.get("telegram", {}).get("text"):
        platforms.append("telegram")
    if session.get("facebook", {}).get("banner") or session.get("facebook", {}).get("reels") or session.get("facebook", {}).get("text"):
        platforms.append("facebook")
    if session.get("instagram", {}).get("banner") or session.get("instagram", {}).get("reels"):
        platforms.append("instagram")
    if session.get("youtube", {}).get("reels"):
        platforms.append("youtube")

    return platforms


def entry_platforms(entry: dict) -> list[str]:
    return entry.get("platforms") or selected_platforms(entry.get("session") or {})



# === GOOGLE DRIVE STORAGE ===
# Google Drive is used as long-term media memory for Tim/HireUA.
# Sheets = clients/queue database. Drive = files: banners, reels, logos, archive.
_drive_service_cache = None
_drive_folder_cache = {}


def sanitize_drive_name(name: str, fallback: str = "Manual") -> str:
    name = str(name or "").strip()
    if not name:
        name = fallback
    name = re.sub(r"[\\/:*?\"<>|]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:90] or fallback


def drive_q(value: str) -> str:
    return str(value or "").replace("'", "\\'")


def get_drive_service():
    global _drive_service_cache
    if _drive_service_cache is not None:
        return _drive_service_cache

    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=GOOGLE_DRIVE_SCOPES,
    )
    _drive_service_cache = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _drive_service_cache


def find_drive_folder_by_name(name: str, parent_id: str | None = None):
    service = get_drive_service()
    q = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{drive_q(name)}' and trashed = false"
    )
    if parent_id:
        q += f" and '{parent_id}' in parents"

    res = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id,name)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files") or []
    return files[0] if files else None


def get_drive_root_folder_id():
    if GOOGLE_DRIVE_ROOT_FOLDER_ID:
        return GOOGLE_DRIVE_ROOT_FOLDER_ID

    cache_key = "root"
    if cache_key in _drive_folder_cache:
        return _drive_folder_cache[cache_key]

    folder = find_drive_folder_by_name(GOOGLE_DRIVE_ROOT_FOLDER_NAME)
    if not folder:
        raise RuntimeError(
            f"Google Drive folder '{GOOGLE_DRIVE_ROOT_FOLDER_NAME}' not found. "
            "Share the folder with the service account or set GOOGLE_DRIVE_ROOT_FOLDER_ID."
        )

    _drive_folder_cache[cache_key] = folder["id"]
    return folder["id"]


def find_or_create_drive_folder(name: str, parent_id: str):
    name = sanitize_drive_name(name)
    cache_key = f"{parent_id}:{name}"
    if cache_key in _drive_folder_cache:
        return _drive_folder_cache[cache_key]

    existing = find_drive_folder_by_name(name, parent_id)
    if existing:
        _drive_folder_cache[cache_key] = existing["id"]
        return existing["id"]

    service = get_drive_service()
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(
        body=metadata,
        fields="id,name",
        supportsAllDrives=True,
    ).execute()
    _drive_folder_cache[cache_key] = created["id"]
    return created["id"]


def get_top_drive_folder_id(name: str):
    root_id = get_drive_root_folder_id()
    return find_or_create_drive_folder(name, root_id)


def get_client_drive_folder_id(client_name: str):
    clients_root = get_top_drive_folder_id("Clients")
    return find_or_create_drive_folder(sanitize_drive_name(client_name), clients_root)


def get_client_drive_subfolder_id(client_name: str, subfolder_name: str):
    client_folder = get_client_drive_folder_id(client_name)
    return find_or_create_drive_folder(subfolder_name, client_folder)


def find_drive_file_by_name(name: str, folder_id: str):
    service = get_drive_service()
    q = f"name = '{drive_q(name)}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id,name,webViewLink,webContentLink,md5Checksum,mimeType)",
        pageSize=5,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files") or []
    return files[0] if files else None


def upload_file_to_drive(local_path: str, folder_id: str, filename: str, mime_type: str = "application/octet-stream"):
    """Upload once: if a file with same generated name exists in the folder, reuse it."""
    service = get_drive_service()
    filename = sanitize_drive_name(filename, fallback=f"file_{uuid4().hex}")

    existing = find_drive_file_by_name(filename, folder_id)
    if existing:
        return existing

    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=False)
    metadata = {"name": filename, "parents": [folder_id]}
    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink,webContentLink,md5Checksum,mimeType",
        supportsAllDrives=True,
    ).execute()
    return created


def download_drive_file_to_temp(file_id: str, suffix: str = ""):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()
    with open(temp_file.name, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return temp_file.name


def export_google_doc_to_temp(file_id: str, mime_type: str = "text/plain", suffix: str = ".txt"):
    service = get_drive_service()
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()
    with open(temp_file.name, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return temp_file.name


def get_nested_drive_folder_id(path_parts: list[str], create_missing: bool = False):
    """Finds a folder by path inside HireUa. Optionally creates missing folders."""
    parent_id = get_drive_root_folder_id()
    for part in path_parts:
        part = sanitize_drive_name(part)
        found = find_drive_folder_by_name(part, parent_id)
        if not found:
            if not create_missing:
                return None
            parent_id = find_or_create_drive_folder(part, parent_id)
        else:
            parent_id = found["id"]
    return parent_id


def list_drive_files(folder_id: str, mime_prefix: str | None = None, name_contains: str | None = None, limit: int = 30):
    service = get_drive_service()
    q = f"'{folder_id}' in parents and trashed = false"
    if mime_prefix:
        q += f" and mimeType contains '{drive_q(mime_prefix)}'"
    if name_contains:
        q += f" and name contains '{drive_q(name_contains)}'"
    res = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id,name,mimeType,webViewLink,webContentLink)",
        pageSize=limit,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return res.get("files") or []


_tim_profile_cache = None
_tim_assets_cache = {}


def load_tim_profile_text() -> str:
    """Reads TIM_PROFILE from Drive when possible. Falls back to a built-in profile."""
    global _tim_profile_cache
    if _tim_profile_cache is not None:
        return _tim_profile_cache

    fallback = (
        "Тім — офіційний персонаж HireUA. Усі фото в папках Avatar_Main та Full Body належать персонажу Тім. "
        "Тім використовується за замовчуванням у банерах, рекламі, вакансіях, Reels та відео HireUA. "
        "Якщо клієнт не просить прибрати Тіма — використовувати Тіма. "
        "Зовнішність: чорне волосся, сині очі, значок HireUA, дружній професійний стиль. "
        "Одяг за замовчуванням: біла вишиванка, синя вишиванка, біла сорочка, синій піджак, біла футболка. "
        "Тім може бути адаптований під бренд клієнта, але повинен залишатися впізнаваним."
    )

    try:
        tim_folder_id = get_nested_drive_folder_id(["Tim"], create_missing=False)
        if not tim_folder_id:
            _tim_profile_cache = fallback
            return _tim_profile_cache

        files = list_drive_files(tim_folder_id, limit=50)
        profile = None
        for f in files:
            name = (f.get("name") or "").lower()
            if "tim_profile" in name or "тім" in name or "tim profile" in name:
                profile = f
                break

        if not profile:
            _tim_profile_cache = fallback
            return _tim_profile_cache

        mime = profile.get("mimeType") or ""
        if mime == "application/vnd.google-apps.document":
            path = export_google_doc_to_temp(profile["id"], "text/plain", ".txt")
        else:
            path = download_drive_file_to_temp(profile["id"], ".txt")

        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

        _tim_profile_cache = text or fallback
        return _tim_profile_cache
    except Exception as e:
        print("TIM PROFILE LOAD ERROR:", e, flush=True)
        _tim_profile_cache = fallback
        return _tim_profile_cache


def _tim_decision_text(text: str = "", data: dict | None = None) -> str:
    """Collects only textual instructions that can change Tim logic.

    Important: uploaded product/logo/interior photos do NOT disable Tim by themselves.
    Tim is disabled only when the user explicitly asks to remove Tim or to use
    their own person/avatar/photo instead of Tim.
    """
    data = data or {}
    return " ".join([
        str(text or ""),
        str(data.get("tim", "")),
        str(data.get("wishes", "")),
        str(data.get("style", "")),
        str(data.get("materials", "")),
        str(data.get("main_info", "")),
    ]).lower()


def client_explicitly_wants_tim(text: str, data: dict | None = None) -> bool:
    combined = _tim_decision_text(text, data)
    positive_patterns = [
        "з тімом", "с тимом", "додай тіма", "добавь тима", "добавити тіма", "добавить тима",
        "тім поруч", "тим рядом", "разом з тімом", "вместе с тимом", "і тіма", "и тима",
        "залишити тіма", "оставить тима", "не убирай тима", "не прибирай тіма",
    ]
    return any(p in combined for p in positive_patterns)


def client_asked_without_tim(text: str, data: dict | None = None) -> bool:
    combined = _tim_decision_text(text, data)
    negative_patterns = [
        "без тіма", "без тима", "без tim",
        "прибрати тіма", "прибрати тима", "убрать тима", "убери тима",
        "не добавляй тима", "не додавай тіма", "не використовуй тіма", "не используй тима",
        "без персонажа hireua", "без персонажа hire ua",
    ]
    return any(p in combined for p in negative_patterns)


def client_requested_own_avatar_or_person_instead_of_tim(text: str, data: dict | None = None) -> bool:
    """Detects explicit user intent to use THEIR person/avatar/photo instead of Tim.

    This must not trigger for product, store, logo, interior or brand photos.
    It triggers only from the user's words, not from the existence of an uploaded image.
    """
    combined = _tim_decision_text(text, data)
    replacement_patterns = [
        "мой аватар", "моего аватара", "моим аватаром", "свой аватар", "своего аватара",
        "мій аватар", "мого аватара", "свій аватар", "свого аватара",
        "этого аватара", "цей аватар", "цього аватара", "этот аватар",
        "моё фото", "мое фото", "мою фотографию", "мою фотку", "моє фото", "мою фотографію",
        "фото сотрудника", "фото співробітника", "фото директора", "фото менеджера",
        "этого человека", "цього чоловіка", "цю людину", "этого мужчину", "эту девушку",
        "используй этого человека", "використовуй цю людину", "поставь этого человека", "постав цього",
        "замість тіма", "заместь тима", "вместо тима", "замість тима",
        "не тім", "не тим",
        "только мой аватар", "тільки мій аватар", "только мое фото", "тільки моє фото",
    ]
    return any(p in combined for p in replacement_patterns)


def should_use_tim(text: str = "", data: dict | None = None) -> bool:
    """Single source of truth for Tim.

    Tim is the default HireUA character. Use Tim unless:
    - the user explicitly asks to remove Tim;
    - the user explicitly asks to use their own person/avatar/photo instead of Tim.

    Product, store, logo, interior and general client materials do NOT disable Tim.
    Explicit request to add/keep Tim overrides ambiguous avatar/photo wording.
    """
    if client_explicitly_wants_tim(text, data):
        return True
    if client_asked_without_tim(text, data):
        return False
    if client_requested_own_avatar_or_person_instead_of_tim(text, data):
        return False
    return True


def get_tim_reference_image_path(prefer_full_body: bool = True) -> str | None:
    """Downloads ONE best Tim identity reference from Drive.

    Identity must come from Tim/Avatar_Main first. Full Body/series images are
    fallback only, because collages often make the model redraw a different man.
    """
    cache_key = "tim_identity_reference"
    cached = _tim_assets_cache.get(cache_key)
    if cached and os.path.exists(cached):
        return cached

    candidate_paths = [["Tim", "Avatar_Main"], ["Tim", "Full Body"], ["Tim", "Full_Body"]]

    try:
        ranked = []
        for parts in candidate_paths:
            folder_id = get_nested_drive_folder_id(parts, create_missing=False)
            if not folder_id:
                continue
            folder_name = "/".join(parts).lower()
            files = list_drive_files(folder_id, mime_prefix="image/", limit=80)
            for f in files:
                name = (f.get("name") or "").lower()
                if any(x in name for x in ("watermark", "logo", "json", "вод")):
                    continue
                score = 0
                if "avatar_main" in folder_name:
                    score += 1000
                if any(x in name for x in ("avatar", "profile", "main", "face", "портрет", "tim", "тім", "тим")):
                    score += 100
                if any(x in name for x in ("full", "body", "collage", "grid", "series")):
                    score -= 50
                if "png" in (f.get("mimeType") or ""):
                    score += 5
                ranked.append((score, f))

        if not ranked:
            return None

        ranked.sort(key=lambda x: x[0], reverse=True)
        chosen = ranked[0][1]
        ext = ".png" if "png" in (chosen.get("mimeType") or "") else ".jpg"
        path = download_drive_file_to_temp(chosen["id"], ext)
        _tim_assets_cache[cache_key] = path
        print(f"TIM REFERENCE SELECTED: {chosen.get('name')} score={ranked[0][0]}", flush=True)
        return path
    except Exception as e:
        print("TIM REFERENCE LOAD ERROR:", e, flush=True)
        return None


def get_brand_watermark_path() -> str | None:
    """Downloads watermark/logo image from Tim/Brand or Brand.

    Prefer explicit watermark files. If file names are random, still pick the best
    HireUA/Ukraine/logo image from Brand instead of silently skipping watermark.
    """
    cached = _tim_assets_cache.get("watermark")
    if cached and os.path.exists(cached):
        return cached

    try:
        folders = [["Tim", "Brand"], ["Brand"], ["Logos"]]
        candidates = []
        for parts in folders:
            folder_id = get_nested_drive_folder_id(parts, create_missing=False)
            if not folder_id:
                continue
            files = list_drive_files(folder_id, mime_prefix="image/", limit=80)
            for f in files:
                name = (f.get("name") or "").lower()
                if "tim_profile" in name or "json" in name:
                    continue
                score = 0
                if any(x in name for x in ("watermark", "вод", "водя")):
                    score += 1000
                if any(x in name for x in ("hireua", "hire ua", "hire")):
                    score += 300
                if any(x in name for x in ("ukraine", "укра")):
                    score += 80
                if any(x in name for x in ("logo", "лог", "brand")):
                    score += 70
                if any(x in name for x in ("transparent", "проз", "png")):
                    score += 30
                # File is in a Brand folder, so even random names are acceptable.
                score += 10
                candidates.append((score, f))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        chosen = candidates[0][1]
        ext = ".png" if "png" in (chosen.get("mimeType") or "") else ".jpg"
        path = download_drive_file_to_temp(chosen["id"], ext)
        _tim_assets_cache["watermark"] = path
        print(f"WATERMARK SELECTED: {chosen.get('name')} score={candidates[0][0]}", flush=True)
        return path
    except Exception as e:
        print("BRAND WATERMARK LOAD ERROR:", e, flush=True)
        return None


async def prepare_session_drive_files(context: ContextTypes.DEFAULT_TYPE, session: dict):
    """Save uploaded banner/reels to Google Drive once and keep Drive IDs in session."""
    client_name = queue_client_from_session(session)

    # Banner
    if session.get("banner_file_id") and not session.get("banner_drive_id"):
        temp_path = None
        try:
            temp_path = await download_telegram_photo_to_temp(context, session["banner_file_id"])
            unique = session.get("banner_file_unique_id") or session.get("banner_file_id") or uuid4().hex
            folder_id = get_client_drive_subfolder_id(client_name, "Banners")
            file_name = f"banner_{sanitize_drive_name(client_name)}_{unique}.jpg"
            uploaded = await asyncio.to_thread(upload_file_to_drive, temp_path, folder_id, file_name, "image/jpeg")
            session["banner_drive_id"] = uploaded.get("id", "")
            session["banner_drive_link"] = uploaded.get("webViewLink", "")
            session["banner_drive_name"] = uploaded.get("name", file_name)
        except Exception as e:
            print("DRIVE BANNER UPLOAD ERROR:", e, flush=True)
            session["banner_drive_error"] = str(e)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    # Reels / video
    if session.get("reels_file_id") and not session.get("reels_drive_id"):
        temp_path = None
        try:
            temp_path = await download_telegram_video_to_temp(context, session["reels_file_id"])
            unique = session.get("reels_file_unique_id") or session.get("reels_file_id") or uuid4().hex
            folder_id = get_client_drive_subfolder_id(client_name, "Reels")
            file_name = f"reels_{sanitize_drive_name(client_name)}_{unique}.mp4"
            uploaded = await asyncio.to_thread(upload_file_to_drive, temp_path, folder_id, file_name, "video/mp4")
            session["reels_drive_id"] = uploaded.get("id", "")
            session["reels_drive_link"] = uploaded.get("webViewLink", "")
            session["reels_drive_name"] = uploaded.get("name", file_name)
        except Exception as e:
            print("DRIVE REELS UPLOAD ERROR:", e, flush=True)
            session["reels_drive_error"] = str(e)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    return session

QUEUE_SHEET_NAME = "Queue"
QUEUE_HEADERS = [
    "ID", "Created", "Client", "Package", "Content", "Platforms", "Channels",
    "PublishTime", "Status", "Notes", "TG", "FB", "IG", "YT",
    "BannerDriveID", "BannerDriveLink", "ReelsDriveID", "ReelsDriveLink",
]
QUEUE_ACTIVE_STATUSES = {"Scheduled", "Running", "Paused", "Error"}
QUEUE_SKIP_STATUSES = {"Cancelled", "Canceled", "Paused", "Published", "Done"}


def queue_sheet():
    """Повертає вкладку Queue. Якщо вкладки немає — створює її з правильними заголовками."""
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
    book = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        sheet = book.worksheet(QUEUE_SHEET_NAME)
    except Exception:
        sheet = book.add_worksheet(title=QUEUE_SHEET_NAME, rows=1000, cols=len(QUEUE_HEADERS) + 2)

    try:
        first_row = sheet.row_values(1)
        if first_row[:len(QUEUE_HEADERS)] != QUEUE_HEADERS:
            sheet.update(f"A1:{chr(64 + len(QUEUE_HEADERS))}1", [QUEUE_HEADERS])
    except Exception as e:
        print("QUEUE HEADER ERROR:", e, flush=True)

    return sheet


def queue_status_from_entry_status(status: str) -> str:
    status = (status or "pending").lower()
    if status in ("pending",):
        return "Scheduled"
    if status in ("running",):
        return "Running"
    if status in ("done", "published"):
        return "Published"
    if status in ("done_with_errors", "failed", "error"):
        return "Error"
    if status in ("cancelled", "canceled"):
        return "Cancelled"
    if status == "paused":
        return "Paused"
    return status[:1].upper() + status[1:]


def queue_platform_flag(value) -> bool:
    """Порожня клітинка = ON, щоб старі/ручні рядки не ламалися."""
    value = str(value or "").strip().upper()
    if not value:
        return True
    return value not in ("OFF", "NO", "FALSE", "0", "НІ", "НЕТ")


def queue_entry_platforms(row: dict) -> list[str]:
    platforms = []
    if queue_platform_flag(row.get("TG")):
        platforms.append("telegram")
    if queue_platform_flag(row.get("FB")):
        platforms.append("facebook")
    if queue_platform_flag(row.get("IG")):
        platforms.append("instagram")
    if queue_platform_flag(row.get("YT")):
        platforms.append("youtube")
    return platforms


def format_queue_time(dt: datetime) -> str:
    return dt.astimezone(KYIV_TZ).strftime("%d.%m.%Y %H:%M")


def parse_queue_time(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = KYIV_TZ.localize(dt)
            return dt.astimezone(KYIV_TZ)
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = KYIV_TZ.localize(dt)
        return dt.astimezone(KYIV_TZ)
    except Exception:
        return None


def queue_content_from_session(session: dict) -> str:
    parts = []
    if session.get("telegram", {}).get("banner") or session.get("facebook", {}).get("banner") or session.get("instagram", {}).get("banner"):
        parts.append("Banner")
    if session.get("telegram", {}).get("reels") or session.get("facebook", {}).get("reels") or session.get("instagram", {}).get("reels") or session.get("youtube", {}).get("reels"):
        parts.append("Reels")
    if session.get("telegram", {}).get("text") or session.get("facebook", {}).get("text"):
        parts.append("Text")
    return "+".join(parts) or "Publication"


def queue_client_from_session(session: dict) -> str:
    for key in ("client", "client_name", "company", "brand"):
        if session.get(key):
            return str(session.get(key)).strip()[:80]

    text = str(session.get("text") or "").strip()
    if text:
        first_line = text.splitlines()[0].strip()
        if first_line:
            return first_line[:80]

    return "Manual"


def queue_channels_from_session(session: dict) -> str:
    channels = session.get("channels") or []
    names = []
    for key in channels:
        if key in CHANNELS:
            names.append(CHANNELS[key][1].replace("@", ""))
        else:
            names.append(str(key))
    return ",".join(names)


def queue_platforms_string(platforms: list[str]) -> str:
    mapping = {"telegram": "TG", "facebook": "FB", "instagram": "IG", "youtube": "YT"}
    return ",".join(mapping.get(p, p) for p in platforms)


def append_queue_entry(entry: dict):
    """Записує одну заплановану публікацію у вкладку Queue."""
    try:
        sheet = queue_sheet()
        session = entry.get("session") or {}
        platforms = entry_platforms(entry)
        run_at = None
        try:
            run_at = datetime.fromisoformat(entry.get("run_at"))
        except Exception:
            pass
        if run_at is None:
            run_at = datetime.now(KYIV_TZ)
        if run_at.tzinfo is None:
            run_at = KYIV_TZ.localize(run_at)
        run_at = run_at.astimezone(KYIV_TZ)

        sheet.append_row([
            entry.get("id", ""),
            datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M"),
            queue_client_from_session(session),
            entry.get("package", ""),
            queue_content_from_session(session),
            queue_platforms_string(platforms),
            queue_channels_from_session(session),
            format_queue_time(run_at),
            "Scheduled",
            "",
            "ON" if "telegram" in platforms else "OFF",
            "ON" if "facebook" in platforms else "OFF",
            "ON" if "instagram" in platforms else "OFF",
            "ON" if "youtube" in platforms else "OFF",
            session.get("banner_drive_id", ""),
            session.get("banner_drive_link", ""),
            session.get("reels_drive_id", ""),
            session.get("reels_drive_link", ""),
        ], value_input_option="USER_ENTERED")
    except Exception as e:
        print("QUEUE APPEND ERROR:", e, flush=True)


def get_queue_records():
    try:
        sheet = queue_sheet()
        records = sheet.get_all_records()
        rows = []
        for idx, row in enumerate(records, start=2):
            row["_row"] = idx
            rows.append(row)
        return rows
    except Exception as e:
        print("QUEUE READ ERROR:", e, flush=True)
        return []


def get_queue_record_by_id(entry_id: str):
    entry_id = str(entry_id or "").strip()
    if not entry_id:
        return None
    for row in get_queue_records():
        if str(row.get("ID") or "").strip() == entry_id:
            return row
    return None


def update_queue_entry(entry_id: str, status: str | None = None, notes: str | None = None):
    try:
        row = get_queue_record_by_id(entry_id)
        if not row:
            return False
        sheet = queue_sheet()
        row_num = row.get("_row")
        if status is not None:
            sheet.update_cell(row_num, 9, status)  # I = Status
        if notes is not None:
            sheet.update_cell(row_num, 10, notes[:45000])  # J = Notes
        return True
    except Exception as e:
        print("QUEUE UPDATE ERROR:", e, flush=True)
        return False


def apply_queue_platform_switches_to_session(session: dict, row: dict) -> dict:
    """Вимикає платформи у session, якщо в Queue стоїть OFF."""
    session = deepcopy(session)
    mapping = [
        ("TG", "telegram"),
        ("FB", "facebook"),
        ("IG", "instagram"),
        ("YT", "youtube"),
    ]
    for col, platform in mapping:
        if not queue_platform_flag(row.get(col)) and platform in session:
            for key in list(session[platform].keys()):
                if isinstance(session[platform].get(key), bool):
                    session[platform][key] = False
    return session


def queue_capacity_for_day(day_dt: datetime | None = None):
    day_dt = (day_dt or datetime.now(KYIV_TZ)).astimezone(KYIV_TZ)
    day_key = day_dt.strftime("%d.%m.%Y")

    total_minutes = sum(
        int((day_part_bounds(day_dt, part)[1] - day_part_bounds(day_dt, part)[0]).total_seconds() // 60)
        for part in DAY_PARTS
    )
    result = {}
    for platform, gap in PLATFORM_MIN_GAP_MINUTES.items():
        total = max(1, total_minutes // gap)
        if platform == "youtube":
            total = min(total, YOUTUBE_DAILY_LIMIT)
        result[platform] = {"total": total, "used": 0, "free": total}

    rows = get_queue_records()
    for row in rows:
        status = str(row.get("Status") or "").strip()
        if status != "Scheduled":
            continue
        publish_time = str(row.get("PublishTime") or "").strip()
        if not publish_time.startswith(day_key):
            continue
        for platform in queue_entry_platforms(row):
            if platform in result:
                result[platform]["used"] += 1

    for platform in result:
        result[platform]["free"] = max(0, result[platform]["total"] - result[platform]["used"])
    return result


def is_active_schedule_entry(entry: dict) -> bool:
    return entry.get("status") in (None, "pending", "running") and bool(entry.get("slot"))


def day_part_bounds(day_dt: datetime, part: str):
    day_dt = day_dt.astimezone(KYIV_TZ)
    start_hour, start_minute, end_hour, end_minute = DAY_PARTS[part]
    start = day_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = day_dt.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start, end


def slots_for_day_part(day_dt: datetime, part: str):
    start, end = day_part_bounds(day_dt, part)
    slots = []
    current = start

    while current < end:
        # Живий час публікації: не 08:00 / 08:05 / 08:10,
        # а 08:02 / 08:09 / 08:13 тощо.
        # Так бот не ставить публікації на круглі хвилини.
        jitter_minutes = random.randint(1, max(1, SLOT_STEP_MINUTES - 1))
        candidate = current + timedelta(minutes=jitter_minutes)

        if candidate < end:
            slots.append(candidate)

        current += timedelta(minutes=SLOT_STEP_MINUTES)

    # Рандом всередині блоку: різні клієнти не отримують однаковий порядок слотів.
    random.shuffle(slots)
    return slots


def platform_gap_ok(candidate: datetime, candidate_platforms: list[str], entries: list[dict]) -> bool:
    candidate = candidate.astimezone(KYIV_TZ)

    for entry in entries:
        if not is_active_schedule_entry(entry):
            continue

        try:
            other = datetime.fromisoformat(entry.get("run_at") or entry.get("slot"))
        except Exception:
            continue

        if other.tzinfo is None:
            other = KYIV_TZ.localize(other)
        else:
            other = other.astimezone(KYIV_TZ)

        common_platforms = set(candidate_platforms) & set(entry_platforms(entry))
        if not common_platforms:
            continue

        for platform in common_platforms:
            min_gap = PLATFORM_MIN_GAP_MINUTES.get(platform, 5)
            if abs((candidate - other).total_seconds()) < min_gap * 60:
                return False

    return True


def youtube_day_count(entries: list[dict], day_dt: datetime) -> int:
    day_key = slot_day_key(day_dt)
    count = 0

    for entry in entries:
        if not is_active_schedule_entry(entry):
            continue
        if "youtube" not in entry_platforms(entry):
            continue
        if str(entry.get("slot", "")).startswith(day_key):
            count += 1

    return count


def find_free_slots_for_session(session: dict, start_from: datetime | None = None):
    entries = load_schedule_entries()
    platforms = selected_platforms(session)
    package_key = session.get("package", "single")
    days = int(session.get("days", 1))
    distribution = PACKAGE_DAY_DISTRIBUTION.get(package_key, PACKAGE_DAY_DISTRIBUTION["start"])

    now = start_from or datetime.now(KYIV_TZ)
    earliest = now + timedelta(minutes=1)
    planned_slots = []

    for day_index in range(days):
        day_dt = now + timedelta(days=day_index)

        for part in distribution:
            if part == "now":
                # Для разової публікації ставимо найближчий безпечний слот у межах дня.
                part_candidates = []
                for p in ("morning", "day", "evening"):
                    part_candidates.extend(slots_for_day_part(day_dt, p))
                part_candidates = sorted(part_candidates)
            else:
                part_candidates = slots_for_day_part(day_dt, part)

            chosen = None

            for candidate in part_candidates:
                candidate = candidate.astimezone(KYIV_TZ)

                if candidate <= earliest:
                    continue

                if "youtube" in platforms and youtube_day_count(entries + planned_slots, candidate) >= YOUTUBE_DAILY_LIMIT:
                    continue

                if not platform_gap_ok(candidate, platforms, entries + planned_slots):
                    continue

                chosen = candidate
                break

            # Якщо конкретний блок дня забитий, шукаємо у наступні дні той самий блок.
            search_offset = 1
            while chosen is None and search_offset <= 60:
                future_day = day_dt + timedelta(days=search_offset)
                future_candidates = slots_for_day_part(future_day, part if part != "now" else "morning")

                for candidate in future_candidates:
                    if "youtube" in platforms and youtube_day_count(entries + planned_slots, candidate) >= YOUTUBE_DAILY_LIMIT:
                        continue
                    if not platform_gap_ok(candidate, platforms, entries + planned_slots):
                        continue
                    chosen = candidate
                    break

                search_offset += 1

            if chosen is None:
                return []

            planned_entry = {
                "slot": slot_key(chosen),
                "run_at": chosen.isoformat(),
                "status": "pending",
                "platforms": platforms,
                "session": session,
            }
            planned_slots.append(planned_entry)

    return [datetime.fromisoformat(entry["run_at"]) for entry in planned_slots]


def schedule_capacity_for_day(day_dt: datetime | None = None):
    day_dt = (day_dt or datetime.now(KYIV_TZ)).astimezone(KYIV_TZ)
    entries = [entry for entry in load_schedule_entries() if is_active_schedule_entry(entry)]
    day_key = slot_day_key(day_dt)

    result = {}
    total_minutes = sum(
        int((day_part_bounds(day_dt, part)[1] - day_part_bounds(day_dt, part)[0]).total_seconds() // 60)
        for part in DAY_PARTS
    )

    for platform, gap in PLATFORM_MIN_GAP_MINUTES.items():
        total = max(1, total_minutes // gap)
        if platform == "youtube":
            total = min(total, YOUTUBE_DAILY_LIMIT)

        used = 0
        for entry in entries:
            if not str(entry.get("slot", "")).startswith(day_key):
                continue
            if platform in entry_platforms(entry):
                used += 1

        result[platform] = {
            "total": total,
            "used": used,
            "free": max(0, total - used),
        }

    return result

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
            "platforms": selected_platforms(session),
            "created_at": datetime.now(KYIV_TZ).isoformat(),
            "session": deepcopy(session),
        }
        entries.append(entry)
        new_entries.append(entry)
        append_queue_entry(entry)

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

            queue_status = queue_status_from_entry_status(status)
            notes_parts = []
            if success:
                notes_parts.append("Опубліковано: " + "; ".join(success))
            if failed:
                notes_parts.append("Помилки: " + "; ".join(failed))
            update_queue_entry(entry_id, queue_status, " | ".join(notes_parts) if notes_parts else None)
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
    await asyncio.to_thread(save_user_to_sheet, update, "/start") 
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
            await query.edit_message_text("⏳ Зберігаю файли в Google Drive і публікую зараз...")
            await prepare_session_drive_files(context, session)
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


async def download_telegram_photo_to_temp(context: ContextTypes.DEFAULT_TYPE, file_id: str):
    tg_file = await context.bot.get_file(file_id)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = temp_file.name
    temp_file.close()
    await tg_file.download_to_drive(temp_path)
    return temp_path


async def handle_content_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Зберігає фото/банер клієнта як основу для подальших правок у контент-чаті."""
    order = context.user_data.get("tim_content_order")
    if not order:
        return False

    if not update.message.photo:
        return False

    photo_path = await download_telegram_photo_to_temp(context, update.message.photo[-1].file_id)
    remember_image(order, photo_path, "client_uploaded_image")
    order["stage"] = "image_uploaded_waiting_edit"

    caption = (update.message.caption or "").strip()
    if caption:
        await update.message.reply_text("Фото отримано ✅ Вношу правки за вашим описом.")
        base_image = order.get("last_uploaded_image")
        path = await edit_tim_image(update, context, base_image, caption, data=order.get("data", {}), story=order.get("story", ""))
        if path:
            order["last_files"] = [path]
            remember_image(order, path, "generated_banner")
            order["stage"] = "generated"
            await send_tim_generated_files(
                update,
                [path],
                "Готово ✅ Я відредагував зображення.\n\nЯкщо потрібні ще правки — просто напишіть, що змінити."
            )
        return True

    await update.message.reply_text(
        "Фото / банер отримано ✅\n\n"
        "Напишіть, що саме потрібно змінити:\n"
        "• замінити фон\n"
        "• додати текст\n"
        "• прибрати елемент\n"
        "• зробити преміум стиль\n"
        "• додати Тіма або логотип"
    )
    return True


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Якщо клієнт у режимі Promo/Reels і надіслав фото — це основа для редагування.
    if context.user_data.get("tim_content_order") and update.message and update.message.photo:
        if await handle_content_photo(update, context):
            return

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

        banner_photo = update.message.photo[-1]
        session["banner_file_id"] = banner_photo.file_id
        session["banner_file_unique_id"] = getattr(banner_photo, "file_unique_id", "")

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

        video = update.message.video
        session["reels_file_id"] = video.file_id
        session["reels_file_unique_id"] = getattr(video, "file_unique_id", "")

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
            append_resume_to_sheet(data)
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

            order = {
                "tariff": form.get("tariff", ""),
                "order_type": form.get("order_type", "banner"),
                "data": data,
                "status": "НА ПОГОДЖЕННІ",
                "last_files": [],
                "client_edits": [],
                "publish_text": "",
            }

            append_content_brief_to_sheet(
                data=data,
                tariff=order["tariff"],
                user_id=update.effective_user.id,
                order_type=order["order_type"],
            )

            context.user_data["tim_content_order"] = order
            context.user_data.pop("client_form", None)

            await generate_first_content_version(update, context, order)
            return True

    # ---------- START / BUSINESS: ЗАЯВКА НА ПАКЕТ ----------
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
                "📥 Нова заявка Start / Business\n\n"
                f"Тариф: {form.get('tariff')}\n\n"
                f"👤 Клієнт: @{update.effective_user.username or ''}\n"
                f"Telegram ID: {update.effective_user.id}\n\n"
                "👨‍💼 ВАКАНСІЯ / ПАКЕТ\n"
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
            append_vacancy_to_sheet(data, form.get("tariff", ""))
            append_client_to_sheet(data, form.get("tariff", ""), update.effective_user)

            await update.message.reply_text(
                "✅ Заявка прийнята.\n\n"
                "Для активації пакета зв'яжіться з адміністратором:\n\n"
                "@HireUkraine"
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
        append_vacancy_to_sheet(data, form.get("tariff", ""))
        await update.message.reply_text(
            "✅ Заявка прийнята.\n"
            "Ми перевіримо інформацію та зв'яжемось з вами."
        )

        context.user_data.pop("client_form", None)
        return True

    return False


WATERMARK_TEXT = "@UkraineHire"


def add_watermark_to_image(image_path: str) -> str:
    """Adds visible HireUA watermark to every generated image.

    First tries PNG/JPG from Drive Tim/Brand. If not found or bad, adds a strong
    text fallback. Never returns an unwatermarked image unless Pillow is missing.
    """
    if Image is None or ImageDraw is None:
        return image_path

    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        watermark_path = get_brand_watermark_path()
        if watermark_path and os.path.exists(watermark_path):
            try:
                wm = Image.open(watermark_path).convert("RGBA")
                target_w = max(190, int(width * 0.22))
                scale = target_w / max(1, wm.size[0])
                target_h = max(1, int(wm.size[1] * scale))
                wm = wm.resize((target_w, target_h), Image.LANCZOS)
                alpha = wm.getchannel("A").point(lambda a: int(a * 0.82))
                wm.putalpha(alpha)
                x = int(width * 0.035)
                y = int(height * 0.025)
                img.alpha_composite(wm, (x, y))
                output_path = os.path.splitext(image_path)[0] + "_watermark.png"
                img.save(output_path)
                return output_path
            except Exception as e:
                print("PNG WATERMARK APPLY ERROR:", e, flush=True)

        # Strong fallback watermark: must be visible if Drive logo was not found.
        draw = ImageDraw.Draw(img)
        font_size = max(34, int(width * 0.045))
        font = None
        for font_path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        text = WATERMARK_TEXT
        x = int(width * 0.035)
        y = int(height * 0.025)
        padding_x = max(18, int(width * 0.018))
        padding_y = max(12, int(width * 0.012))
        bbox = draw.textbbox((x, y), text, font=font)
        rect = (bbox[0] - padding_x, bbox[1] - padding_y, bbox[2] + padding_x, bbox[3] + padding_y)
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(rect, radius=20, fill=(0, 31, 95, 175))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)
        draw.text((x, y), text, fill=(255, 255, 255, 245), font=font)
        output_path = os.path.splitext(image_path)[0] + "_watermark.png"
        img.save(output_path)
        return output_path
    except Exception as e:
        print("WATERMARK ERROR:", e, flush=True)
        return image_path


async def generate_tim_image_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict, client_comment: str = "", slide_number: int = None, story: str = ""):
    """Створює нове зображення з текстового опису. Тім додається за замовчуванням."""
    data = data or {}
    if slide_number:
        task = f"Create slide/banner #{slide_number} of 5 for a Reels/Shorts storyboard. Keep the same visual style and story continuity across all slides."
    else:
        task = "Create one premium vertical advertising banner."

    use_tim = should_use_tim(client_comment, data)
    tim_profile = load_tim_profile_text()
    tim_instruction = ""
    if use_tim:
        tim_instruction = f"""
TIM IS REQUIRED BY DEFAULT:
Tim is the default HireUA character and must be present in the banner unless the client explicitly asked to remove Tim or to use their own person/avatar/photo instead of Tim.
Client product photos, store photos, logos, interiors, brand materials or goods do NOT cancel Tim. In those cases, combine the client material with Tim.
Use the provided Tim reference image as the mandatory identity reference. Tim must have the same face, hair, eyes and recognizable character identity as the reference. Do not invent a new man.
Tim must look like the same HireUA character from the Drive library, not a random man and not a different avatar.
Keep Tim recognizable: black hair, blue eyes, friendly professional Ukrainian HR assistant, HireUA badge or branded element.
Tim may wear clothing that fits the task, but keep the same face and character identity.

TIM_PROFILE FROM DRIVE:
{tim_profile}
"""
    else:
        tim_instruction = """
CLIENT REQUESTED NO TIM OR OWN AVATAR/PERSON INSTEAD OF TIM:
Do not add Tim. If the client provided their own person/avatar/photo and asked to use it, use that client character/person instead. Still keep HireUA premium style and watermark.
"""

    prompt = f"""
{task}

QUALITY REQUIREMENTS:
Ultra high quality. Premium commercial advertising design. Modern marketing agency level.
Professional composition, realistic lighting, sharp details, clean layout, high-end social media ad quality.
Avoid cheap template graphics, random robots, generic AI mascots, distorted faces, messy typography, unreadable letters.

FORMAT:
Vertical 1080x1920 social media banner / Reels cover.
Leave clean empty space for a HireUA watermark in the upper-left corner. A PNG watermark from Google Drive folder Tim/Brand will be added automatically after generation.

BRAND CONTEXT:
HireUA is a modern Ukrainian recruitment and promotion platform. The visual should feel trustworthy, professional, energetic and premium.
Use green/blue/white corporate mood when appropriate, but adapt to the client's task.
Do not make HireUA dominate the client's offer.

CHARACTER RULES:
{tim_instruction}
Do not replace Tim with robots or generic mascots.

TEXT RULES:
Do not create a lot of text inside the image. If text appears, it must be minimal and clean.
Focus mainly on strong visual, composition and emotion. Text overlays can be added later.

CLIENT / TASK DATA:
{content_brief_text(data)}

REELS STORY / CONTEXT:
{story}

CLIENT REQUEST / APPROVED BRIEF / EDITS:
{client_comment}
"""

    def _generate_with_optional_tim_reference():
        # If Tim is required, we must use a Tim reference from Drive.
        # Otherwise the model can invent a random man, which is not allowed.
        if use_tim:
            ref_path = get_tim_reference_image_path(prefer_full_body=False)
            if not ref_path or not os.path.exists(ref_path):
                raise RuntimeError("TIM_REFERENCE_NOT_FOUND: add Tim images to Drive / Tim / Avatar_Main or Full Body")
            try:
                with open(ref_path, "rb") as ref_img:
                    try:
                        return openai_client.images.edit(
                            model=OPENAI_IMAGE_MODEL,
                            image=ref_img,
                            prompt=prompt + "\nUse the provided image as the mandatory identity reference for Tim. Keep the same face, hair, eyes and recognizable character identity. Create a new premium banner composition with this same Tim character, not a random man.",
                            size="1024x1536",
                            quality="high",
                        )
                    except TypeError:
                        ref_img.seek(0)
                        return openai_client.images.edit(
                            model=OPENAI_IMAGE_MODEL,
                            image=[ref_img],
                            prompt=prompt + "\nUse the provided image as the mandatory identity reference for Tim. Keep the same face, hair, eyes and recognizable character identity. Create a new premium banner composition with this same Tim character, not a random man.",
                            size="1024x1536",
                            quality="high",
                        )
            except Exception as e:
                raise RuntimeError(f"TIM_REFERENCE_EDIT_FAILED: {e}")

        return openai_client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size="1024x1536",
            quality="high",
        )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_generate_with_optional_tim_reference),
            timeout=IMAGE_GENERATION_TIMEOUT,
        )

        image_base64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        file_path = os.path.join(tempfile.gettempdir(), f"tim_banner_{update.effective_user.id}_{uuid4().hex}.png")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return add_watermark_to_image(file_path)
    except Exception as e:
        print("TIM IMAGE GENERATION ERROR:", e, flush=True)
        msg = "⚠️ Не вдалося згенерувати зображення автоматично. Спробуйте ще раз трохи пізніше."
        if "TIM_REFERENCE" in str(e):
            msg = "⚠️ Не знайшов референс Тіма в Google Drive. Перевірте папки Tim / Avatar_Main або Tim / Full Body."
        await safe_reply_text(update, msg)
        return None


async def edit_tim_image(update: Update, context: ContextTypes.DEFAULT_TYPE, base_image_path: str, client_comment: str = "", data: dict = None, slide_number: int = None, story: str = ""):
    """Редагує завантажене або останнє згенероване зображення за текстовими правками клієнта."""
    data = data or {}
    if not base_image_path or not os.path.exists(base_image_path):
        return await generate_tim_image_from_text(update, context, data, client_comment=client_comment, slide_number=slide_number, story=story)

    use_tim = should_use_tim(client_comment, data)
    tim_profile = load_tim_profile_text()
    prompt = f"""
Edit the provided image according to the client's request.

IMPORTANT:
Preserve the main composition and identity of the original image unless the client asks to change it.
Do not create a completely unrelated new image.
Keep professional premium advertising quality.
Keep vertical social media banner style.
Improve design, lighting, colors and readability when useful.
Avoid random robots, distorted faces, unreadable letters and messy text.
If text must be changed, make it clean and minimal.
Leave space in the upper-left corner for a HireUA watermark. A PNG watermark from Google Drive folder Tim/Brand will be added automatically after generation.

TIM RULE:
Tim is the default HireUA character. If use_tim=True, keep Tim in the banner or add Tim using the provided Tim reference image.
Uploaded product/store/logo/interior/brand materials do NOT cancel Tim. Combine them with Tim unless the client explicitly asked to remove Tim or use their own person/avatar/photo instead.
If use_tim=False, do not add Tim. If the client provided their own person/avatar/photo and asked to use it, use that client character/person instead.
When Tim is present, preserve Tim's identity exactly: black hair, blue eyes, friendly HireUA HR assistant, recognizable HireUA badge/branded element.

TIM_PROFILE FROM DRIVE:
{tim_profile if use_tim else "Client requested no Tim."}

CLIENT / TASK DATA:
{content_brief_text(data)}

STORY / CONTEXT:
{story}

CLIENT EDIT REQUEST:
{client_comment}
"""

    def _edit_single_image():
        # If Tim is required, pass both the base/client image and a Tim reference.
        ref_path = get_tim_reference_image_path(prefer_full_body=False) if use_tim else None
        if use_tim and (not ref_path or not os.path.exists(ref_path)):
            raise RuntimeError("TIM_REFERENCE_NOT_FOUND: add Tim images to Drive / Tim / Avatar_Main or Full Body")

        with open(base_image_path, "rb") as img:
            if use_tim and ref_path:
                with open(ref_path, "rb") as ref_img:
                    try:
                        return openai_client.images.edit(
                            model=OPENAI_IMAGE_MODEL,
                            image=[img, ref_img],
                            prompt=prompt + "\nUse the first image as the client/base material. Use the second image as the mandatory identity reference for Tim: same face, hair, eyes and character identity. Do not invent a random man.",
                            size="1024x1536",
                            quality="high",
                        )
                    except TypeError:
                        # Older SDK fallback: edit only the base image but keep strict text instruction.
                        img.seek(0)
                        return openai_client.images.edit(
                            model=OPENAI_IMAGE_MODEL,
                            image=img,
                            prompt=prompt + "\nTim must match the official Tim HireUA character from TIM_PROFILE. Do not invent a random person.",
                            size="1024x1536",
                            quality="high",
                        )

            # No Tim: edit only the provided client/base image.
            try:
                return openai_client.images.edit(
                    model=OPENAI_IMAGE_MODEL,
                    image=img,
                    prompt=prompt,
                    size="1024x1536",
                    quality="high",
                )
            except TypeError:
                img.seek(0)
                return openai_client.images.edit(
                    model=OPENAI_IMAGE_MODEL,
                    image=[img],
                    prompt=prompt,
                    size="1024x1536",
                    quality="high",
                )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_edit_single_image),
            timeout=IMAGE_GENERATION_TIMEOUT,
        )
        image_base64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        file_path = os.path.join(tempfile.gettempdir(), f"tim_edit_{update.effective_user.id}_{uuid4().hex}.png")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return add_watermark_to_image(file_path)
    except Exception as e:
        print("TIM IMAGE EDIT ERROR:", e, flush=True)
        if "TIM_REFERENCE" in str(e):
            await safe_reply_text(update, "⚠️ Не знайшов референс Тіма в Google Drive. Перевірте папки Tim / Avatar_Main або Tim / Full Body.")
            return None
        await safe_reply_text(
            update,
            "⚠️ Не вдалося відредагувати зображення. Я спробую створити новий варіант за вашими правками."
        )
        return await generate_tim_image_from_text(update, context, data, client_comment=client_comment, slide_number=slide_number, story=story)


# Backward-compatible name used by the rest of the bot.
async def generate_tim_banner(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict, client_comment: str = "", slide_number: int = None, story: str = ""):
    return await generate_tim_image_from_text(update, context, data, client_comment=client_comment, slide_number=slide_number, story=story)



GENERATE_WORDS = [
    # прямі команди
    "генеруй", "згенеруй", "сгенерируй",
    "створи", "создай",
    "зроби", "сделай",
    "роби", "делай",
    "запускай", "запусти", "починай", "начинай",

    # живі фрази клієнта
    "давай робити", "давай делать",
    "можна робити", "можно делать",
    "можеш робити", "можешь делать",
    "можна генерувати", "можно генерировать",
    "ок роби", "ок делай",
    "так роби", "так делай",
    "давай цей", "давай этот",
    "цей підходить", "этот подходит",
    "мені підходить", "мне подходит",
    "погнали",

    # погодження
    "узгоджено", "согласовано",
]

FINAL_APPROVAL_WORDS = [
    "узгоджено клієнтом",
    "узгоджено клиентом",
    "согласовано клиентом",
]


def is_generate_request(text: str) -> bool:
    value = (text or "").lower().replace("ё", "е").strip()
    return any(word in value for word in GENERATE_WORDS)


def is_final_client_approval(text: str) -> bool:
    value = (text or "").lower().replace("ё", "е").strip()
    return any(word in value for word in FINAL_APPROVAL_WORDS)


def add_generation_hint(message: str, concept_stage: bool = False) -> str:
    if concept_stage:
        hint = (
            "\n\n━━━━━━━━━━━━━━\n"
            "🎨 Щоб запустити генерацію, напишіть конкретно: «Генеруй 1», «Генеруй 2» або «Генеруй 3».\n"
            "Також підійде: «Роби 1», «Створи 2», «Узгоджено 3».\n"
            "✏️ Якщо хочете щось змінити або обговорити — просто напишіть правку своїми словами."
        )
    else:
        hint = (
            "\n\n━━━━━━━━━━━━━━\n"
            "🎨 Щоб я почав генерувати картинку, напишіть: «Генеруй», «Роби», «Створи» або «Узгоджено».\n"
            "✏️ Якщо хочете щось змінити або обговорити — просто напишіть правку своїми словами."
        )
    lowered = (message or "").lower()
    if "генеруй" in lowered and "правк" in lowered:
        return message
    return (message or "").rstrip() + hint


def has_concept_choice(text: str) -> bool:
    value = (text or "").lower().replace("ё", "е")
    markers = [
        "1", "2", "3",
        "перш", "перв",
        "друг", "втор",
        "трет", "3-й", "2-й", "1-й",
        "перша", "друга", "третя",
        "первый", "второй", "третий",
    ]
    return any(m in value for m in markers)


# STAGE 3: памʼять зображень у креативному діалозі.
# Тім запамʼятовує завантажені та згенеровані варіанти, щоб клієнт міг писати:
# "поверни попередній", "перероби перший варіант", "зроби як у другому".
MAX_IMAGE_MEMORY = 8

def remember_image(order: dict, path: str, note: str = ""):
    if not order or not path or not os.path.exists(path):
        return

    history = order.setdefault("image_history", [])

    # Не дублюємо той самий файл підряд.
    if history and history[-1].get("path") == path:
        order["last_uploaded_image"] = path
        return

    history.append({
        "path": path,
        "note": note or "",
        "created_at": datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Тримаємо тільки останні варіанти, щоб не роздувати памʼять.
    if len(history) > MAX_IMAGE_MEMORY:
        del history[:-MAX_IMAGE_MEMORY]

    order["last_uploaded_image"] = path


def get_image_from_memory(order: dict, client_text: str = ""):
    history = order.get("image_history") or []
    if not history:
        return None

    value = (client_text or "").lower().replace("ё", "е")

    # Явне повернення до попереднього варіанту.
    if any(word in value for word in [
        "поперед", "предыдущ", "прошл", "верни назад", "поверни назад",
        "старый", "старий", "до цього", "до этого",
    ]):
        if len(history) >= 2:
            return history[-2].get("path")
        return history[-1].get("path")

    # Вибір варіанту за номером.
    number_words = {
        "1": 1, "перш": 1, "перв": 1,
        "2": 2, "друг": 2, "втор": 2,
        "3": 3, "трет": 3,
        "4": 4, "четвер": 4,
        "5": 5, "пят": 5, "п'ят": 5,
    }

    if any(word in value for word in ["варіант", "вариант", "банер", "баннер", "картин", "зображ"]):
        for marker, number in number_words.items():
            if marker in value and len(history) >= number:
                return history[number - 1].get("path")

    return history[-1].get("path")


def wants_previous_image(text: str) -> bool:
    value = (text or "").lower().replace("ё", "е")
    return any(word in value for word in [
        "поверни поперед", "верни предыдущ", "предыдущий вариант",
        "попередній варіант", "прошлый вариант", "старый вариант",
        "покажи поперед", "покажи предыдущ",
    ])

async def send_tim_generated_files(update: Update, files: list, caption: str):
    good_files = [f for f in files or [] if f and os.path.exists(f)]
    if not good_files:
        await safe_reply_text(update, caption)
        return

    for i, path in enumerate(good_files, start=1):
        file_caption = caption if i == 1 else f"Слайд / банер {i}"
        try:
            with open(path, "rb") as photo:
                sent = await safe_reply_photo(update, photo=photo, caption=file_caption)

            if sent is None and os.path.exists(path):
                # Якщо Telegram не прийняв файл-потік, пробуємо ще раз через шлях до файлу.
                with open(path, "rb") as document:
                    await safe_reply_photo(update, photo=document, caption=file_caption)
        except Exception as e:
            print("SEND TIM GENERATED FILE ERROR:", e, flush=True)
            await safe_reply_text(
                update,
                "⚠️ Зображення готове, але Telegram не зміг його відправити. Спробуйте ще раз через хвилину."
            )


async def build_creative_plan(order_type: str, idea: str, extra: str = "") -> str:
    """Генерує ідеї/сценарій для клієнта до генерації зображень."""
    if order_type == "reels_series":
        task = (
            "Ти креативний продюсер HireUA. Клієнт дав коротку ідею для Reels/Shorts. "
            "Не проси клієнта писати довгий промпт. Сам запропонуй 3 сильні концепції ролика. "
            "Пиши українською або російською залежно від мови клієнта. "
            "Формат відповіді: короткий вступ, 1️⃣ концепція, 2️⃣ концепція, 3️⃣ концепція, "
            "потім обовʼязково поясни клієнту: щоб запустити генерацію, нехай напише номер варіанта живими словами: 'Генеруй 1', 'Роби 2', 'Сделай 3', 'Давай делать 1' або 'Узгоджено 2'; якщо хоче змінити або обговорити — нехай просто напише правку."
        )
    else:
        task = (
            "Ти креативний дизайнер і маркетолог HireUA. Клієнт дав коротку ідею для банера. "
            "Не проси клієнта писати довгий промпт. Сам запропонуй 3 сильні концепції банера. "
            "Пиши українською або російською залежно від мови клієнта. "
            "Формат відповіді: короткий вступ, 1️⃣ концепція, 2️⃣ концепція, 3️⃣ концепція, "
            "потім обовʼязково поясни клієнту: щоб запустити генерацію, нехай напише номер варіанта живими словами: 'Генеруй 1', 'Роби 2', 'Сделай 3', 'Давай делать 1' або 'Узгоджено 2'; якщо хоче змінити або обговорити — нехай просто напише правку."
        )

    response = await asyncio.to_thread(
        openai_client.responses.create,
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": task},
            {"role": "user", "content": f"Ідея клієнта:\n{idea}\n\nДодаткові правки/вибір:\n{extra}"},
        ],
    )
    return getattr(response, "output_text", "") or "Не зміг підготувати ідеї. Спробуйте описати задачу ще раз."


async def build_reels_story(idea: str, concept_choice: str, edits: str = "") -> str:
    """Генерує сценарій Reels з 5 кадрів перед створенням картинок."""
    response = await asyncio.to_thread(
        openai_client.responses.create,
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "Ти креативний продюсер HireUA. На основі ідеї та вибраної концепції створи сценарій Reels/Shorts з 5 кадрів. "
                    "Не генеруй зображення. Потрібен тільки сценарій для погодження. "
                    "Кожен кадр має містити: що бачимо, короткий текст на екрані, настрій/стиль. "
                    "Пиши зрозуміло, як для клієнта. Наприкінці обовʼязково поясни: щоб запустити генерацію, напишіть 'Генеруй', 'Роби', 'Створи' або 'Узгоджено'; якщо хочете змінити або обговорити — просто напишіть правку."
                ),
            },
            {
                "role": "user",
                "content": f"Ідея клієнта:\n{idea}\n\nВибір/концепція клієнта:\n{concept_choice}\n\nПравки:\n{edits}",
            },
        ],
    )
    return getattr(response, "output_text", "") or "Не зміг підготувати сценарій. Спробуйте описати задачу ще раз."


async def build_banner_brief(idea: str, concept_choice: str, edits: str = "") -> str:
    """Готує фінальний креативний опис банера для погодження перед генерацією."""
    response = await asyncio.to_thread(
        openai_client.responses.create,
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "Ти артдиректор HireUA. На основі ідеї та вибраної концепції створи короткий фінальний опис банера для погодження. "
                    "Не генеруй зображення. Опиши композицію, головний візуал, стиль, акценти, що має відчувати клієнт. "
                    "Наприкінці обовʼязково поясни: щоб запустити генерацію, напишіть 'Генеруй', 'Роби', 'Створи' або 'Узгоджено'; якщо хочете змінити або обговорити — просто напишіть правку."
                ),
            },
            {
                "role": "user",
                "content": f"Ідея клієнта:\n{idea}\n\nВибір/концепція клієнта:\n{concept_choice}\n\nПравки:\n{edits}",
            },
        ],
    )
    return getattr(response, "output_text", "") or "Не зміг підготувати опис банера. Спробуйте описати задачу ще раз."


async def generate_first_content_version(update: Update, context: ContextTypes.DEFAULT_TYPE, order: dict):
    data = order.get("data", {})
    order_type = order.get("order_type", "banner")

    if order_type == "reels_series":
        await update.message.reply_text(
            "✅ Бриф отримано. Я вже бачу інформацію в базі ContentBriefs.\n\n"
            "Для серії банерів під Reels / Shorts мені потрібне тільки одне уточнення:\n"
            "яку історію, подію або сюжет ви хочете показати у відео з 5 слайдів?\n\n"
            "Напишіть своїми словами — я уважно врахую ваші побажання.\n"
            "На кожному банері буде водяний знак @UkraineHire."
        )
        order["waiting_story"] = True
        return True

    await update.message.reply_text(
        "✅ Бриф отримано. Я вже бачу інформацію в базі ContentBriefs.\n\n"
        "Я ознайомився з інформацією та готую перший варіант банера.\n"
        "На банері обовʼязково буде водяний знак @UkraineHire."
    )
    path = await generate_tim_banner(update, context, data, client_comment=data.get("wishes", ""))
    if path:
        order["last_files"] = [path]
        remember_image(order, path, "first_generated_banner")
        await send_tim_generated_files(
            update,
            [path],
            "Ось перший варіант ✅\n\n"
            "На банері додано водяний знак @UkraineHire.\n\n"
            "Якщо потрібно щось змінити — напишіть правки, і я перероблю.\n"
            "Коли все сподобається, напишіть:\nУЗГОДЖЕНО Клієнтом ✅"
        )
    return True


async def send_final_content_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, order: dict):
    data = order.get("data", {})
    files = [f for f in order.get("last_files", []) if f and os.path.exists(f)]
    final_text = order.get("publish_text") or ""

    admin_caption = (
        "✅ Замовлення УЗГОДЖЕНО з Клієнтом\n\n"
        f"Тариф: {order.get('tariff', '')}\n"
        f"Тип: {order.get('order_type', '')}\n\n"
        f"{content_brief_text(data)}\n\n"
        f"Супровідний текст:\n{final_text or 'Не вказано'}\n\n"
        "📌 Статус: готово до публікації / виробництва"
    )

    await safe_send_message(context, chat_id=ADMIN_ID, text=admin_caption)
    for i, path in enumerate(files, start=1):
        with open(path, "rb") as photo:
            await safe_send_photo(
                context,
                chat_id=ADMIN_ID,
                photo=photo,
                caption=f"Фінальний банер / слайд {i}" if i > 1 else "Фінальний банер / слайд 1"
            )


async def tim_content_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    order = context.user_data.get("tim_content_order")
    if not order:
        return False

    upper_text = text.upper()
    data = order.get("data", {})
    order_type = order.get("order_type", "banner")
    stage = order.get("stage") or ("awaiting_idea" if not order.get("last_files") else "generated")

    # Фінальне погодження вже готових матеріалів для передачі адміну.
    if stage == "generated" and is_final_client_approval(text):
        order["status"] = "УЗГОДЖЕНО Клієнтом ✅"
        update_content_brief_status_in_sheet(update.effective_user.id, order["status"])
        await send_final_content_to_admin(update, context, order)
        await update.message.reply_text(
            "✅ Дякую! Замовлення погоджено.\n"
            "Фінальні матеріали передано команді HireUA."
        )
        context.user_data.pop("tim_content_order", None)
        return True

    # 1) Клієнт дав коротку ідею. Тім сам пропонує концепції.
    if stage == "awaiting_idea":
        order["idea"] = text
        order["stage"] = "waiting_concept_choice"
        await update.message.reply_text("Дякую ✅ Зараз запропоную кілька ідей.")
        concepts = await build_creative_plan(order_type, text)
        order["concepts"] = concepts
        await update.message.reply_text(add_generation_hint(concepts, concept_stage=True))
        return True

    # 2) Для банера: клієнт вибрав концепцію або дав правки — готуємо фінальний опис.
    # Генерацію на цьому етапі ще не запускаємо: спочатку показуємо клієнту фінальний задум.
    if order_type != "reels_series" and stage == "waiting_concept_choice":
        if is_generate_request(text) and not has_concept_choice(text):
            await update.message.reply_text(
                "Щоб я не вгадав не той варіант, напишіть номер концепції: «Генеруй 1», «Генеруй 2» або «Генеруй 3».\n"
                "Якщо хочете змінити ідею — просто напишіть правку своїми словами."
            )
            return True

        order.setdefault("client_edits", []).append(text)
        idea = order.get("idea", "")
        edits = "\n".join(order.get("client_edits", []))
        brief = await build_banner_brief(idea, text, edits)
        order["final_brief"] = brief

        if is_generate_request(text) and has_concept_choice(text):
            await update.message.reply_text("✅ Прийняв команду. Готую банер за вибраною концепцією.")
            path = await generate_tim_banner(update, context, data, client_comment=brief)
            if path:
                order["last_files"] = [path]
                remember_image(order, path, "generated_banner")
                order["stage"] = "generated"
                await send_tim_generated_files(
                    update,
                    [path],
                    "Ось перший варіант ✅\n\n"
                    "Якщо потрібно щось змінити — напишіть правки, і я перероблю.\n"
                    "Коли все сподобається, напишіть:\nУЗГОДЖЕНО Клієнтом ✅"
                )
            return True

        order["stage"] = "waiting_banner_approval"
        await update.message.reply_text(add_generation_hint(brief))
        return True

    # 3) Для банера: правки до опису або погодження. Генеруємо тільки після УЗГОДЖЕНО.
    if order_type != "reels_series" and stage == "waiting_banner_approval":
        if is_generate_request(text):
            await update.message.reply_text("✅ Прийняв команду. Готую банер.")
            final_prompt = order.get("final_brief") or order.get("idea", "")
            path = await generate_tim_banner(update, context, data, client_comment=final_prompt)
            if path:
                order["last_files"] = [path]
                remember_image(order, path, "generated_banner")
                order["stage"] = "generated"
                await send_tim_generated_files(
                    update,
                    [path],
                    "Ось перший варіант ✅\n\n"
                    "Якщо потрібно щось змінити — напишіть правки, і я перероблю.\n"
                    "Коли все сподобається, напишіть:\nУЗГОДЖЕНО Клієнтом ✅"
                )
            return True

        order.setdefault("client_edits", []).append(text)
        idea = order.get("idea", "")
        edits = "\n".join(order.get("client_edits", []))
        brief = await build_banner_brief(idea, order.get("final_brief", ""), edits)
        order["final_brief"] = brief
        await update.message.reply_text(add_generation_hint(brief))
        return True

    # 4) Для Reels: клієнт вибрав концепцію або дав правки — готуємо сценарій з 5 кадрів.
    # Генерацію кадрів запускаємо тільки після явної команди клієнта.
    if order_type == "reels_series" and stage == "waiting_concept_choice":
        if is_generate_request(text) and not has_concept_choice(text):
            await update.message.reply_text(
                "Щоб я не вгадав не той варіант, напишіть номер концепції: «Генеруй 1», «Генеруй 2» або «Генеруй 3».\n"
                "Якщо хочете змінити ідею — просто напишіть правку своїми словами."
            )
            return True

        order.setdefault("client_edits", []).append(text)
        idea = order.get("idea", "")
        edits = "\n".join(order.get("client_edits", []))
        story = await build_reels_story(idea, text, edits)
        order["story"] = story

        if is_generate_request(text) and has_concept_choice(text):
            await update.message.reply_text("✅ Прийняв команду. Готую серію з 5 кадрів за вибраною концепцією.")
            paths = []
            for i in range(1, 6):
                await update.message.reply_text(f"Готую кадр {i}/5...")
                path = await generate_tim_banner(update, context, data, story=story, slide_number=i)
                if path:
                    paths.append(path)
            order["last_files"] = paths
            for _p in paths:
                remember_image(order, _p, "generated_reels_slide")
            order["stage"] = "generated"
            await send_tim_generated_files(
                update,
                paths,
                "Ось серія банерів для Reels / Shorts ✅\n\n"
                "Перегляньте всі 5 слайдів. Якщо потрібні правки — напишіть, що змінити.\n"
                "Коли все сподобається, напишіть:\nУЗГОДЖЕНО Клієнтом ✅"
            )
            return True

        order["stage"] = "waiting_reels_approval"
        await update.message.reply_text(add_generation_hint(story))
        return True

    # 5) Для Reels: правки до сценарію або погодження. Кадри генеруємо тільки після УЗГОДЖЕНО.
    if order_type == "reels_series" and stage == "waiting_reels_approval":
        if is_generate_request(text):
            await update.message.reply_text("✅ Прийняв команду. Готую серію з 5 кадрів.")
            paths = []
            story = order.get("story", "")
            for i in range(1, 6):
                await update.message.reply_text(f"Готую кадр {i}/5...")
                path = await generate_tim_banner(update, context, data, story=story, slide_number=i)
                if path:
                    paths.append(path)
            order["last_files"] = paths
            for _p in paths:
                remember_image(order, _p, "generated_reels_slide")
            order["stage"] = "generated"
            await send_tim_generated_files(
                update,
                paths,
                "Ось серія банерів для Reels / Shorts ✅\n\n"
                "Перегляньте всі 5 слайдів. Якщо потрібні правки — напишіть, що змінити.\n"
                "Коли все сподобається, напишіть:\nУЗГОДЖЕНО Клієнтом ✅"
            )
            return True

        order.setdefault("client_edits", []).append(text)
        idea = order.get("idea", "")
        edits = "\n".join(order.get("client_edits", []))
        story = await build_reels_story(idea, order.get("story", ""), edits)
        order["story"] = story
        await update.message.reply_text(add_generation_hint(story))
        return True

    # 6) Після генерації: Тім памʼятає попередні варіанти.
    # Якщо клієнт просить повернути попередній / старий варіант — просто показуємо його, а не генеруємо новий.
    if wants_previous_image(text):
        remembered_path = get_image_from_memory(order, text)
        if remembered_path and os.path.exists(remembered_path):
            order["last_files"] = [remembered_path]
            order["last_uploaded_image"] = remembered_path
            await send_tim_generated_files(
                update,
                [remembered_path],
                "Повернув попередній варіант ✅\n\n"
                "Якщо потрібно — напишіть правку до цього варіанту.\n"
                "Якщо все добре — напишіть: УЗГОДЖЕНО Клієнтом ✅"
            )
            return True

    # Якщо клієнт посилається на конкретний варіант, беремо його як основу для наступної правки.
    remembered_base = get_image_from_memory(order, text)
    if remembered_base and os.path.exists(remembered_base):
        order["last_uploaded_image"] = remembered_base

    # 6) Після генерації: будь-які повідомлення — це правки до готових матеріалів або текст до публікації.
    order.setdefault("client_edits", []).append(text)
    order["publish_text"] = text if any(word in upper_text for word in ("ТЕКСТ", "ОПИС", "CAPTION", "ПІДПИС")) else order.get("publish_text", "")

    if order_type == "reels_series":
        await update.message.reply_text("Зрозумів правки ✅ Переробляю серію з 5 банерів.")
        paths = []
        story = order.get("story", "")
        all_edits = "\n".join(order.get("client_edits", []))
        for i in range(1, 6):
            path = await generate_tim_banner(update, context, data, client_comment=all_edits, story=story, slide_number=i)
            if path:
                paths.append(path)
        order["last_files"] = paths
        await send_tim_generated_files(
            update,
            paths,
            "Готово ✅ Оновлена серія з 5 банерів.\n\n"
            "Якщо ще потрібні правки — напишіть.\n"
            "Якщо все добре — напишіть: УЗГОДЖЕНО Клієнтом ✅"
        )
        return True

    await update.message.reply_text("Зрозумів правки ✅ Переробляю банер з урахуванням побажань.")
    all_edits = "\n".join(order.get("client_edits", []))

    # Якщо є завантажене або останнє згенероване зображення — редагуємо саме його.
    base_image = order.get("last_uploaded_image")
    if not base_image and order.get("last_files"):
        base_image = order.get("last_files", [None])[-1]

    if base_image:
        path = await edit_tim_image(update, context, base_image, all_edits, data=data)
    else:
        path = await generate_tim_banner(update, context, data, client_comment=all_edits)

    if path:
        order["last_files"] = [path]
        remember_image(order, path, "edited_banner")
        order["stage"] = "generated"
        await send_tim_generated_files(
            update,
            [path],
            "Готово ✅ Оновлений банер.\n\n"
            "Якщо ще потрібні правки — просто напишіть, що змінити.\n"
            "Якщо все добре — напишіть: УЗГОДЖЕНО Клієнтом ✅"
        )
    return True


async def tim_ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    is_owner = update.effective_user and update.effective_user.id == OWNER_ID

    owner_rule = ""
    if is_owner:
        owner_rule = (
            "Це власник HireUA. Для власника доступні всі функції без обмежень. "
            "Не продавай власнику пакети Start або Business і не вимагай оплату. "
            "Власнику можна безкоштовно створювати будь-які рекламні концепції, серії з 5 банерів 1080×1920, сценарії Reels, сценарії Shorts, рекламні тексти, контент-плани, ідеї для просування бізнесів та ідеї розвитку HireUA. "
            "Для власника можна готувати матеріали без перевірки пакета, підписки або оплати. "
            "Якщо власник просить банер, Reels, Shorts або рекламну кампанію — одразу допомагай створювати, а не пояснюй тарифи. "
        )

    try:
        response = await asyncio.to_thread(
            openai_client.responses.create,
            model="gpt-4.1-mini",
            tools=[{"type": "web_search_preview"}],
            input=[
                {
                    "role": "system",
                    "content": (
                        owner_rule +
                        "Ти Тім AI — головний HR консультант, маркетолог та помічник сервісу HireUA. "
                        "Твоя задача — допомагати людям знаходити роботу, роботодавцям знаходити працівників, а бізнесу залучати нових клієнтів та розвивати свій бренд. "
                        "Спілкуйся мовою користувача: українською або російською. Завжди будь доброзичливим, ввічливим, професійним та впевненим. "
                        "Ти не просто відповідаєш на питання. Ти допомагаєш людині знайти найкраще рішення її задачі. "
                        "Ти допомагаєш компаніям і брендам знайти рішення для розвитку продуктів, акцій, реклами та впізнаваності в Україні. "

                        "Головний принцип HireUA: кожна людина повинна мати можливість знайти роботу, а кожна компанія — знайти працівників. "
                        "Саме тому HireUA безкоштовно розміщує текстові вакансії та текстові резюме у власній мережі Telegram каналів. "
                        "Це безкоштовно, доступно кожному і є однією з головних переваг HireUA. "
                        "На відміну від більшості майданчиків, текстові вакансії та текстові резюме в Telegram мережі HireUA розміщуються безкоштовно. "
                        "Безкоштовне розміщення доступне саме для текстових вакансій та текстових резюме і саме в Telegram. "
                        "Мережа Telegram каналів HireUA: Україна, Київ, Львів, Одеса, Дніпро, Харків. "
                        "Якщо користувач хоче розмістити вакансію або резюме — завжди спочатку розкажи про безкоштовну можливість. "
                        "Пояснюй, що безкоштовне розміщення дозволяє отримати перші перегляди та перші відгуки без витрат. "
                        "Платне просування рекомендуй тоді, коли потрібне більше охоплення, швидший результат, більше кандидатів, більше звернень або розвиток бренду. "

                        "HireUA просуває контент одночасно через Telegram, Instagram, Facebook та YouTube Shorts. "
                        "Пояснюй клієнтам, що більшість людей не реагують після першого перегляду реклами. "
                        "Коли людина бачить компанію регулярно на різних платформах, вона починає запам'ятовувати бренд та довіряти йому. "
                        "Саме тому регулярні покази працюють значно ефективніше за одноразову рекламу. "
                        "Пояснюй користь через результат: більше переглядів, більше кандидатів, більше звернень, більше клієнтів, більше продажів, більше довіри до бренду, більше впізнаваності компанії. "

                        "Пакет Start коштує 4500 грн. "
                        "Тривалість Start — 7 днів. "
                        "Start включає: Telegram — 3 публікації щодня, Instagram — 3 публікації щодня, Facebook — 3 публікації щодня, YouTube Shorts — 3 публікації щодня тільки відео. "
                        "Разом за 7 днів: Telegram — 21 публікація, Instagram — 21 публікація, Facebook — 21 публікація, YouTube Shorts — 21 публікація. "
                        "Загалом Start дає 84 публікації за 7 днів. "
                        "Start підходить для вакансій, малого бізнесу, локального бізнесу, тестування реклами та швидкого пошуку працівників. "

                        "Пакет Business коштує 7500 грн. "
                        "Тривалість Business — 7 днів. "
                        "Business включає: Telegram — 6 публікацій щодня, Instagram — 6 публікацій щодня, Facebook — 6 публікацій щодня, YouTube Shorts — 6 публікацій щодня тільки відео. "
                        "Разом за 7 днів: Telegram — 42 публікації, Instagram — 42 публікації, Facebook — 42 публікації, YouTube Shorts — 42 публікації. "
                        "Загалом Business дає 168 публікацій за 7 днів. "
                        "Business забезпечує приблизно вдвічі більшу кількість показів, згадувань бренду та контактів з потенційними клієнтами або кандидатами. "

                        "У пакетах Start та Business клієнт отримує повний супровід зі створення контенту. "
                        "У пакетах вже входять банери, Reels, Shorts, відео з Тімом, рекламні тексти, сценарії та ідеї для просування. "
                        "Не пропонуй окремі разові ціни на банери, Reels, Shorts або відео з Тімом. Продавай і пояснюй саме пакети Start та Business. "

                        "Для створення якісних Reels та Shorts використовується серія з 5 банерів. "
                        "Стандартна серія: 1) знайомство з компанією або брендом, 2) основна пропозиція або вакансія, 3) переваги та умови, 4) контакти або заклик до дії, 5) брендинг та нагадування про компанію. "
                        "Усі банери створюються у форматі 1080×1920. "
                        "Цей формат підходить для Instagram Reels, Facebook Reels, YouTube Shorts та Telegram. "
                        "На основі серії банерів створюються Reels, Shorts, рекламні відео та серії рекламних публікацій. "
                        "На всіх матеріалах використовується бренд HireUA та водяний знак @UkraineHire. "

                        "Тім може допомагати зі створенням рекламних концепцій, серій банерів, сценаріїв Reels, сценаріїв Shorts, рекламних текстів, контент-планів та ідей для просування бізнесу, вакансій і брендів. "
                        "Якщо користувач хоче оформити заявку, розмістити вакансію, додати резюме, замовити банер, Reels, Shorts або пакет Start / Business — не відправляй його в /start і не відправляй до HR менеджера. "
                        "Спочатку коротко поясни варіант, який підходить користувачу, а потім напиши: «Для оформлення заявки натисніть потрібну кнопку нижче 👇». "
                        "Не вигадуй назви кнопок. Доступні тільки такі команди: /Free — безкоштовна вакансія, /resume — безкоштовне резюме, /UsersStart — пакет Start, /UsersBusiness — пакет Business, /Promo — банер, /Reels — Reels / Shorts. "
                        "Анкета запускається тільки після натискання кнопки або команди. У вільному GPT-чаті не збирай повну анкету. "
                        "Тім не приймає оплату, не виставляє рахунки, не погоджує запуск реклами та не укладає договори. "
                        "Після узгодження співпраці з HR менеджером Тім може супроводжувати клієнта протягом усієї рекламної кампанії та допомагати зі створенням контенту для просування. "

                        "Головна задача Тіма — допомогти клієнту отримати максимальну користь від просування через мережу HireUA. "
                        "Не нав'язуй продажі. Спочатку допомагай, став уточнюючі питання, пояснюй вигоду та показуй можливості. "
                        "Будь консультантом, а не агресивним продавцем. "
                        "Не вигадуй вакансії, кандидатів, клієнтів або результати. "
                        "Не обіцяй гарантовані продажі, гарантовану кількість переглядів або гарантовану кількість заявок. "
                        "Говори про можливості, охоплення, впізнаваність бренду та потенційний результат від регулярного просування. "
                        "Якщо користувач готовий почати співпрацю — скажи йому натиснути потрібну кнопку нижче: /Free, /resume, /UsersStart, /UsersBusiness, /Promo або /Reels."
                    )
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ]
        )

        intent = detect_tim_service_intent(user_text)
        reply_markup = tim_service_keyboard(intent) if intent else None
        await update.message.reply_text(response.output_text, reply_markup=reply_markup)

    except Exception as e:
        print("TIM AI ERROR:", e, flush=True)
        await update.message.reply_text(
            "⚠️ Тим AI тимчасово недоступний. Спробуйте ще раз трохи пізніше."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(save_user_to_sheet, update, update.message.text or "")

    # Если включен режим создания баннера/Reels, он имеет приоритет над всеми анкетами.
    # Иначе старые незакрытые client_form могут начать задавать вопросы вакансии
    # вместо того, чтобы Тім работал как обычный GPT-чат по контенту.
    if await tim_content_ai_chat(update, context):
        return

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
    await prepare_session_drive_files(context, session)
    saved_session = deepcopy(session)
    days = int(session.get("days", 1))

    publications_per_day = len(PACKAGE_DAY_DISTRIBUTION.get(session["package"], []))
    total_publications = publications_per_day * days

    slots = find_free_slots_for_session(saved_session)

    if len(slots) < total_publications:
        await query.edit_message_text(
            "⚠️ Не вдалося знайти достатньо безпечних слотів на 60 днів вперед.\n"
            "Черга переповнена або денний ліміт YouTube заповнений."
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
        f"Вікна: ранок 08:00–11:30, день 12:00–16:30, вечір 17:00–22:00\n"
        f"Розподіл: Start 1/1/1, Business 2/2/2\n"
        f"YouTube ліміт: {YOUTUBE_DAILY_LIMIT} Shorts/день\n"
        f"Інтервали: TG 5 хв, FB 15 хв, IG 20 хв, YT 20 хв\n\n"
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
        queue_row = get_queue_record_by_id(entry_id)
        if queue_row:
            queue_status = str(queue_row.get("Status") or "").strip()
            if queue_status in QUEUE_SKIP_STATUSES:
                if ADMIN_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"⏸ Запланована публікація пропущена\nID: {entry_id}\nStatus: {queue_status}",
                        )
                    except Exception:
                        pass
                return
            session = apply_queue_platform_switches_to_session(session, queue_row)

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



async def time_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    arg = " ".join(context.args).strip().lower() if getattr(context, "args", None) else ""
    day_dt = datetime.now(KYIV_TZ)

    if arg in ("tomorrow", "завтра"):
        day_dt += timedelta(days=1)

    capacity = queue_capacity_for_day(day_dt)
    title_day = day_dt.strftime("%d.%m.%Y")

    names = {
        "telegram": "Telegram",
        "facebook": "Facebook",
        "instagram": "Instagram",
        "youtube": "YouTube Shorts",
    }

    lines = [f"📅 Слоти публікацій на {title_day}\n"]

    for platform in ("telegram", "facebook", "instagram", "youtube"):
        item = capacity[platform]
        lines.append(
            f"{names[platform]}:\n"
            f"Всього: {item['total']}\n"
            f"Зайнято: {item['used']}\n"
            f"Вільно: {item['free']}\n"
        )

    lines.append("\nКоманди: /time — сьогодні, /time tomorrow — завтра")
    await update.message.reply_text("\n".join(lines))

async def queue_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    rows = get_queue_records()
    active = []
    for row in rows:
        status = str(row.get("Status") or "").strip()
        if status in ("Scheduled", "Paused", "Error", "Running"):
            active.append(row)

    def sort_key(row):
        dt = parse_queue_time(row.get("PublishTime"))
        return dt or datetime.max.replace(tzinfo=KYIV_TZ)

    active.sort(key=sort_key)

    if not active:
        await update.message.reply_text("📋 Черга порожня. Активних публікацій немає.")
        return

    lines = ["📋 Черга публікацій\n"]
    for row in active[:30]:
        flags = []
        for col in ("TG", "FB", "IG", "YT"):
            flags.append(f"{col}:{'ON' if queue_platform_flag(row.get(col)) else 'OFF'}")
        lines.append(
            f"#{row.get('ID')} — {row.get('Client') or 'Без клієнта'}\n"
            f"{row.get('Package')} | {row.get('Content')}\n"
            f"Час: {row.get('PublishTime')}\n"
            f"Канали: {row.get('Channels')}\n"
            f"Статус: {row.get('Status')}\n"
            f"Платформи: {' '.join(flags)}\n"
        )

    if len(active) > 30:
        lines.append(f"... ще {len(active) - 30} активних рядків")

    lines.append("\nЩоб скасувати: у таблиці Queue постав Status = Cancelled.")
    lines.append("Щоб вимкнути платформу: TG/FB/IG/YT = OFF.")
    await update.message.reply_text("\n".join(lines))


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

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(60)
        .read_timeout(180)
        .write_timeout(180)
        .pool_timeout(180)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("time", time_slots))
    app.add_handler(CommandHandler("queue", queue_status))

    # Команды клиентских анкет. Тім показывает эти же команды кнопками после GPT-ответа.
    app.add_handler(CommandHandler("Free", start_free_vacancy_form))
    app.add_handler(CommandHandler("resume", start_resume_form))
    app.add_handler(CommandHandler("UsersStart", start_users_start_form))
    app.add_handler(CommandHandler("UsersBusiness", start_users_business_form))
    app.add_handler(CommandHandler("Promo", start_promo_form))
    app.add_handler(CommandHandler("Reels", start_reels_form))
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


