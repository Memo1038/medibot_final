# medibot_final_secure.py - Optimized for Render Webhook Deployment
import telebot # Provides the main Telegram bot API functions
import os
from dotenv import load_dotenv # Used to load .env locally (though Render uses env vars)
from flask import Flask, request # Used to set up the Webhook server

# --- 1. CONFIGURATION AND INITIALIZATION ---

# Load environment variables (from .env locally, or Render environment remotely)
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# If the bot token is missing, the script shouldn't proceed
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set.")

# Render provides the port automatically via the environment
PORT = int(os.environ.get('PORT', 5000))
# The base URL of your Render service (e.g., https://medibot-final.onrender.com)
WEBHOOK_URL_BASE = os.environ.get('WEBHOOK_URL_BASE')
# The Webhook URL must be secret, using the BOT_TOKEN as the path
WEBHOOK_URL_PATH = f"/{BOT_TOKEN}"


# Initialize Bot and Flask
bot = telebot.TeleBot(BOT_TOKEN)
server = Flask(__name__)

# روابط الدفع حسب كل دولة
PAYMENT_LINKS = {
    "EG": {    # مصر
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5615069",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5594819"
    },
    "SA": {    # السعودية والخليج
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5763844",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5763828"
    },
    "DEFAULT": {  # باقي دول العالم
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5763844",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5763828"
    }
}

# --- 2. BOT LOGIC FUNCTIONS ---

# دالة تحديد الدولة تلقائياً
def detect_country(phone):
    # Standardize phone by removing leading '+'
    if phone.startswith("+"):
        phone = phone[1:]

    # Check for Egypt (20)
    if phone.startswith("20"):
        return "EG"
    # Check for KSA (966), UAE (971), Kuwait (965), Bahrain (973), Oman (968)
    if phone.startswith("966") or phone.startswith("971") or \
       phone.startswith("965") or phone.startswith("973") or \
       phone.startswith("968"):
        return "SA"
    return "DEFAULT"

# --- 3. TELEGRAM HANDLERS ---

# رسالة البداية
@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "مرحباً 👋\nمن فضلك أرسل رقم هاتفك مع كود الدولة.\nمثال:\n+201234567890\n+966512345678")

# استقبال رقم الهاتف
@bot.message_handler(func=lambda m: True)
def handle_phone(message):
    phone = message.text.strip()

    # Validation check: should start with '+' or a digit
    if not phone.startswith("+") and not phone[0].isdigit():
        bot.reply_to(message, "❌ من فضلك أرسل رقم هاتف صحيح (يجب أن يبدأ بعلامة + أو رقم).")
        return

    country = detect_country(phone)
    prices = PAYMENT_LINKS.get(country, PAYMENT_LINKS["DEFAULT"])

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
🌍 تم التعرف على دولتك: {country}

{price_text}

✨ الخطة الفردية – {ind_price}
رابط الدفع: {prices['individual']}

👨‍👩‍👧 الخطة العائلية – {fam_price}
رابط الدفع: {prices['family']}

بعد الدفع أرسل لقطة شاشة لتأكيد الاشتراك.
"""
    bot.reply_to(message, reply)

# --- 4. WEBHOOK IMPLEMENTATION FOR RENDER (FLASK ROUTES) ---

@server.route(WEBHOOK_URL_PATH, methods=['POST'])
def get_message():
    """Handles incoming POST request from Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        # Process the update using the bot handler functions defined above
        bot.process_new_updates([update])
        return '!', 200
    else:
        # Deny access if not a JSON payload (i.e., not Telegram)
        return 'Not Authorized', 403

@server.route('/')
def webhook_setup():
    """Sets the Telegram Webhook URL upon service startup."""
    # Ensure WEBHOOK_URL_BASE is set in Render environment variables
    if not WEBHOOK_URL_BASE:
        return "WEBHOOK_URL_BASE not set. Cannot set webhook.", 500

    webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_URL_PATH}"
    
    # 1. Remove any old webhook
    bot.remove_webhook()
    
    # 2. Set the new webhook URL
    if bot.set_webhook(url=webhook_url):
        return f"Webhook set to: {webhook_url}", 200
    else:
        return "Failed to set webhook.", 500


# --- 5. START THE FLASK SERVER ---

if __name__ == "__main__":
    # Flask runs on 0.0.0.0 (all interfaces) and uses the port specified by Render
    server.run(host="0.0.0.0", port=PORT)
