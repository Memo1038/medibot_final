# medibot_render_json_times_ar.py
# Telegram bot (Webhook) + APScheduler + JSON storage
# Arabic-localized version: all fields and UI elements in Arabic,
# keys for medicines: "اسم", "الجرعة", "الأوقات"

import os
import json
import threading
import traceback
from datetime import datetime
from functools import partial

from flask import Flask, request
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# -----------------------
# Load env
# -----------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")  # e.g. https://yourapp.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not WEBHOOK_URL_BASE:
    raise RuntimeError("WEBHOOK_URL_BASE environment variable is required")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

DATA_FILE = "data.json"
DATA_LOCK = threading.Lock()

# -----------------------
# Initialize
# -----------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# Data structure loaded from JSON
# data = { "<user_id>": {name, country, phone, age, email, step, medicines: [ {id,اسم,الجرعة,الأوقات: ["HH:MM", ...]} ], temp_flow: {...} } }
data = {}

# -----------------------
# JSON load/save
# -----------------------
def load_data():
    global data
    try:
        if os.path.exists(DATA_FILE):
            with DATA_LOCK:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
        else:
            data = {}
    except Exception:
        print("Failed to load data.json:", traceback.format_exc())
        data = {}

def save_data():
    try:
        with DATA_LOCK:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        print("Failed to save data.json:", traceback.format_exc())

# -----------------------
# Helpers: job id / schedulers
# -----------------------
def sanitize_job_id(raw: str) -> str:
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in raw)

def schedule_med_jobs(user_id: str, med: dict):
    """
    Schedule APScheduler cron jobs for each time in med['الأوقات'].
    Each job runs daily at specified hour:minute.
    Job id: user__medid__HHMM__idx
    """
    try:
        # remove previous jobs for this med first
        remove_med_jobs(user_id, med)
        for idx, hhmm in enumerate(med.get("الأوقات", [])):
            try:
                hh, mm = map(int, hhmm.split(":"))
            except Exception:
                print(f"Invalid time {hhmm} for med {med.get('اسم')}")
                continue
            raw = f"{user_id}__{med['id']}__{hhmm.replace(':','')}__{idx}"
            job_id = sanitize_job_id(raw)
            # partial to pass med id and user id
            job_func = partial(send_reminder, int(user_id), med['id'])
            scheduler.add_job(
                func=job_func,
                trigger="cron",
                hour=hh,
                minute=mm,
                id=job_id,
                replace_existing=True,
                misfire_grace_time=60
            )
            print(f"Scheduled job {job_id} for user {user_id} med {med.get('اسم')} at {hhmm}")
    except Exception:
        print("Error scheduling med jobs:", traceback.format_exc())

def remove_med_jobs(user_id: str, med: dict):
    for idx, hhmm in enumerate(med.get("الأوقات", [])):
        raw = f"{user_id}__{med['id']}__{hhmm.replace(':','')}__{idx}"
        job_id = sanitize_job_id(raw)
        try:
            scheduler.remove_job(job_id)
            print(f"Removed job {job_id}")
        except Exception:
            pass

def reschedule_all():
    # remove existing app jobs
    try:
        for job in list(scheduler.get_jobs()):
            if "__" in job.id:
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass
    except Exception:
        print("Error clearing jobs:", traceback.format_exc())

    # add from data
    for uid, u in data.items():
        for med in u.get("medicines", []):
            schedule_med_jobs(uid, med)

# -----------------------
# Reminder sender
# -----------------------
def send_reminder(user_id: int, med_id: str):
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
    except Exception:
        print("Failed to send reminder:", traceback.format_exc())

# -----------------------
# Keyboards (Arabic)
# -----------------------
def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ إضافة دواء", "📋 عرض الأدوية")
    kb.row("✏️ تعديل دواء", "🗑️ حذف دواء")
    kb.row("💰 اختيار الخطة")
    return kb

def times_count_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("1", "2", "3", "4")
    return kb

def period_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("صباحًا", "مساءً")
    return kb

def payment_buttons_keyboard(country):
    kb = types.InlineKeyboardMarkup()
    if country == "EG":
        kb.add(types.InlineKeyboardButton("خطة فردية - 97 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5615069"))
        kb.add(types.InlineKeyboardButton("خطة عائلية - 190 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5594819"))
    else:
        kb.add(types.InlineKeyboardButton("خطة فردية - 59 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763844"))
        kb.add(types.InlineKeyboardButton("خطة عائلية - 89 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763828"))
    return kb

# -----------------------
# Bot handlers / flow
# -----------------------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = str(message.from_user.id)
    if uid not in data:
        data[uid] = {
            "step": "get_name",
            "medicines": []
        }
    else:
        data[uid]["step"] = "get_name"
    save_data()
    bot.send_message(message.chat.id, "مرحباً 👋\nمن فضلك أدخل اسمك الكامل:")

@bot.message_handler(func=lambda m: str(m.from_user.id) in data)
def user_flow(message):
    uid = str(message.from_user.id)
    u = data[uid]
    step = u.get("step", "main_menu")
    text = message.text.strip() if message.text else ""

    # Registration steps
    if step == "get_name":
        u["name"] = text
        u["step"] = "get_country"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("مصر 🇪🇬", "السعودية 🇸🇦", "أخرى 🌍")
        bot.send_message(message.chat.id, "اختر دولتك:", reply_markup=kb)
        return

    if step == "get_country":
        if "مصر" in text:
            u["country"] = "EG"
        elif "سعودية" in text:
            u["country"] = "SA"
        else:
            u["country"] = "DEFAULT"
        u["step"] = "get_phone"
        save_data()
        bot.send_message(message.chat.id, "أدخل رقم جوالك مع كود الدولة (+20 أو +966 ...):")
        return

    if step == "get_phone":
        u["phone"] = text
        u["step"] = "get_age"
        save_data()
        bot.send_message(message.chat.id, "أدخل عمرك:")
        return

    if step == "get_age":
        if not text.isdigit():
            bot.send_message(message.chat.id, "من فضلك أدخل رقم صحيح للسن.")
            return
        u["age"] = int(text)
        u["step"] = "get_email"
        save_data()
        bot.send_message(message.chat.id, "أدخل بريدك الإلكتروني:")
        return

    if step == "get_email":
        u["email"] = text
        u["step"] = "choose_plan"
        save_data()
        bot.send_message(message.chat.id, "شكراً! الآن اختر خطتك:", reply_markup=payment_buttons_keyboard(u.get("country","DEFAULT")))
        return

    if step == "choose_plan":
        u["step"] = "main_menu"
        save_data()
        bot.send_message(message.chat.id, "بعد الدفع، اضغط على أي زر للوصول إلى القائمة الرئيسية:", reply_markup=main_menu_keyboard())
        return

    # Main menu
    if step == "main_menu":
        if text == "➕ إضافة دواء":
            u["step"] = "adding_medicine_name"
            save_data()
            bot.send_message(message.chat.id, "أدخل اسم الدواء الذي تريد إضافته:")
            return
        if text == "📋 عرض الأدوية":
            meds = u.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لم تقم بإضافة أي دواء بعد.", reply_markup=main_menu_keyboard())
                return
            lines = []
            for i, m in enumerate(meds, start=1):
                times_text = ", ".join(m.get("الأوقات", [])) if m.get("الأوقات") else "لم يتم تحديد أوقات"
                lines.append(f"{i}. {m.get('اسم')} — {m.get('الجرعة')}\nالأوقات: {times_text}")
            bot.send_message(message.chat.id, "قائمة الأدوية:\n\n" + "\n\n".join(lines), reply_markup=main_menu_keyboard())
            return
        if text == "✏️ تعديل دواء":
            meds = u.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لا يوجد أدوية لتعديلها.", reply_markup=main_menu_keyboard())
                return
            u["step"] = "editing_medicine"
            save_data()
            lines = [f"{i+1}. {m['اسم']}" for i, m in enumerate(meds)]
            bot.send_message(message.chat.id, "أرسل رقم الدواء الذي تريد تعديله:\n" + "\n".join(lines))
            return
        if text == "🗑️ حذف دواء":
            meds = u.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لا يوجد أدوية لحذفها.", reply_markup=main_menu_keyboard())
                return
            u["step"] = "deleting_medicine"
            save_data()
            lines = [f"{i+1}. {m['اسم']}" for i, m in enumerate(meds)]
            bot.send_message(message.chat.id, "أرسل رقم الدواء الذي تريد حذفه:\n" + "\n".join(lines))
            return
        if text == "💰 اختيار الخطة":
            bot.send_message(message.chat.id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(u.get("country","DEFAULT")))
            return
        # Unknown input -> show menu
        bot.send_message(message.chat.id, "اختر من القائمة:", reply_markup=main_menu_keyboard())
        return

    # Add medicine flow (Arabic fields)
    if step == "adding_medicine_name":
        med_name = text
        u["temp_med"] = {
            "id": f"med{int(datetime.utcnow().timestamp() * 1000)}",
            "اسم": med_name,
            "الجرعة": "",
            "الأوقات": []
        }
        u["step"] = "adding_medicine_dosage"
        save_data()
        bot.send_message(message.chat.id, f"أدخل الجرعة للدواء '{med_name}' (مثال: 1 قرص / 5 مل):")
        return

    if step == "adding_medicine_dosage":
        dosage = text
        u["temp_med"]["الجرعة"] = dosage
        u["step"] = "adding_medicine_times_count"
        save_data()
        bot.send_message(message.chat.id, "كم مرة يوميًا تأخذ هذا الدواء؟ اختر 1 إلى 4:", reply_markup=times_count_keyboard())
        return

    if step == "adding_medicine_times_count":
        if text not in {"1","2","3","4"}:
            bot.send_message(message.chat.id, "اختر عدد صحيح من 1 إلى 4 باستخدام الأزرار.")
            return
        count = int(text)
        u["temp_med"]["times_needed"] = count
        u["temp_med"]["times_collected"] = 0
        u["step"] = "adding_medicine_time_input"
        save_data()
        bot.send_message(message.chat.id, f"أدخل وقت الجرعة 1 بصيغة HH:MM (مثال: 08:30):")
        return

    if step == "adding_medicine_time_input":
        # validate HH:MM
        try:
            hh, mm = map(int, text.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError()
        except Exception:
            bot.send_message(message.chat.id, "صيغة وقت خاطئة. استخدم HH:MM مثل 08:30")
            return
        # save raw and ask for period choice to convert if user entered 12-hour format
        u["temp_med"].setdefault("current_time_candidate", {})
        u["temp_med"]["current_time_candidate"]["hhmm"] = text
        u["step"] = "adding_medicine_time_period"
        save_data()
        bot.send_message(message.chat.id, "اختر الفترة لهذا الوقت:", reply_markup=period_keyboard())
        return

    if step == "adding_medicine_time_period":
        period = text
        candidate = u["temp_med"].get("current_time_candidate", {})
        hhmm = candidate.get("hhmm")
        if not hhmm:
            # unexpected
            u["step"] = "main_menu"
            save_data()
            bot.send_message(message.chat.id, "حدث خطأ. الرجاء البدء من جديد.", reply_markup=main_menu_keyboard())
            return
        try:
            hh, mm = map(int, hhmm.split(":"))
        except Exception:
            bot.send_message(message.chat.id, "خطأ في وقت المرشح.")
            return

        # Convert based on period selection:
        if period == "صباحًا":
            if hh == 12:
                hh = 0
        elif period == "مساءً":
            if hh < 12:
                hh = hh + 12
        else:
            bot.send_message(message.chat.id, "اختيار غير صالح. اختر صباحًا أو مساءً.")
            return

        hhmm24 = f"{hh:02d}:{mm:02d}"
        u["temp_med"].setdefault("الأوقات", []).append(hhmm24)
        u["temp_med"]["times_collected"] = u["temp_med"].get("times_collected", 0) + 1
        collected = u["temp_med"]["times_collected"]
        needed = u["temp_med"]["times_needed"]
        # cleanup candidate
        u["temp_med"].pop("current_time_candidate", None)
        save_data()

        if collected < needed:
            u["step"] = "adding_medicine_time_input"
            save_data()
            bot.send_message(message.chat.id, f"✅ تم حفظ الوقت {hhmm24}.\nأدخل وقت الجرعة {collected+1} بصيغة HH:MM:")
            return
        else:
            # finalize med
            med = {
                "id": u["temp_med"]["id"],
                "اسم": u["temp_med"]["اسم"],
                "الجرعة": u["temp_med"]["الجرعة"],
                "الأوقات": u["temp_med"].get("الأوقات", [])
            }
            u.setdefault("medicines", []).append(med)
            # schedule jobs
            schedule_med_jobs(uid, med)
            # remove temp
            u.pop("temp_med", None)
            u["step"] = "main_menu"
            save_data()
            bot.send_message(message.chat.id, "✅ تم إضافة الدواء مع الأوقات اليومية! ستحصل على تذكيرات يومية في الأوقات المدخلة.", reply_markup=main_menu_keyboard())
            return

    # Edit medicine flow
    if step == "editing_medicine":
        if not text.isdigit():
            bot.send_message(message.chat.id, "أدخل رقم الدواء من القائمة.")
            return
        idx = int(text) - 1
        meds = u.get("medicines", [])
        if idx < 0 or idx >= len(meds):
            bot.send_message(message.chat.id, "الرقم غير صحيح.")
            return
        u["edit_index"] = idx
        u["step"] = "editing_medicine_field"
        save_data()
        bot.send_message(message.chat.id, "ماذا تريد تعديل؟ اكتب: الاسم / الجرعة / الأوقات")
        return

    if step == "editing_medicine_field":
        field = text.strip().lower()
        # normalize Arabic inputs
        if field in {"الاسم", "اسم"}:
            chosen = "اسم"
        elif field in {"الجرعة", "جرعة"}:
            chosen = "الجرعة"
        elif field in {"الأوقات", "اوقات", "الأوقات " ,"أوقات"}:
            chosen = "الأوقات"
        else:
            bot.send_message(message.chat.id, "خيار غير صحيح. اكتب: الاسم / الجرعة / الأوقات")
            return
        u["edit_field"] = chosen
        if chosen == "اسم":
            u["step"] = "editing_medicine_name"
            save_data()
            bot.send_message(message.chat.id, "أدخل الاسم الجديد للدواء:")
            return
        if chosen == "الجرعة":
            u["step"] = "editing_medicine_dosage"
            save_data()
            bot.send_message(message.chat.id, "أدخل الجرعة الجديدة للدواء:")
            return
        if chosen == "الأوقات":
            # ask how many times now (similar to add flow)
            u["step"] = "editing_medicine_times_count"
            save_data()
            bot.send_message(message.chat.id, "كم مرة يوميًا الآن؟ اختر 1 إلى 4:", reply_markup=times_count_keyboard())
            return

    if step == "editing_medicine_name":
        new_name = text
        idx = u.pop("edit_index")
        med = u["medicines"][idx]
        med["اسم"] = new_name
        save_data()
        u["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم تعديل الاسم إلى: {new_name}", reply_markup=main_menu_keyboard())
        return

    if step == "editing_medicine_dosage":
        new_dosage = text
        idx = u.pop("edit_index")
        med = u["medicines"][idx]
        med["الجرعة"] = new_dosage
        save_data()
        u["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم تعديل الجرعة إلى: {new_dosage}", reply_markup=main_menu_keyboard())
        return

    # editing times: similar to add flow, but overwrite existing med times
    if step == "editing_medicine_times_count":
        if text not in {"1","2","3","4"}:
            bot.send_message(message.chat.id, "اختر عدد صحيح من 1 إلى 4 باستخدام الأزرار.")
            return
        count = int(text)
        u["temp_edit"] = {
            "times_needed": count,
            "times_collected": 0,
            "الأوقات": []
        }
        u["step"] = "editing_medicine_time_input"
        save_data()
        bot.send_message(message.chat.id, "أدخل وقت الجرعة 1 بصيغة HH:MM (مثال: 08:30):")
        return

    if step == "editing_medicine_time_input":
        try:
            hh, mm = map(int, text.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError()
        except Exception:
            bot.send_message(message.chat.id, "صيغة وقت خاطئة. استخدم HH:MM مثل 08:30")
            return
        u["temp_edit"]["current_time_candidate"] = {"hhmm": text}
        u["step"] = "editing_medicine_time_period"
        save_data()
        bot.send_message(message.chat.id, "اختر الفترة لهذا الوقت:", reply_markup=period_keyboard())
        return

    if step == "editing_medicine_time_period":
        period = text
        cand = u["temp_edit"].get("current_time_candidate", {})
        hhmm = cand.get("hhmm")
        if not hhmm:
            u["step"] = "main_menu"
            save_data()
            bot.send_message(message.chat.id, "حدث خطأ. الرجاء البدء من جديد.", reply_markup=main_menu_keyboard())
            return
        hh, mm = map(int, hhmm.split(":"))
        if period == "صباحًا":
            if hh == 12:
                hh = 0
        elif period == "مساءً":
            if hh < 12:
                hh += 12
        else:
            bot.send_message(message.chat.id, "اختيار غير صالح. اختر صباحًا أو مساءً.")
            return
        hhmm24 = f"{hh:02d}:{mm:02d}"
        u["temp_edit"].setdefault("الأوقات", []).append(hhmm24)
        u["temp_edit"]["times_collected"] = u["temp_edit"].get("times_collected",0) + 1
        collected = u["temp_edit"]["times_collected"]
        needed = u["temp_edit"]["times_needed"]
        u["temp_edit"].pop("current_time_candidate", None)
        save_data()
        if collected < needed:
            u["step"] = "editing_medicine_time_input"
            save_data()
            bot.send_message(message.chat.id, f"✅ تم حفظ الوقت {hhmm24}.\nأدخل وقت الجرعة {collected+1} بصيغة HH:MM:")
            return
        else:
            # finalize edit
            idx = u.pop("edit_index")
            med = u["medicines"][idx]
            # remove existing jobs
            remove_med_jobs(uid, med)
            med["الأوقات"] = u["temp_edit"].get("الأوقات", [])
            # schedule new
            schedule_med_jobs(uid, med)
            u.pop("temp_edit", None)
            u["step"] = "main_menu"
            save_data()
            bot.send_message(message.chat.id, "✅ تم تحديث أوقات الدواء!", reply_markup=main_menu_keyboard())
            return

    # Delete medicine
    if step == "deleting_medicine":
        if not text.isdigit():
            bot.send_message(message.chat.id, "أدخل رقم الدواء من القائمة.")
            return
        idx = int(text) - 1
        meds = u.get("medicines", [])
        if idx < 0 or idx >= len(meds):
            bot.send_message(message.chat.id, "الرقم غير صحيح.")
            return
        med = meds.pop(idx)
        remove_med_jobs(uid, med)
        save_data()
        u["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم حذف الدواء: {med.get('اسم')}", reply_markup=main_menu_keyboard())
        return

    # Fallback: reset to main menu
    u["step"] = "main_menu"
    save_data()
    bot.send_message(message.chat.id, "اختر من القائمة:", reply_markup=main_menu_keyboard())

# -----------------------
# Webhook routes
# -----------------------
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception:
        print("Failed to process update:", traceback.format_exc())
    return "OK", 200

@app.route("/", methods=["GET"])
def set_webhook():
    try:
        bot.remove_webhook()
        set_resp = bot.set_webhook(url=WEBHOOK_URL)
        # load data & schedule jobs
        load_data()
        reschedule_all()
        return f"Webhook set: {WEBHOOK_URL} (set_webhook returned {set_resp})", 200
    except Exception:
        return f"Failed to set webhook: {traceback.format_exc()}", 500

# -----------------------
# Startup
# -----------------------
if __name__ == "__main__":
    load_data()
    reschedule_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
