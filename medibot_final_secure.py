# -*- coding: utf-8 -*-
# medibot_full_ar.py
# Arabic full medication reminder bot (single-file, ready)
# Features:
# - Registration flow: name -> phone -> age -> email -> country -> payment
# - Payment links by country (PayTabs sample links)
# - "I paid" confirmation button to continue
# - Main control panel with "أدويتي" submenu (عرض، إضافة، تعديل، حذف)
# - "رجوع" زر في كل مرحلة ليعود للقائمة السابقة
# - APScheduler reminders and optional Azure TTS voice reminder
# - Saves state to data.json (UTF-8)
#
# Env variables:
# BOT_TOKEN (required)
# WEBHOOK_MODE = "poll" or "webhook" (default "poll")
# WEBHOOK_URL_BASE required for webhook mode (https://...)
# Optional for Azure TTS:
# AZURE_TTS_KEY, AZURE_TTS_REGION
#
# Requirements (see bottom): pyTelegramBotAPI Flask APScheduler python-dotenv requests

import os
import json
import threading
import traceback
from datetime import datetime
from functools import partial
from pathlib import Path
import time
import uuid

from flask import Flask, request
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Optional import for HTTP requests (for Azure TTS)
import requests

# -----------------------
# Load environment
# -----------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env required")

WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "poll").lower()  # "poll" or "webhook"
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")  # e.g. https://xyz.ngrok.io
if WEBHOOK_MODE == "webhook" and not WEBHOOK_URL_BASE:
    raise RuntimeError("WEBHOOK_URL_BASE required when WEBHOOK_MODE=webhook")
WEBHOOK_URL = f"{WEBHOOK_URL_BASE.rstrip('/')}/{BOT_TOKEN}" if WEBHOOK_URL_BASE else None

AZURE_TTS_KEY = os.getenv("AZURE_TTS_KEY")  # optional
AZURE_TTS_REGION = os.getenv("AZURE_TTS_REGION")  # optional like "eastus"

DATA_FILE = "data.json"
DATA_LOCK = threading.Lock()

# -----------------------
# Init
# -----------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# in-memory data; persisted to DATA_FILE
# structure:
# data = {
#   "<user_id>": {
#       "step": "...",
#       "name": "...",
#       "phone": "...",
#       "age": 0,
#       "email": "...",
#       "country": "EG"/"SA"/"DEFAULT",
#       "paid": False,
#       "medicines": [ { "id": "...", "اسم": "...", "الجرعة": "...", "الأوقات": ["08:30", ...] }, ... ],
#       "temp": {...}
#   }
# }
data = {}

# -----------------------
# JSON save/load
# -----------------------
def load_data():
    global data
    try:
        if Path(DATA_FILE).exists():
            with DATA_LOCK:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
        else:
            data = {}
    except Exception:
        print("load_data failed:", traceback.format_exc())
        data = {}

def save_data():
    try:
        with DATA_LOCK:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        print("save_data failed:", traceback.format_exc())

# -----------------------
# Scheduler helpers
# -----------------------
def sanitize_job_id(raw: str) -> str:
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in raw)

def send_reminder(user_id: int, med_id: str):
    """Send text reminder and attempt Azure TTS voice if configured."""
    try:
        u = data.get(str(user_id))
        if not u:
            return
        med = next((m for m in u.get("medicines", []) if m.get("id") == med_id), None)
        if not med:
            return
        now = datetime.now().strftime("%H:%M")
        text = f"⏰ تذكير بالدواء:\n💊 {med.get('اسم')}\n📝 الجرعة: {med.get('الجرعة')}\n🕒 الوقت: {now}"
        bot.send_message(user_id, text)

        # Try Azure TTS -> send voice note
        if AZURE_TTS_KEY and AZURE_TTS_REGION:
            try:
                voice_path = generate_azure_tts_audio(text, user_id, med_id)
                if voice_path and Path(voice_path).exists():
                    with open(voice_path, "rb") as vf:
                        bot.send_voice(user_id, vf)
                    # cleanup file
                    try:
                        os.remove(voice_path)
                    except:
                        pass
            except Exception:
                # log but don't crash
                print("Azure TTS send failed:", traceback.format_exc())
    except Exception:
        print("send_reminder error:", traceback.format_exc())

def schedule_med_jobs(user_id: str, med: dict):
    # remove previous jobs for med
    remove_med_jobs(user_id, med)
    for idx, hhmm in enumerate(med.get("الأوقات", [])):
        try:
            hh, mm = map(int, hhmm.split(":"))
        except Exception:
            print(f"invalid time {hhmm} for med {med.get('اسم')}")
            continue
        raw = f"{user_id}__{med['id']}__{hhmm.replace(':','')}__{idx}"
        jid = sanitize_job_id(raw)
        job_func = partial(send_reminder, int(user_id), med['id'])
        scheduler.add_job(func=job_func, trigger="cron", hour=hh, minute=mm, id=jid, replace_existing=True, misfire_grace_time=60)
        print(f"Scheduled {jid} at {hhmm} for user {user_id}")

def remove_med_jobs(user_id: str, med: dict):
    for idx, hhmm in enumerate(med.get("الأوقات", [])):
        raw = f"{user_id}__{med['id']}__{hhmm.replace(':','')}__{idx}"
        jid = sanitize_job_id(raw)
        try:
            scheduler.remove_job(jid)
        except Exception:
            pass

def reschedule_all():
    # remove our jobs
    try:
        for job in list(scheduler.get_jobs()):
            if "__" in job.id:
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass
    except Exception:
        pass
    # add from data
    for uid, u in data.items():
        for med in u.get("medicines", []):
            schedule_med_jobs(uid, med)

# -----------------------
# Azure TTS (optional)
# -----------------------
def generate_azure_tts_audio(text: str, user_id: int, med_id: str) -> str:
    """
    Generate an mp3 via Azure TTS and return local filepath.
    Requires AZURE_TTS_KEY and AZURE_TTS_REGION env vars.
    """
    if not (AZURE_TTS_KEY and AZURE_TTS_REGION):
        return None
    try:
        token_url = f"https://{AZURE_TTS_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {"Ocp-Apim-Subscription-Key": AZURE_TTS_KEY}
        r = requests.post(token_url, headers=headers, timeout=10)
        if r.status_code != 200:
            print("Azure token failed", r.status_code, r.text)
            return None
        access_token = r.text

        tts_url = f"https://{AZURE_TTS_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        ssml = f"""
            <speak version='1.0' xml:lang='ar-EG'>
                <voice xml:lang='ar-EG' xml:gender='Female' name='ar-EG-SalmaNeural'>
                    {escape_for_ssml(text)}
                </voice>
            </speak>
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",  # small wav
            "User-Agent": "medibot"
        }
        rr = requests.post(tts_url, headers=headers, data=ssml.encode("utf-8"), timeout=30)
        if rr.status_code not in (200,201):
            print("Azure TTS failed", rr.status_code, rr.text[:200])
            return None
        # save wav to temp file
        fname = f"/tmp/tts_{user_id}_{med_id}_{uuid.uuid4().hex}.wav"
        with open(fname, "wb") as f:
            f.write(rr.content)
        return fname
    except Exception:
        print("Azure TTS exception:", traceback.format_exc())
        return None

def escape_for_ssml(s: str) -> str:
    # minimal escaping
    return s.replace("&", "&amp;").replace("<","&lt;").replace(">","&gt;")

# -----------------------
# Keyboards & UI
# -----------------------
def main_control_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("أدويتي", "💳 الباقات")
    kb.row("🔙 الرجوع إلى القائمة السابقة")
    return kb

def mymeds_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📋 عرض الأدوية", "➕ إضافة دواء")
    kb.row("✏️ تعديل دواء", "🗑️ حذف دواء")
    kb.row("🔙 رجوع")
    return kb

def times_count_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("1", "2", "3", "4")
    return kb

def period_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("صباحًا", "مساءً")
    return kb

def payment_buttons_for_country(country_code: str):
    ik = types.InlineKeyboardMarkup()
    if country_code == "EG":
        ik.add(types.InlineKeyboardButton("خطة فردية - 97 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5615069"))
        ik.add(types.InlineKeyboardButton("خطة عائلية - 190 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5594819"))
    elif country_code == "SA":
        ik.add(types.InlineKeyboardButton("خطة فردية - 59 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763844"))
        ik.add(types.InlineKeyboardButton("خطة عائلية - 89 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763828"))
    else:
        ik.add(types.InlineKeyboardButton("Individual Plan - 9 USD", url="https://example.com"))
        ik.add(types.InlineKeyboardButton("Family Plan - 15 USD", url="https://example.com"))
    # add confirm button (to click after paying)
    ik.add(types.InlineKeyboardButton("✅ لقد دفعت — تحقق", callback_data="paid_confirm"))
    return ik

# -----------------------
# Helpers
# -----------------------
def ensure_user(uid: str):
    if uid not in data:
        data[uid] = {"step": None, "medicines": [], "paid": False}
        save_data()

# -----------------------
# Bot handlers (sequential state machine)
# -----------------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid = str(m.from_user.id)
    ensure_user(uid)
    data[uid]["step"] = "get_name"
    save_data()
    bot.send_message(uid, "مرحبًا 👋\nأدخل اسمك الكامل:")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = str(call.from_user.id)
    ensure_user(uid)
    # handle payment confirm
    if call.data == "paid_confirm":
        data[uid]["paid"] = True
        save_data()
        bot.answer_callback_query(call.id, "✅ تم تأكيد الدفع (يتم التحقق لاحقًا).")
        bot.send_message(uid, "شكرًا! تم التحقق مؤقتًا من الدفع. الوصول إلى لوحة التحكم مفعل الآن.", reply_markup=main_control_keyboard())
        return

    bot.answer_callback_query(call.id, "تم الضغط: " + str(call.data))

@bot.message_handler(func=lambda m: True)
def state_machine(m):
    uid = str(m.from_user.id)
    text = (m.text or "").strip()
    ensure_user(uid)
    u = data[uid]
    step = u.get("step")

    # If user uses keyboard main control quick button "أدويتي" or "💳 الباقات"
    if text == "أدويتي":
        # require payment
        if not u.get("paid"):
            bot.send_message(uid, "يجب إتمام الدفع أولاً للوصول إلى أدويتي. اختر باقة:", reply_markup=payment_buttons_for_country(u.get("country","DEFAULT")))
            u["step"] = "awaiting_payment"
            save_data()
            return
        u["step"] = "in_mymeds"
        save_data()
        bot.send_message(uid, "لوحة أدوِيتي:", reply_markup=mymeds_keyboard())
        return

    if text == "💳 الباقات":
        bot.send_message(uid, "اختر باقتك:", reply_markup=types.ReplyKeyboardRemove())
        bot.send_message(uid, "روابط الدفع:", reply_markup=payment_buttons_for_country(u.get("country","DEFAULT")))
        u["step"] = "awaiting_payment"
        save_data()
        return

    if text == "🔙 الرجوع إلى القائمة السابقة" or text == "🔙 رجوع" or text == "رجوع":
        # return to main control
        u["step"] = "menu"
        save_data()
        bot.send_message(uid, "تم الرجوع للقائمة الرئيسية.", reply_markup=main_control_keyboard())
        return

    # Registration flow steps
    if step == "get_name":
        u["name"] = text
        u["step"] = "get_phone"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("أرسل رقم مع كود الدولة (مثال +20XXXXXXXXX)")
        bot.send_message(uid, "حسنًا. الآن أرسل رقم هاتفك مع رمز الدولة (مثال: +20XXXXXXXXX):", reply_markup=types.ReplyKeyboardRemove())
        return

    if step == "get_phone":
        # minimal validation
        if not text.startswith("+") or len(text) < 7:
            bot.send_message(uid, "الرجاء إدخال رقم هاتف صحيح مع رمز الدولة مثل: +201XXXXXXXXX")
            return
        u["phone"] = text
        u["step"] = "get_age"
        save_data()
        bot.send_message(uid, "أدخل عمرك (أرقام فقط):")
        return

    if step == "get_age":
        if not text.isdigit():
            bot.send_message(uid, "من فضلك أدخل رقم صحيح للسن.")
            return
        u["age"] = int(text)
        u["step"] = "get_email"
        save_data()
        bot.send_message(uid, "أدخل بريدك الإلكتروني:")
        return

    if step == "get_email":
        # minimal email check
        if "@" not in text or "." not in text:
            bot.send_message(uid, "من فضلك أدخل بريد إلكتروني صالح.")
            return
        u["email"] = text
        u["step"] = "choose_country"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("مصر 🇪🇬", "السعودية 🇸🇦", "أخرى 🌍")
        bot.send_message(uid, "اختر دولتك:", reply_markup=kb)
        return

    if step == "choose_country":
        if "مصر" in text:
            u["country"] = "EG"
        elif "سعودي" in text or "السعودية" in text:
            u["country"] = "SA"
        else:
            u["country"] = "DEFAULT"
        u["step"] = "post_signup"
        save_data()
        # send payment options immediately (per your flow)
        bot.send_message(uid, f"شكرًا {u.get('name')}! اختر باقتك للدفع:", reply_markup=payment_buttons_for_country(u.get("country")))
        return

    # awaiting payment (user clicked link externally)
    if step == "awaiting_payment":
        # allow user to click confirmation button via inline keyboard; also accept text "تم الدفع"
        if text in {"تم الدفع", "دفعت", "paid", "تم"}:
            u["paid"] = True
            u["step"] = "menu"
            save_data()
            bot.send_message(uid, "✅ تم وضع علامة الدفع مؤقتًا. إذا كنت تريد، اضغط تأكيد الدفع في زر الرابط.\nتم تفعيل لوحة التحكم:", reply_markup=main_control_keyboard())
            return
        else:
            bot.send_message(uid, "اضغط على رابط الدفع أو اضغط زر '✅ لقد دفعت — تحقق' بعد إتمام الدفع.")
            return

    # Post signup default menu (after payment or if not required)
    if step in (None, "post_signup", "menu"):
        # show main control keyboard
        u["step"] = "menu"
        save_data()
        bot.send_message(uid, f"مرحبًا {u.get('name','')} — هذه لوحة التحكم الرئيسية:", reply_markup=main_control_keyboard())
        return

    # ----------------------------
    # My meds submenu flows
    # ----------------------------
    if step == "in_mymeds":
        # handled above via "أدويتي" button; keep state here
        u["step"] = "in_mymeds"
        save_data()
        bot.send_message(uid, "لوحة أدوِيتي:", reply_markup=mymeds_keyboard())
        return

    # Add med flow
    if step == "med_name":
        # used when user pressed ➕ إضافة دواء
        u["temp"] = {"اسم": text}
        u["step"] = "med_dose"
        save_data()
        bot.send_message(uid, "أدخل الجرعة (مثال: حبة واحدة):")
        return

    if step == "med_dose":
        u["temp"]["الجرعة"] = text
        u["step"] = "med_times_count"
        save_data()
        bot.send_message(uid, "كم مرة يوميًا؟ اختر 1..4", reply_markup=times_count_keyboard())
        return

    if step == "med_times_count":
        if text not in {"1","2","3","4"}:
            bot.send_message(uid, "اختر رقم من 1 إلى 4 باستخدام الأزرار.")
            return
        cnt = int(text)
        u["temp"]["times_needed"] = cnt
        u["temp"]["times_collected"] = 0
        u["temp"]["الأوقات"] = []
        u["step"] = "med_time_input"
        save_data()
        bot.send_message(uid, f"أدخل وقت الجرعة 1 بصيغة HH:MM (مثال: 08:30):", reply_markup=types.ReplyKeyboardRemove())
        return

    if step == "med_time_input":
        # validate
        try:
            hh, mm = map(int, text.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError()
        except Exception:
            bot.send_message(uid, "صيغة خاطئة. استخدم HH:MM مثل 08:30")
            return
        # ask period
        u["temp"]["current_time_candidate"] = text
        u["step"] = "med_time_period"
        save_data()
        bot.send_message(uid, "اختر الفترة لهذا الوقت:", reply_markup=period_keyboard())
        return

    if step == "med_time_period":
        candidate = u["temp"].get("current_time_candidate")
        if not candidate:
            u["step"] = "menu"
            save_data()
            bot.send_message(uid, "حدث خطأ، الرجاء البدء من جديد.", reply_markup=main_control_keyboard())
            return
        try:
            hh, mm = map(int, candidate.split(":"))
        except:
            bot.send_message(uid, "خطأ في الوقت.")
            u["step"] = "menu"
            return
        if text == "صباحًا":
            if hh == 12:
                hh = 0
        elif text == "مساءً":
            if hh < 12:
                hh += 12
        else:
            bot.send_message(uid, "اختيار غير صالح. اختر صباحًا أو مساءً.")
            return
        hhmm24 = f"{hh:02d}:{mm:02d}"
        u["temp"].setdefault("الأوقات", []).append(hhmm24)
        u["temp"]["times_collected"] += 1
        needed = u["temp"]["times_needed"]
        collected = u["temp"]["times_collected"]
        u["temp"].pop("current_time_candidate", None)
        if collected < needed:
            u["step"] = "med_time_input"
            save_data()
            bot.send_message(uid, f"✅ حفظ الوقت {hhmm24}. الآن أرسل الوقت رقم {collected+1}:")
            return
        else:
            # finalize med
            med = {
                "id": str(int(time.time()*1000)),
                "اسم": u["temp"]["اسم"],
                "الجرعة": u["temp"]["الجرعة"],
                "الأوقات": u["temp"]["الأوقات"]
            }
            u.setdefault("medicines", []).append(med)
            save_data()
            schedule_med_jobs(uid, med)
            u.pop("temp", None)
            u["step"] = "menu"
            save_data()
            bot.send_message(uid, "✅ تم إضافة الدواء وتم جدولة التذكيرات.", reply_markup=main_control_keyboard())
            return

    # View meds
    if step == "view_meds" or text == "📋 عرض الأدوية":
        meds = u.get("medicines", [])
        if not meds:
            bot.send_message(uid, "لا توجد أدوية مسجلة.", reply_markup=mymeds_keyboard())
            u["step"] = "in_mymeds"
            return
        lines = []
        for i,m in enumerate(meds, start=1):
            lines.append(f"{i}. {m.get('اسم')} — {m.get('الجرعة')}\nالأوقات: {', '.join(m.get('الأوقات', []))}")
        bot.send_message(uid, "📋 قائمة أدوِيتي:\n\n" + "\n\n".join(lines), reply_markup=mymeds_keyboard())
        u["step"] = "in_mymeds"
        save_data()
        return

    # user clicked "➕ إضافة دواء" from keyboard
    if text == "➕ إضافة دواء":
        u["step"] = "med_name"
        save_data()
        bot.send_message(uid, "أدخل اسم الدواء:")
        return

    # Edit med flow start
    if text == "✏️ تعديل دواء":
        meds = u.get("medicines", [])
        if not meds:
            bot.send_message(uid, "لا توجد أدوية للتعديل.", reply_markup=mymeds_keyboard())
            return
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for m in meds:
            kb.row(m["اسم"])
        kb.row("🔙 رجوع")
        u["step"] = "choose_edit"
        save_data()
        bot.send_message(uid, "اختر الدواء الذي تريد تعديله:", reply_markup=kb)
        return

    if step == "choose_edit":
        if text == "🔙 رجوع":
            u["step"] = "in_mymeds"
            save_data()
            bot.send_message(uid, "تم الرجوع.", reply_markup=mymeds_keyboard())
            return
        meds = u.get("medicines", [])
        chosen = next((m for m in meds if m["اسم"] == text), None)
        if not chosen:
            bot.send_message(uid, "اختيار غير موجود.")
            return
        u["edit_med_id"] = chosen["id"]
        u["step"] = "edit_field"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("الاسم", "الجرعة")
        kb.row("الأوقات", "🔙 رجوع")
        bot.send_message(uid, "ماذا تريد تعديل؟", reply_markup=kb)
        return

    if step == "edit_field":
        mid = u.get("edit_med_id")
        meds = u.get("medicines", [])
        med = next((m for m in meds if m["id"] == mid), None)
        if not med:
            bot.send_message(uid, "خطأ داخلي: الدواء غير موجود.")
            u["step"] = "menu"
            save_data()
            return
        if text == "الاسم":
            u["step"] = "edit_name"
            save_data()
            bot.send_message(uid, "أدخل الاسم الجديد:")
            return
        if text == "الجرعة":
            u["step"] = "edit_dose"
            save_data()
            bot.send_message(uid, "أدخل الجرعة الجديدة:")
            return
        if text == "الأوقات":
            u["step"] = "edit_times"
            save_data()
            bot.send_message(uid, "أدخل الأوقات الجديدة مفصولة بفواصل مثل:\n08:00,14:30")
            return
        if text == "🔙 رجوع":
            u["step"] = "in_mymeds"
            save_data()
            bot.send_message(uid, "تم الرجوع.", reply_markup=mymeds_keyboard())
            return

    if step == "edit_name":
        mid = u.get("edit_med_id")
        med = next((m for m in u.get("medicines", []) if m["id"] == mid), None)
        if med:
            med["اسم"] = text
            save_data()
            bot.send_message(uid, "تم تعديل الاسم.", reply_markup=mymeds_keyboard())
            u["step"] = "in_mymeds"
            return

    if step == "edit_dose":
        mid = u.get("edit_med_id")
        med = next((m for m in u.get("medicines", []) if m["id"] == mid), None)
        if med:
            med["الجرعة"] = text
            save_data()
            bot.send_message(uid, "تم تعديل الجرعة.", reply_markup=mymeds_keyboard())
            u["step"] = "in_mymeds"
            return

    if step == "edit_times":
        mid = u.get("edit_med_id")
        med = next((m for m in u.get("medicines", []) if m["id"] == mid), None)
        if med:
            arr = [t.strip() for t in text.split(",") if t.strip()]
            med["الأوقات"] = arr
            save_data()
            schedule_med_jobs(uid, med)
            bot.send_message(uid, "تم تعديل الأوقات.", reply_markup=mymeds_keyboard())
            u["step"] = "in_mymeds"
            return

    # Delete flow
    if text == "🗑️ حذف دواء":
        meds = u.get("medicines", [])
        if not meds:
            bot.send_message(uid, "لا توجد أدوية للحذف.", reply_markup=mymeds_keyboard())
            return
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for m in meds:
            kb.row(m["اسم"])
        kb.row("🔙 رجوع")
        u["step"] = "choose_delete"
        save_data()
        bot.send_message(uid, "اختر الدواء للحذف:", reply_markup=kb)
        return

    if step == "choose_delete":
        if text == "🔙 رجوع":
            u["step"] = "in_mymeds"
            save_data()
            bot.send_message(uid, "تم الرجوع.", reply_markup=mymeds_keyboard())
            return
        meds = u.get("medicines", [])
        chosen = next((m for m in meds if m["اسم"] == text), None)
        if not chosen:
            bot.send_message(uid, "الدواء غير موجود.")
            return
        remove_med_jobs(uid, chosen)
        u["medicines"].remove(chosen)
        save_data()
        bot.send_message(uid, "تم حذف الدواء.", reply_markup=mymeds_keyboard())
        u["step"] = "in_mymeds"
        return

    # Fallback: if nothing matched
    bot.send_message(uid, "لم أفهم. استخدم الأزرار الموضحة أو اكتب /start للبدء.", reply_markup=main_control_keyboard())

# -----------------------
# Webhook route for Telegram
# -----------------------
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def receive_update():
    try:
        raw = request.get_data().decode("utf-8")
        if not raw:
            return "OK", 200
        update = telebot.types.Update.de_json(raw)
        bot.process_new_updates([update])
    except Exception:
        print("webhook processing failed:", traceback.format_exc())
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "medibot running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook_route():
    if WEBHOOK_MODE != "webhook":
        return f"WEBHOOK_MODE={WEBHOOK_MODE} (not setting webhook)", 200
    try:
        bot.remove_webhook()
        res = bot.set_webhook(url=WEBHOOK_URL)
        load_data()
        reschedule_all()
        return f"Webhook set: {WEBHOOK_URL} (resp: {res})", 200
    except Exception:
        return f"Failed to set webhook: {traceback.format_exc()}", 500

# -----------------------
# Run modes
# -----------------------
def run_polling():
    print("Starting in POLLING mode")
    load_data()
    reschedule_all()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

def run_webhook():
    print("Starting in WEBHOOK mode")
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    load_data()
    reschedule_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    load_data()
    if WEBHOOK_MODE == "webhook":
        run_webhook()
    else:
        run_polling()
