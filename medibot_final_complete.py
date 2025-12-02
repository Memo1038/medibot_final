# medibot_final_secure.py
import telebot
import os
from dotenv import load_dotenv

# تحميل القيم من ملف .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# روابط الدفع حسب كل دولة
PAYMENT_LINKS = {
    "EG": {   # مصر
        "individual": "https://secure-egypt.paytabs.com/payment/link/140410/5615069",
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5594819"
    },
    "SA": {   # السعودية والخليج
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
    if phone.startswith("+20") or phone.startswith("20"):
        return "EG"
    if phone.startswith("+966") or phone.startswith("966"):
        return "SA"
    if phone.startswith("+971") or phone.startswith("971"):
        return "SA"
    if phone.startswith("+965") or phone.startswith("965"):
        return "SA"
    if phone.startswith("+973") or phone.startswith("973"):
        return "SA"
    if phone.startswith("+968") or phone.startswith("968"):
        return "SA"
    return "DEFAULT"

# رسالة البداية
@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "مرحباً 👋\nمن فضلك أرسل رقم هاتفك مع كود الدولة.\nمثال:\n+201234567890\n+966512345678")

# استقبال رقم الهاتف
@bot.message_handler(func=lambda m: True)
def handle_phone(message):
    phone = message.text.strip()

    if not phone.startswith("+") and not phone[0].isdigit():
        bot.reply_to(message, "❌ من فضلك أرسل رقم صحيح.")
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

# تشغيل البوت
bot.infinity_polling()
