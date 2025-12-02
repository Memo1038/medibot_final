# medibot_final_full.py - Full Telegram Bot Flow for Render Webhook Deployment

import os
import telebot
from telebot import types
from flask import Flask, request
from dotenv import load_dotenv

# -------------------------------
# Load Environment Variables
# -------------------------------
load_dotenv()  # Only needed for local testing; Render reads from env vars automatically

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing!")
if not WEBHOOK_URL_BASE:
    raise ValueError("WEBHOOK_URL_BASE is missing!")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

# -------------------------------
# Initialize Bot and Flask
# -------------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# -------------------------------
# In-memory storage for demo purposes (replace with DB in production)
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

# -------------------------------
# Step Handlers
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
            bot.send_message(user_id, "❌ من فضلك أرسل رقم هاتف صحيح (يجب أن يبدأ بعلامة + أو رقم).")
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
        email = message.text.strip()
        user["email"] = email
        user["step"] = "choose_plan"
        bot.send_message(user_id, "شكراً! الآن اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))
    
    elif step == "choose_plan":
        # The plan selection will be done via inline buttons with payment links
        # After payment, user can start adding medicines
        user["step"] = "main_menu"
        bot.send_message(user_id, "بعد الدفع، اضغط على أي زر أدناه للوصول إلى القائمة الرئيسية:", reply_markup=main_menu_keyboard())
    
    elif step == "main_menu":
        text = message.text.strip()
        if text == "📝 Add Medicine":
            user["step"] = "adding_medicine"
            bot.send_message(user_id, "أدخل اسم الدواء الذي تريد إضافته:")
        elif text == "📋 View Medicines":
            meds = user["medicines"]
            if meds:
                bot.send_message(user_id, "قائمة الأدوية:\n" + "\n".join([f"{i+1}. {m}" for i,m in enumerate(meds)]), reply_markup=main_menu_keyboard())
            else:
                bot.send_message(user_id, "لم تقم بإضافة أي دواء بعد.", reply_markup=main_menu_keyboard())
        elif text == "🔄 Edit Medicine":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لتعديلها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "editing_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد تعديله:\n" + "\n".join([f"{i+1}. {m}" for i,m in enumerate(meds)]))
        elif text == "❌ Delete Medicine":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لحذفها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "deleting_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد حذفه:\n" + "\n".join([f"{i+1}. {m}" for i,m in enumerate(meds)]))
        elif text == "💰 Choose Plan":
            bot.send_message(user_id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))
    
    elif step == "adding_medicine":
        med_name = message.text.strip()
        user["medicines"].append(med_name)
        user["step"] = "main_menu"
        bot.send_message(user_id, f"✅ تم إضافة الدواء: {med_name}", reply_markup=main_menu_keyboard())
    
    elif step == "editing_medicine":
        index = message.text.strip()
        meds = user["medicines"]
        if not index.isdigit() or int(index) < 1 or int(index) > len(meds):
            bot.send_message(user_id, "❌ الرقم غير صحيح. حاول مرة أخرى.")
            return
        user["edit_index"] = int(index)-1
        user["step"] = "editing_medicine_name"
        bot.send_message(user_id, f"أرسل الاسم الجديد للدواء {meds[int(index)-1]}:")
    
    elif step == "editing_medicine_name":
        new_name = message.text.strip()
        idx = user.pop("edit_index")
        user["medicines"][idx] = new_name
        user["step"] = "main_menu"
        bot.send_message(user_id, f"✅ تم تعديل الدواء إلى: {new_name}", reply_markup=main_menu_keyboard())
    
    elif step == "deleting_medicine":
        index = message.text.strip()
        meds = user["medicines"]
        if not index.isdigit() or int(index) < 1 or int(index) > len(meds):
            bot.send_message(user_id, "❌ الرقم غير صحيح. حاول مرة أخرى.")
            return
        deleted = meds.pop(int(index)-1)
        user["step"] = "main_menu"
        bot.send_message(user_id, f"❌ تم حذف الدواء: {deleted}", reply_markup=main_menu_keyboard())

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

