# medibot_final_secure.py - Final working version for Render + Telegram Webhook + Payment links

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

# -------------------------------
# PAYMENT LINKS AND COUNTRY LOGIC
# -------------------------------
PAYMENT_LINKS = {
    "EG": {    # Egypt
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5615069",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5594819"
    },
    "SA": {    # Saudi Arabia / Gulf
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5763844",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5763828"
    },
    "DEFAULT": {  # Rest of the world
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5763844",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5763828"
    }
}

def detect_country(phone):
    phone = phone.lstrip("+")
    if phone.startswith("20"):
        return "EG"
    if phone.startswith(("966", "971", "965", "973", "968")):
        return "SA"
    return "DEFAULT"

# -------------------------------
# TELEGRAM HANDLERS
# -------------------------------

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "مرحباً 👋\nمن فضلك أرسل رقم هاتفك مع كود الدولة.\nمثال:\n+201234567890\n+966512345678")

@bot.message_handler(func=lambda m: True)
def handle_phone(message):
    phone = message.text.strip()
    if not phone.startswith("+") and not phone[0].isdigit():
        bot.reply_to(message, "❌ من فضلك أرسل رقم هاتف صحيح (يجب أن يبدأ بعلامة + أو رقم).")
        return

    country = detect_country(phone)
    links = PAYMENT_LINKS.get(country, PAYMENT_LINKS["DEFAULT"])

    if country == "EG":
        price_text = "🇪🇬 الأسعار بالجنيه المصري:"
        ind_price = "97 جنيه"
        fam_price = "190 جنيه"
    else:
        price_text = "🇸🇦 الأسعار بالريال السعودي:"
        ind_price = "59 ريال"
        fam_price = "89 ريال"

    reply = f"""
📱 رقمك: {phone}
🌍 دولتك: {country}

{price_text}

✨ الخطة الفردية – {ind_price}
رابط الدفع: {links['individual']}

👨‍👩‍👧 الخطة العائلية – {fam_price}
رابط الدفع: {links['family']}

بعد الدفع أرسل لقطة شاشة لتأكيد الاشتراك.
"""
    bot.reply_to(message, reply)

# -------------------------------
# FLASK WEBHOOK ROUTES
# -------------------------------

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=['GET'])
def index():
    # Remove old webhook and set new one
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    return f"Webhook set: {WEBHOOK_URL}", 200

# -------------------------------
# START SERVER
# -------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
