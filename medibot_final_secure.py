# medibot_final_secure.py - Optimized for Render Webhook Deployment

import os
from dotenv import load_dotenv  # For local testing
import telebot  # pyTelegramBotAPI
from flask import Flask, request  # Webhook server
from apscheduler.schedulers.background import BackgroundScheduler
import requests

# -------------------------------
# Load Environment Variables
# -------------------------------
load_dotenv()  # Only needed for local testing; Render reads from env vars automatically

BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_KEY = os.getenv("AZURE_KEY")
AZURE_REGION = os.getenv("AZURE_REGION")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set. Add it to .env or Render Environment Variables.")

# -------------------------------
# Initialize Telegram Bot
# -------------------------------
bot = telebot.TeleBot(BOT_TOKEN)

# -------------------------------
# Initialize Flask App
# -------------------------------
app = Flask(__name__)

# -------------------------------
# Telegram Webhook Endpoint
# -------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    json_data = request.get_json()
    if json_data:
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
    return "OK", 200

# -------------------------------
# Example Command Handler
# -------------------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome to MediBot! Your medication reminder assistant.")

# -------------------------------
# Example Background Scheduler (optional)
# -------------------------------
scheduler = BackgroundScheduler()
# Example: run every 10 minutes
# scheduler.add_job(lambda: print("Background job running..."), 'interval', minutes=10)
scheduler.start()

# -------------------------------
# Start Flask Server (Render uses PORT)
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
