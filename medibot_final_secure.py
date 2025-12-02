# medibot_final_secure.py - Optimized for Render Webhook Deployment
import telebot
import os
from dotenv import load_dotenv
from flask import Flask, request

# 1. Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Render provides the port automatically
PORT = int(os.environ.get('PORT', 5000)) 
# Your Render web service URL (replace with your actual Render URL)
WEBHOOK_URL_BASE = os.environ.get('WEBHOOK_URL_BASE') 

# 2. Initialize Bot and Flask
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

# دالة تحديد الدولة تلقائياً
def detect_country(phone):
    # Standardize phone by removing leading '+'
    if phone.startswith("+"):
        phone = phone[1:] 

    if phone.startswith("20"):
        return "EG"
    if phone.startswith("966") or phone.startswith("971") or \
       phone.startswith("965") or phone.startswith("973") or \
       phone.startswith("968"):
        return "SA"
    return "DEFAULT"

# --- TELEGRAM HANDLERS (Same Logic) ---

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
        # Note: Corrected the family price for consistency (was 197 in ManyChat blueprint, 190 here)
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

# --- WEBHOOK IMPLEMENTATION FOR RENDER ---

@server.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    """Handles incoming POST request from Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '!', 200
    else:
        return 'Hello from bot', 200 # Should be 403 or similar but 200 prevents retries

@server.route('/')
def webhook():
    """Sets the Telegram Webhook URL upon service startup."""
    # Ensure WEBHOOK_URL_BASE is set in Render environment variables
    if not WEBHOOK_URL_BASE:
        return "WEBHOOK_URL_BASE not set. Cannot set webhook.", 500

    webhook_url = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return "Webhook set!", 200

# 3. Start the Flask server
if __name__ == "__main__":
    server.run(host="0.0.0.0", port=PORT)