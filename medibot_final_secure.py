# -*- coding: utf-8 -*-
# MEDIBOT — Arabic Medication Reminder Bot (Fixed Version)
# ----------------------------------------------

import os
import json
import threading
from datetime import datetime
from pathlib import Path
from functools import partial
from flask import Flask, request
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# --------------------------
# Load environment
# --------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")  # Or "poll" for polling
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "webhook")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env")

if WEBHOOK_MODE == "webhook" and not WEBHOOK_URL_BASE:
    raise RuntimeError("WEBHOOK_URL_BASE is missing in webhook mode")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE.rstrip('/')}/{BOT_TOKEN}" if WEBHOOK_URL_BASE else None

# --------------------------
# Files + Thread Lock
# --------------------------
DATA_FILE = "data.json"
DATA_LOCK = threading.Lock()

# --------------------------
# Init bot, flask, scheduler
# --------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

data = {}

# --------------------------
# JSON functions
# --------------------------
def load_data():
    global data
    if Path(DATA_FILE).exists():
        with DATA_LOCK:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    else:
        data = {}

def save_data():
    with DATA_LOCK:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# --------------------------
# Scheduling Helpers
# --------------------------
def sanitize_job_id(s):
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in s)

def send_reminder(user_id, med_id):
    u = data.get(str(user_id))
    if not u:
        return
    med = next((m for m in u["medicines"] if m["id"] == med_id), None)
    if not med:
        return

    now = datetime.now().strftime("%H:%M")
    text = f"⏰ تذكير الدواء\n💊 {med['اسم']}\n📝 الجرعة: {med['الجرعة']}\n🕒 الوقت: {now}"
    bot.send_message(user_id, text)

def schedule_med_jobs(user_id, med):
    remove_med_jobs(user_id, med)
    for idx, hhmm in enumerate(med.get("الأوقات", [])):
        hh, mm = map(int, hhmm.split(":"))
        job_id = sanitize_job_id(f"{user_id}_{med['id']}_{idx}")
        f = partial(send_reminder, int(user_id), med["id"])
        scheduler.add_job(f, "cron", hour=hh, minute=mm, id=job_id, replace_existing=True)

def remove_med_jobs(user_id, med):
    for idx, hhmm in enumerate(med.get("الأوقات", [])):
        job_id = sanitize_job_id(f"{user_id}_{med['id']}_{idx}")
        try:
            scheduler.remove_job(job_id)
        except:
            pass

def reschedule_all():
    for job in scheduler.get_jobs():
        scheduler.remove_job(job.id)
    for uid, u in data.items():
        for med in u["medicines"]:
            schedule_med_jobs(uid, med)

# --------------------------
# Keyboards
# --------------------------
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ إضافة دواء", "📋 عرض الأدوية")
    kb.row("✏️ تعديل دواء", "🗑️ حذف دواء")
    return kb

def times_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("1", "2", "3", "4")
    return kb

def period_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("صباحًا", "مساءً")
    return kb

# --------------------------
# START Command
# --------------------------
@bot.message_handler(commands=["start"])
def start(message):
    uid = str(message.from_user.id)
    data[uid] = {"step": "get_name", "medicines": []}
    save_data()
    bot.send_message(uid, "مرحباً 👋\nمن فضلك أدخل اسمك الكامل:")

# --------------------------
# MAIN BOT FLOW
# --------------------------
@bot.message_handler(func=lambda m: True)
def flow(message):
    uid = str(message.from_user.id)
    txt = message.text.strip()

    if uid not in data:
        bot.send_message(uid, "اكتب /start للبدء من جديد")
        return

    step = data[uid].get("step")

    # ---------------------------------------------------
    # 1) الاسم
    # ---------------------------------------------------
    if step == "get_name":
        data[uid]["name"] = txt
        data[uid]["step"] = "menu"
        save_data()
        bot.send_message(uid, f"أهلاً {txt} 🌟", reply_markup=main_menu())
        return

    # ---------------------------------------------------
    # 2) القائمة
    # ---------------------------------------------------
    if step == "menu":
        if txt == "➕ إضافة دواء":
            data[uid]["new_med"] = {}
            data[uid]["step"] = "med_name"
            save_data()
            bot.send_message(uid, "ما اسم الدواء؟")
            return

        if txt == "📋 عرض الأدوية":
            meds = data[uid]["medicines"]
            if not meds:
                bot.send_message(uid, "لا توجد أدوية.")
                return
            msg = "📋 قائمة الأدوية:\n"
            for m in meds:
                msg += f"- {m['اسم']} ({', '.join(m['الأوقات'])})\n"
            bot.send_message(uid, msg)
            return

        if txt == "✏️ تعديل دواء":
            data[uid]["step"] = "choose_edit_med"
            save_data()
            meds = data[uid]["medicines"]
            if not meds:
                bot.send_message(uid, "لا توجد أدوية للتعديل.")
                data[uid]["step"] = "menu"
                return
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for m in meds:
                kb.row(m["اسم"])
            kb.row("رجوع")
            bot.send_message(uid, "اختر دواء للتعديل:", reply_markup=kb)
            return

        if txt == "🗑️ حذف دواء":
            data[uid]["step"] = "choose_delete_med"
            save_data()
            meds = data[uid]["medicines"]
            if not meds:
                bot.send_message(uid, "لا توجد أدوية للحذف.")
                data[uid]["step"] = "menu"
                return
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for m in meds:
                kb.row(m["اسم"])
            kb.row("رجوع")
            bot.send_message(uid, "اختر دواء للحذف:", reply_markup=kb)
            return

        # أي شيء آخر
        bot.send_message(uid, "اختر من القائمة:", reply_markup=main_menu())
        return

    # ---------------------------------------------------
    # إضافة دواء: الاسم
    # ---------------------------------------------------
    if step == "med_name":
        data[uid]["new_med"]["اسم"] = txt
        data[uid]["step"] = "dose"
        save_data()
        bot.send_message(uid, "ما الجرعة؟ مثال: حبة واحدة")
        return

    # الجرعة
    if step == "dose":
        data[uid]["new_med"]["الجرعة"] = txt
        data[uid]["step"] = "times_count"
        save_data()
        bot.send_message(uid, "كم مرة في اليوم؟", reply_markup=times_keyboard())
        return

    # عدد المرات
    if step == "times_count":
        if txt not in ["1", "2", "3", "4"]:
            bot.send_message(uid, "اختر رقم 1 إلى 4")
            return
        data[uid]["new_med"]["times_left"] = int(txt)
        data[uid]["new_med"]["الأوقات"] = []
        data[uid]["step"] = "enter_time"
        save_data()
        bot.send_message(uid, "أدخل الوقت مثل 08:30 أو 03:15")
        return

    # إدخال وقت
    if step == "enter_time":
        try:
            hh, mm = txt.split(":")
            int(hh); int(mm)
        except:
            bot.send_message(uid, "تنسيق الوقت غير صحيح. مثال: 08:30")
            return

        data[uid]["new_med"]["الأوقات"].append(txt)
        data[uid]["new_med"]["times_left"] -= 1
        save_data()

        if data[uid]["new_med"]["times_left"] == 0:
            med = data[uid]["new_med"]
            med["id"] = str(datetime.now().timestamp()).replace(".", "")
            del med["times_left"]

            data[uid]["medicines"].append(med)
            save_data()

            schedule_med_jobs(uid, med)

            data[uid]["step"] = "menu"
            del data[uid]["new_med"]
            save_data()

            bot.send_message(uid, "تم إضافة الدواء بنجاح ✔️", reply_markup=main_menu())
        else:
            bot.send_message(uid, "أدخل الوقت التالي:")
        return

    # ---------------------------------------------------
    # تعديل دواء
    # ---------------------------------------------------
    if step == "choose_edit_med":
        if txt == "رجوع":
            data[uid]["step"] = "menu"
            bot.send_message(uid, "رجوع للقائمة.", reply_markup=main_menu())
            return
        meds = data[uid]["medicines"]
        chosen = next((m for m in meds if m["اسم"] == txt), None)
        if not chosen:
            bot.send_message(uid, "غير موجود.")
            return
        data[uid]["edit_med"] = chosen
        data[uid]["step"] = "edit_field"
        save_data()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("اسم", "جرعة")
        kb.row("الأوقات")
        kb.row("رجوع")
        bot.send_message(uid, "اختر ما تريد تعديله:", reply_markup=kb)
        return

    if step == "edit_field":
        if txt == "رجوع":
            data[uid]["step"] = "menu"
            bot.send_message(uid, "رجوع للقائمة.", reply_markup=main_menu())
            return
        if txt == "اسم":
            data[uid]["step"] = "edit_name"
            bot.send_message(uid, "أدخل الاسم الجديد:")
            return
        if txt == "جرعة":
            data[uid]["step"] = "edit_dose"
            bot.send_message(uid, "أدخل الجرعة الجديدة:")
            return
        if txt == "الأوقات":
            data[uid]["step"] = "edit_times"
            bot.send_message(uid, "أدخل الأوقات الجديدة مفصولة بفواصل مثل:\n08:00,14:30,18:00")
            return

    if step == "edit_name":
        med = data[uid]["edit_med"]
        med["اسم"] = txt
        save_data()
        bot.send_message(uid, "تم التعديل ✔️", reply_markup=main_menu())
        data[uid]["step"] = "menu"
        return

    if step == "edit_dose":
        med = data[uid]["edit_med"]
        med["الجرعة"] = txt
        save_data()
        bot.send_message(uid, "تم التعديل ✔️", reply_markup=main_menu())
        data[uid]["step"] = "menu"
        return

    if step == "edit_times":
        med = data[uid]["edit_med"]
        arr = [t.strip() for t in txt.split(",")]
        med["الأوقات"] = arr
        save_data()
        schedule_med_jobs(uid, med)
        bot.send_message(uid, "تم تعديل الأوقات ✔️", reply_markup=main_menu())
        data[uid]["step"] = "menu"
        return

    # ---------------------------------------------------
    # حذف دواء
    # ---------------------------------------------------
    if step == "choose_delete_med":
        if txt == "رجوع":
            data[uid]["step"] = "menu"
            bot.send_message(uid, "رجوع للقائمة", reply_markup=main_menu())
            return

        meds = data[uid]["medicines"]
        chosen = next((m for m in meds if m["اسم"] == txt), None)
        if not chosen:
            bot.send_message(uid, "غير موجود.")
            return

        remove_med_jobs(uid, chosen)
        data[uid]["medicines"].remove(chosen)
        save_data()
        bot.send_message(uid, "تم الحذف ✔️", reply_markup=main_menu())
        data[uid]["step"] = "menu"
        return

# --------------------------
# Webhook
# --------------------------
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

# --------------------------
# Run modes
# --------------------------
def run_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    load_data()
    reschedule_all()
    app.run(host="0.0.0.0", port=5000)

def run_polling():
    load_data()
    reschedule_all()
    bot.infinity_polling()

if __name__ == "__main__":
    if WEBHOOK_MODE == "poll":
        run_polling()
    else:
        run_webhook()
