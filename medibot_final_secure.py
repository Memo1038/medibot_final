# medibot_final_secure.py - MediBot Final Version for Render + Telegram Webhook

import os
import telebot
from flask import Flask, request
from dotenv import load_dotenv

# Load environment variables (Render reads them automatically)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing!")

if not WEBHOOK_URL_BASE:
    raise ValueError("WEBHOOK_URL_BASE is missing!")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# Initialize Flask
app = Flask(__name__)

# In-memory storage (replace with DB in production)
users_data = {}  # {chat_id: {name, country, phone, age, email, plan, meds}}

# ------------------------------
# Telegram Handlers
# ------------------------------

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    users_data[chat_id] = {}
    bot.send_message(chat_id, "مرحباً 👋\nالرجاء إدخال الاسم الكامل:")

    bot.register_next_step_handler_by_chat_id(chat_id, ask_country)

def ask_country(message):
    chat_id = message.chat.id
    users_data[chat_id]["name"] = message.text.strip()
    bot.send_message(chat_id, "الرجاء إدخال البلد:")
    bot.register_next_step_handler_by_chat_id(chat_id, ask_phone)

def ask_phone(message):
    chat_id = message.chat.id
    users_data[chat_id]["country"] = message.text.strip()
    bot.send_message(chat_id, "الرجاء إدخال رقم الجوال مع كود الدولة:")
    bot.register_next_step_handler_by_chat_id(chat_id, ask_age)

def ask_age(message):
    chat_id = message.chat.id
    users_data[chat_id]["phone"] = message.text.strip()
    bot.send_message(chat_id, "الرجاء إدخال العمر:")
    bot.register_next_step_handler_by_chat_id(chat_id, ask_email)

def ask_email(message):
    chat_id = message.chat.id
    users_data[chat_id]["age"] = message.text.strip()
    bot.send_message(chat_id, "الرجاء إدخال البريد الإلكتروني:")
    bot.register_next_step_handler_by_chat_id(chat_id, choose_plan)

def choose_plan(message):
    chat_id = message.chat.id
    users_data[chat_id]["email"] = message.text.strip()
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("الخطه الفرديه", "الخطه العائليه (3 اشخاص)")
    bot.send_message(chat_id, "اختر خطتك:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(chat_id, after_payment)

def after_payment(message):
    chat_id = message.chat.id
    users_data[chat_id]["plan"] = message.text.strip()
    bot.send_message(chat_id, f"تم اختيار {message.text}. بعد الدفع، يمكنك إضافة أدويتك.")
    bot.send_message(chat_id, "يمكنك الآن إدارة أدويتك: إضافة / حذف / تعديل.")

# ------------------------------
# Webhook Endpoint
# ------------------------------

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# ------------------------------
# Home Route (sets webhook)
# ------------------------------

@app.route("/", methods=['GET'])
def index():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    return f"Webhook set: {WEBHOOK_URL}", 200

# ------------------------------
# Start server
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
