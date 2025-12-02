# medibot_render_full.py - Telegram Bot with Webhook + medicine reminders

import os
import telebot
from telebot import types
from flask import Flask, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

# -------------------------------
# Load Environment Variables
# -------------------------------
load_dotenv()  # Only needed for local testing

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing!")
if not WEBHOOK_URL_BASE:
    raise ValueError("WEBHOOK_URL_BASE is missing!")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

# -------------------------------
# Initialize Bot, Flask, Scheduler
# -------------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# -------------------------------
# In-memory storage
# -------------------------------
users_data = {}  # {user_id: {name, country, phone, age, email, plan, medicines: []}}

# -------------------------------
# Helper Functions
# -------------------------------
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

def schedule_medicine_reminders(user_id, medicine):
    """
    Schedule reminders for all days and times of a medicine
    """
    for day, times in medicine["schedule"].items():
        for t in times:
            hour, minute = map(int, t.split(":"))
            # APScheduler cron job
            job_id = f"{user_id}_{medicine['name']}_{day}_{t}"
            try:
                scheduler.remove_job(job_id)
            except:
                pass
            scheduler.add_job(
                func=lambda uid=user_id, med_name=medicine['name'], dosage=medicine['dosage']: send_reminder(uid, med_name, dosage),
                trigger="cron",
                day_of_week=day[:3].lower(),  # e.g., 'mon', 'tue'
                hour=hour,
                minute=minute,
                id=job_id,
                replace_existing=True
            )

def send_reminder(user_id, med_name, dosage):
    try:
        bot.send_message(
            user_id,
            f"⏰ تذكير بالدواء:\n💊 {med_name}\n📝 الجرعة: {dosage}"
        )
    except Exception as e:
        print(f"Error sending reminder: {e}")

def remove_medicine_jobs(user_id, medicine):
    """
    Remove all scheduled jobs for a medicine
    """
    for day, times in medicine["schedule"].items():
        for t in times:
            job_id = f"{user_id}_{medicine['name']}_{day}_{t}"
            try:
                scheduler.remove_job(job_id)
            except:
                pass

# -------------------------------
# User Flow Handlers
# -------------------------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    users_data[user_id] = {"step": "get_name", "medicines": []}
    bot.send_message(user_id, "مرحباً 👋\nمن فضلك أدخل اسمك الكامل:")

@bot.message_handler(func=lambda m: m.from_user.id in users_data)
def user_flow(message):
    user_id = message.from_user.id
    user = users_data[user_id]
    step = user.get("step")

    # -------------------------------
    # Registration Steps
    # -------------------------------
    if step == "get_name":
        user["name"] = message.text.strip()
        user["step"] = "get_country"
        bot.send_message(user_id, "اختر دولتك:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("مصر 🇪🇬", "السعودية 🇸🇦", "أخرى 🌍"))
    
    elif step == "get_country":
        country_text = message.text.strip()
        if "مصر" in country_text:
            user["country"] = "EG"
        elif "سعودية" in country_text:
            user["country"] = "SA"
        else:
            user["country"] = "DEFAULT"
        user["step"] = "get_phone"
        bot.send_message(user_id, "أدخل رقم جوالك مع كود الدولة (+20 أو +966 ...):")

    elif step == "get_phone":
        phone = message.text.strip()
        if not phone.startswith("+") and not phone[0].isdigit():
            bot.send_message(user_id, "❌ من فضلك أرسل رقم هاتف صحيح.")
            return
        user["phone"] = phone
        user["step"] = "get_age"
        bot.send_message(user_id, "أدخل عمرك:")

    elif step == "get_age":
        if not message.text.isdigit():
            bot.send_message(user_id, "❌ من فضلك أدخل رقم صحيح للسن.")
            return
        user["age"] = int(message.text)
        user["step"] = "get_email"
        bot.send_message(user_id, "أدخل بريدك الإلكتروني:")

    elif step == "get_email":
        user["email"] = message.text.strip()
        user["step"] = "choose_plan"
        bot.send_message(user_id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))

    elif step == "choose_plan":
        user["step"] = "main_menu"
        bot.send_message(user_id, "بعد الدفع، اضغط على أي زر للوصول إلى القائمة الرئيسية:", reply_markup=main_menu_keyboard())

    # -------------------------------
    # Main Menu
    # -------------------------------
    elif step == "main_menu":
        text = message.text.strip()
        if text == "📝 Add Medicine":
            user["step"] = "adding_medicine_name"
            bot.send_message(user_id, "أدخل اسم الدواء الذي تريد إضافته:")
        elif text == "📋 View Medicines":
            meds = user["medicines"]
            if meds:
                msg = "قائمة الأدوية:\n"
                for i, m in enumerate(meds):
                    schedule_text = "\n".join([f"{d}: {', '.join(times)}" for d, times in m.get("schedule", {}).items()])
                    msg += f"{i+1}. {m['name']} - {m['dosage']}\n{schedule_text}\n\n"
                bot.send_message(user_id, msg, reply_markup=main_menu_keyboard())
            else:
                bot.send_message(user_id, "لم تقم بإضافة أي دواء بعد.", reply_markup=main_menu_keyboard())
        elif text == "🔄 Edit Medicine":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لتعديلها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "editing_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد تعديله:\n" + "\n".join([f"{i+1}. {m['name']}" for i, m in enumerate(meds)]))
        elif text == "❌ Delete Medicine":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لحذفها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "deleting_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد حذفه:\n" + "\n".join([f"{i+1}. {m['name']}" for i, m in enumerate(meds)]))
        elif text == "💰 Choose Plan":
            bot.send_message(user_id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))

    # -------------------------------
    # Add Medicine Flow
    # -------------------------------
    elif step == "adding_medicine_name":
        med_name = message.text.strip()
        user["new_med"] = {"name": med_name}
        user["step"] = "adding_medicine_dosage"
        bot.send_message(user_id, f"أدخل جرعة الدواء {med_name} (مثال: 1 قرص / 5 مل):")

    elif step == "adding_medicine_dosage":
        dosage = message.text.strip()
        user["new_med"]["dosage"] = dosage
        user["step"] = "adding_medicine_days"
        bot.send_message(user_id, "اختر أيام الأسبوع لأخذ الدواء (مثال: Monday, Wednesday, Friday):")

    elif step == "adding_medicine_days":
        days = [d.strip().capitalize() for d in message.text.split(",")]
        user["new_med"]["schedule"] = {day: [] for day in days}
        user["step"] = "adding_medicine_times"
        bot.send_message(user_id, "أدخل أوقات الدواء لكل يوم (HH:MM) مفصولة بفواصل (مثال: 08:30, 20:00):")

    elif step == "adding_medicine_times":
        times = [t.strip() for t in message.text.split(",")]
        for day in user["new_med"]["schedule"]:
            user["new_med"]["schedule"][day] = times
        # Add medicine
        user["medicines"].append(user.pop("new_med"))
        # Schedule reminders
        schedule_medicine_reminders(user_id, user["medicines"][-1])
        user["step"] = "main_menu"
        bot.send_message(user_id, "✅ تم إضافة الدواء مع الجرعة والجدول الزمني!", reply_markup=main_menu_keyboard())

    # -------------------------------
    # Delete Medicine
    # -------------------------------
    elif step == "deleting_medicine":
        index = message.text.strip()
        meds = user["medicines"]
        if not index.isdigit() or int(index) < 1 or int(index) > len(meds):
            bot.send_message(user_id, "❌ الرقم غير صحيح. حاول مرة أخرى.")
            return
        idx = int(index)-1
        med_to_remove = meds.pop(idx)
        remove_medicine_jobs(user_id, med_to_remove)
        user["step"] = "main_menu"
        bot.send_message(user_id, f"❌ تم حذف الدواء: {med_to_remove['name']}", reply_markup=main_menu_keyboard())

# -------------------------------
# Flask Webhook Routes
# -------------------------------
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=['GET'])
def index():
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    return f"Webhook set: {WEBHOOK_URL}/{BOT_TOKEN}", 200

# -------------------------------
# Start Server
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
