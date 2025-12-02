# medibot_render_json.py
# Telegram bot for Render (Webhook) with APScheduler and JSON storage.
# Features:
# - Register user (name, country, phone, age, email)
# - Add medicine: name, dosage, days, times
# - Edit / Delete medicine
# - Persistent storage in data.json
# - APScheduler cron jobs to send reminders at exact times via the running bot instance
# - Webhook setup route (GET /) to set webhook URL
# - Uses environment variables: BOT_TOKEN, WEBHOOK_URL_BASE

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

# -----------------------
# Configuration / Env
# -----------------------
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

# In-memory structure loaded from JSON; format:
# {
#   "<user_id>": {
#       "name": "...",
#       "country": "EG/SA/DEFAULT",
#       "phone": "...",
#       "age": 30,
#       "email": "...",
#       "step": "main_menu" or other,
#       "medicines": [
#           {
#               "id": "<unique>",
#               "name": "...",
#               "dosage": "...",
#               "schedule": {"Monday": ["08:30", "20:00"], ...}
#           }
#       ]
#   }
# }
data = {}

# -----------------------
# Utilities: load/save JSON
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
# Helpers: job id and scheduler logic
# -----------------------
def sanitize_job_id(raw: str) -> str:
    # keep only safe chars
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in raw)

def day_str_to_cron(day_name: str) -> str:
    # APScheduler day_of_week accepts: mon,tue,wed,thu,fri,sat,sun
    mapping = {
        "Mon": "mon", "Monday": "mon",
        "Tue": "tue", "Tues": "tue", "Tuesday": "tue",
        "Wed": "wed", "Wednesday": "wed",
        "Thu": "thu", "Thursday": "thu",
        "Fri": "fri", "Friday": "fri",
        "Sat": "sat", "Saturday": "sat",
        "Sun": "sun", "Sunday": "sun"
    }
    return mapping.get(day_name[:3].capitalize(), None)

def schedule_medicine_jobs(user_id: str, med: dict):
    """
    Create APScheduler cron jobs for every (day, time) pair for a medicine.
    Job id format: <user>__<medid>__<day>__<HHMM>
    """
    try:
        for day, times in med.get("schedule", {}).items():
            cron_day = day_str_to_cron(day)
            if not cron_day:
                print(f"Unknown day name '{day}' for user {user_id}, med {med.get('name')}")
                continue
            for t in times:
                try:
                    hh_mm = t.strip()
                    hour, minute = map(int, hh_mm.split(":"))
                except Exception:
                    print(f"Invalid time format '{t}' for user {user_id}, med {med.get('name')}")
                    continue

                raw_job_id = f"{user_id}__{med['id']}__{day}__{hh_mm.replace(':','')}"
                job_id = sanitize_job_id(raw_job_id)
                # remove existing job if exists
                try:
                    scheduler.remove_job(job_id)
                except Exception:
                    pass

                # Use partial to capture med properties safely
                job_func = partial(send_reminder, int(user_id), med['id'])
                scheduler.add_job(
                    func=job_func,
                    trigger="cron",
                    day_of_week=cron_day,
                    hour=hour,
                    minute=minute,
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=60  # if missed by <60s, still run
                )
                # print debug
                print(f"Scheduled job {job_id} -> user {user_id}, med {med['name']}, {day} {hh_mm}")
    except Exception:
        print("Error scheduling medicine jobs:", traceback.format_exc())

def remove_medicine_jobs(user_id: str, med: dict):
    # Remove all job_ids associated with this med
    for day, times in med.get("schedule", {}).items():
        for t in times:
            raw_job_id = f"{user_id}__{med['id']}__{day}__{t.replace(':','')}"
            job_id = sanitize_job_id(raw_job_id)
            try:
                scheduler.remove_job(job_id)
                print(f"Removed job {job_id}")
            except Exception:
                pass

def reschedule_all():
    # Clear existing scheduler jobs related to our app, then add from data
    # NOTE: We only remove jobs that match our job id naming pattern (contain "__")
    try:
        for job in list(scheduler.get_jobs()):
            if "__" in job.id:
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass
    except Exception:
        print("Error clearing jobs:", traceback.format_exc())

    for uid, u in data.items():
        for med in u.get("medicines", []):
            schedule_medicine_jobs(uid, med)

# -----------------------
# Reminder send function
# -----------------------
def send_reminder(user_id: int, med_id: str):
    try:
        # Look up med by id (in case name/ dosage changed)
        u = data.get(str(user_id))
        if not u:
            return
        med = None
        for m in u.get("medicines", []):
            if m.get("id") == med_id:
                med = m
                break
        if not med:
            return
        text = f"⏰ تذكير بالدواء:\n💊 {med.get('name')}\n📝 الجرعة: {med.get('dosage')}\n" \
               f"🕒 الوقت: {datetime.now().strftime('%H:%M')}"
        bot.send_message(user_id, text)
    except Exception as e:
        print("Failed to send reminder:", e, traceback.format_exc())

# -----------------------
# Keyboards
# -----------------------
def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📝 Add Medicine", "📋 View Medicines")
    kb.row("🔄 Edit Medicine", "❌ Delete Medicine")
    kb.row("💰 Choose Plan")
    return kb

def payment_buttons_keyboard(country):
    kb = types.InlineKeyboardMarkup()
    if country == "EG":
        kb.add(types.InlineKeyboardButton("خطة فردية - 97 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5615069"))
        kb.add(types.InlineKeyboardButton("خطة عائلية - 190 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5594819"))
    else:
        kb.add(types.InlineKeyboardButton("Individual Plan - 59 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763844"))
        kb.add(types.InlineKeyboardButton("Family Plan - 89 SAR", url="https://secure-egypt.paytabs.com/payment/link/140410/5763828"))
    return kb

# -----------------------
# Bot handlers: start + main flow
# -----------------------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = str(message.from_user.id)
    if user_id not in data:
        data[user_id] = {
            "step": "get_name",
            "medicines": []
        }
        save_data()
    else:
        data[user_id]["step"] = "get_name"
        save_data()
    bot.send_message(message.chat.id, "مرحباً 👋\nمن فضلك أدخل اسمك الكامل:")

@bot.message_handler(func=lambda m: str(m.from_user.id) in data)
def user_flow(message):
    user_id = str(message.from_user.id)
    user = data[user_id]
    step = user.get("step", "main_menu")
    text = message.text.strip() if message.text else ""

    # ---------- Registration steps ----------
    if step == "get_name":
        user["name"] = text
        user["step"] = "get_country"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("مصر 🇪🇬", "السعودية 🇸🇦", "أخرى 🌍")
        bot.send_message(message.chat.id, "اختر دولتك:", reply_markup=kb)
        return

    if step == "get_country":
        if "مصر" in text:
            user["country"] = "EG"
        elif "سعودية" in text:
            user["country"] = "SA"
        else:
            user["country"] = "DEFAULT"
        user["step"] = "get_phone"
        save_data()
        bot.send_message(message.chat.id, "أدخل رقم جوالك مع كود الدولة (+20 أو +966 ...):")
        return

    if step == "get_phone":
        phone = text
        if not phone:
            bot.send_message(message.chat.id, "أدخل رقم صحيح.")
            return
        user["phone"] = phone
        user["step"] = "get_age"
        save_data()
        bot.send_message(message.chat.id, "أدخل عمرك:")
        return

    if step == "get_age":
        if not text.isdigit():
            bot.send_message(message.chat.id, "من فضلك أدخل رقم صحيح للسن.")
            return
        user["age"] = int(text)
        user["step"] = "get_email"
        save_data()
        bot.send_message(message.chat.id, "أدخل بريدك الإلكتروني:")
        return

    if step == "get_email":
        user["email"] = text
        user["step"] = "choose_plan"
        save_data()
        bot.send_message(message.chat.id, "شكراً! الآن اختر خطتك:", reply_markup=payment_buttons_keyboard(user.get("country", "DEFAULT")))
        return

    if step == "choose_plan":
        user["step"] = "main_menu"
        save_data()
        bot.send_message(message.chat.id, "بعد الدفع، اضغط على أي زر للوصول إلى القائمة الرئيسية:", reply_markup=main_menu_keyboard())
        return

    # ---------- Main menu ----------
    if step == "main_menu":
        if text == "📝 Add Medicine":
            user["step"] = "adding_medicine_name"
            save_data()
            bot.send_message(message.chat.id, "أدخل اسم الدواء الذي تريد إضافته:")
            return
        if text == "📋 View Medicines":
            meds = user.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لم تقم بإضافة أي دواء بعد.", reply_markup=main_menu_keyboard())
                return
            lines = []
            for i, m in enumerate(meds, start=1):
                schedule_lines = []
                for d, times in m.get("schedule", {}).items():
                    schedule_lines.append(f"{d}: {', '.join(times)}")
                lines.append(f"{i}. {m.get('name')} — {m.get('dosage')}\n" + ("\n".join(schedule_lines) if schedule_lines else ""))
            bot.send_message(message.chat.id, "قائمة الأدوية:\n\n" + "\n\n".join(lines), reply_markup=main_menu_keyboard())
            return
        if text == "🔄 Edit Medicine":
            meds = user.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لا يوجد أدوية لتعديلها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "editing_medicine"
            save_data()
            lines = [f"{i+1}. {m['name']}" for i, m in enumerate(meds)]
            bot.send_message(message.chat.id, "أرسل رقم الدواء الذي تريد تعديله:\n" + "\n".join(lines))
            return
        if text == "❌ Delete Medicine":
            meds = user.get("medicines", [])
            if not meds:
                bot.send_message(message.chat.id, "لا يوجد أدوية لحذفها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "deleting_medicine"
            save_data()
            lines = [f"{i+1}. {m['name']}" for i, m in enumerate(meds)]
            bot.send_message(message.chat.id, "أرسل رقم الدواء الذي تريد حذفه:\n" + "\n".join(lines))
            return
        if text == "💰 Choose Plan":
            bot.send_message(message.chat.id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(user.get("country", "DEFAULT")))
            return
        # If unknown input, show menu
        bot.send_message(message.chat.id, "اختر من القائمة:", reply_markup=main_menu_keyboard())
        return

    # ---------- Add medicine flow ----------
    if step == "adding_medicine_name":
        med_name = text
        user["new_med"] = {
            "id": f"med{int(datetime.utcnow().timestamp() * 1000)}",
            "name": med_name,
            "dosage": "",
            "schedule": {}
        }
        user["step"] = "adding_medicine_dosage"
        save_data()
        bot.send_message(message.chat.id, f"أدخل جرعة الدواء {med_name} (مثال: 1 قرص / 5 مل):")
        return

    if step == "adding_medicine_dosage":
        dosage = text
        user["new_med"]["dosage"] = dosage
        user["step"] = "adding_medicine_days"
        save_data()
        bot.send_message(message.chat.id, "اختر أيام الأسبوع لأخذ الدواء (مثال: Monday, Wednesday, Friday):")
        return

    if step == "adding_medicine_days":
        # allow Arabic or English day names; we will store them capitalized english-like
        raw_days = [d.strip() for d in text.split(",") if d.strip()]
        if not raw_days:
            bot.send_message(message.chat.id, "من فضلك أدخل يوم واحد على الأقل.")
            return
        # normalize simple Arabic weekdays to English short names if needed
        normalized = []
        ar_to_en = {
            "الاثنين": "Monday", "الثلاثاء": "Tuesday", "الاربعاء": "Wednesday", "الأربعاء": "Wednesday",
            "الخميس": "Thursday", "الجمعة": "Friday", "السبت": "Saturday", "الأحد": "Sunday"
        }
        for d in raw_days:
            d_clean = d.capitalize()
            if d_clean in ar_to_en:
                normalized.append(ar_to_en[d_clean])
            else:
                # if user wrote english day like Monday
                normalized.append(d_clean)
        user["new_med"]["schedule"] = {day: [] for day in normalized}
        user["step"] = "adding_medicine_times"
        save_data()
        bot.send_message(message.chat.id, "أدخل أوقات الدواء لكل يوم (HH:MM) مفصولة بفواصل (مثال: 08:30, 20:00):")
        return

    if step == "adding_medicine_times":
        times = [t.strip() for t in text.split(",") if t.strip()]
        if not times:
            bot.send_message(message.chat.id, "من فضلك أدخل وقت واحد على الأقل.")
            return
        # basic validation HH:MM
        for t in times:
            try:
                hh, mm = map(int, t.split(":"))
                assert 0 <= hh < 24 and 0 <= mm < 60
            except Exception:
                bot.send_message(message.chat.id, f"صيغة وقت خاطئة: {t}. استخدم HH:MM مثل 08:30")
                return
        # apply same times to each chosen day
        for day in user["new_med"]["schedule"]:
            user["new_med"]["schedule"][day] = times.copy()
        # finalize
        med = user["new_med"]
        user.setdefault("medicines", []).append(med)
        user.pop("new_med", None)
        user["step"] = "main_menu"
        save_data()
        # schedule jobs for this medicine
        schedule_medicine_jobs(user_id, med)
        bot.send_message(message.chat.id, "✅ تم إضافة الدواء مع الجرعة والجدول الزمني!", reply_markup=main_menu_keyboard())
        return

    # ---------- Edit medicine flow ----------
    if step == "editing_medicine":
        idx_text = text
        meds = user.get("medicines", [])
        if not idx_text.isdigit():
            bot.send_message(message.chat.id, "أدخل رقم الدواء من القائمة.")
            return
        idx = int(idx_text) - 1
        if idx < 0 or idx >= len(meds):
            bot.send_message(message.chat.id, "الرقم غير صحيح.")
            return
        user["edit_index"] = idx
        user["step"] = "editing_medicine_field"
        save_data()
        bot.send_message(message.chat.id, "ماذا تريد تعديل؟ اكتب: name / dosage / schedule")
        return

    if step == "editing_medicine_field":
        field = text.lower()
        user["edit_field"] = field
        if field == "name":
            user["step"] = "editing_medicine_name"
            save_data()
            bot.send_message(message.chat.id, "أدخل الاسم الجديد للدواء:")
            return
        if field == "dosage":
            user["step"] = "editing_medicine_dosage"
            save_data()
            bot.send_message(message.chat.id, "أدخل الجرعة الجديدة للدواء:")
            return
        if field == "schedule":
            user["step"] = "editing_medicine_schedule_days"
            save_data()
            bot.send_message(message.chat.id, "أدخل أيام الأسبوع الجديدة مفصولة بفواصل:")
            return
        bot.send_message(message.chat.id, "خيار غير صحيح. اكتب: name / dosage / schedule")
        return

    if step == "editing_medicine_name":
        new_name = text
        idx = user.pop("edit_index")
        med = user["medicines"][idx]
        med["name"] = new_name
        save_data()
        # update jobs (job ids include med id only, so name change doesn't affect id)
        user["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم تعديل الاسم إلى: {new_name}", reply_markup=main_menu_keyboard())
        return

    if step == "editing_medicine_dosage":
        new_dosage = text
        idx = user.pop("edit_index")
        med = user["medicines"][idx]
        med["dosage"] = new_dosage
        save_data()
        user["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم تعديل الجرعة إلى: {new_dosage}", reply_markup=main_menu_keyboard())
        return

    if step == "editing_medicine_schedule_days":
        raw_days = [d.strip() for d in text.split(",") if d.strip()]
        if not raw_days:
            bot.send_message(message.chat.id, "من فضلك أدخل يوم واحد على الأقل.")
            return
        normalized = []
        ar_to_en = {
            "الاثنين": "Monday", "الثلاثاء": "Tuesday", "الاربعاء": "Wednesday", "الأربعاء": "Wednesday",
            "الخميس": "Thursday", "الجمعة": "Friday", "السبت": "Saturday", "الأحد": "Sunday"
        }
        for d in raw_days:
            d_clean = d.capitalize()
            if d_clean in ar_to_en:
                normalized.append(ar_to_en[d_clean])
            else:
                normalized.append(d_clean)
        idx = user.get("edit_index")
        med = user["medicines"][idx]
        # remove existing jobs for this med before changing schedule
        remove_medicine_jobs(user_id, med)
        med["schedule"] = {day: [] for day in normalized}
        user["step"] = "editing_medicine_schedule_times"
        save_data()
        bot.send_message(message.chat.id, "أدخل أوقات الدواء الجديدة لكل يوم (HH:MM) مفصولة بفواصل:")
        return

    if step == "editing_medicine_schedule_times":
        times = [t.strip() for t in text.split(",") if t.strip()]
        if not times:
            bot.send_message(message.chat.id, "من فضلك أدخل وقت واحد على الأقل.")
            return
        try:
            for t in times:
                hh, mm = map(int, t.split(":"))
                assert 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            bot.send_message(message.chat.id, "صيغة وقت خاطئة. استخدم HH:MM مثل 08:30")
            return
        idx = user.pop("edit_index")
        med = user["medicines"][idx]
        for day in med["schedule"]:
            med["schedule"][day] = times.copy()
        save_data()
        # reschedule jobs for this med
        schedule_medicine_jobs(user_id, med)
        user["step"] = "main_menu"
        bot.send_message(message.chat.id, "✅ تم تحديث جدول الدواء!", reply_markup=main_menu_keyboard())
        return

    # ---------- Delete medicine ----------
    if step == "deleting_medicine":
        idx_text = text
        meds = user.get("medicines", [])
        if not idx_text.isdigit():
            bot.send_message(message.chat.id, "أدخل رقم الدواء من القائمة.")
            return
        idx = int(idx_text) - 1
        if idx < 0 or idx >= len(meds):
            bot.send_message(message.chat.id, "الرقم غير صحيح.")
            return
        med = meds.pop(idx)
        # remove scheduled jobs
        remove_medicine_jobs(user_id, med)
        save_data()
        user["step"] = "main_menu"
        bot.send_message(message.chat.id, f"✅ تم حذف الدواء: {med.get('name')}", reply_markup=main_menu_keyboard())
        return

    # Fallback: show main menu
    user["step"] = "main_menu"
    save_data()
    bot.send_message(message.chat.id, "اختر من القائمة:", reply_markup=main_menu_keyboard())

# -----------------------
# Flask routes for webhook
# -----------------------
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    # Telegram will POST updates here
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception:
        print("Failed to process update:", traceback.format_exc())
    return "OK", 200

@app.route("/", methods=["GET"])
def set_webhook():
    # Called by you to set the webhook to Telegram
    try:
        bot.remove_webhook()
        set_resp = bot.set_webhook(url=f"{WEBHOOK_URL}")
        # reload data and reschedule jobs to ensure persistence after deploy/restart
        load_data()
        reschedule_all()
        return f"Webhook set: {WEBHOOK_URL} (set_webhook returned {set_resp})", 200
    except Exception:
        return f"Failed to set webhook: {traceback.format_exc()}", 500

# -----------------------
# Startup: load data and schedule
# -----------------------
if __name__ == "__main__":
    # load existing data & schedule jobs
    load_data()
    reschedule_all()
    port = int(os.environ.get("PORT", 5000))
    # start Flask app (Render will use this)
    app.run(host="0.0.0.0", port=port)
