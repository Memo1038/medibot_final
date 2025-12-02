# medibot_final_secure.py - Final working version for Render + Telegram Webhook

import os
import telebot
from flask import Flask, request
from dotenv import load_dotenv

# Load env vars (Render reads automatically)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing!")

if not WEBHOOK_URL_BASE:
    raise ValueError("WEBHOOK_URL_BASE is missing!")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

# Init bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# Init Flask app
app = Flask(__name__)

# Main webhook endpoint
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# Home route: also sets webhook!
@app.route("/", methods=['GET'])
def index():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    return f"Webhook set: {WEBHOOK_URL}", 200

# Example command
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "Welcome from MediBot! Bot is working ✔️")

# Start server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
