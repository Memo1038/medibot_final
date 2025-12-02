# medibot_full_ar.py - MediBot كامل بالعربية مع التذكيرات الصوتية وPayTabs

import os
import telebot
from telebot import types
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from datetime import datetime, timedelta

# -------------------------------
# إعداد المتغيرات البيئية
# -------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")
AZURE_KEY = os.getenv("AZURE_KEY")
AZURE_REGION = os.getenv("AZURE_REGION")
PAYTABS_SERVER_KEY = os.getenv("PAYTABS_SERVER_KEY")  # مفتاح التحقق من Webhook

if not BOT_TOKEN or not WEBHOOK_URL_BASE or not AZURE_KEY or not AZURE_REGION or not PAYTABS_SERVER_KEY:
    raise ValueError("يجب تعيين جميع متغيرات البيئة: BOT_TOKEN, WEBHOOK_URL_BASE, AZURE_KEY, AZURE_REGION, PAYTABS_SERVER_KEY")

WEBHOOK_URL = f"{WEBHOOK_URL_BASE}/{BOT_TOKEN}"

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# -------------------------------
# التخزين المؤقت للمستخدمين والأدوية
# -------------------------------
users_data = {}  # {user_id: {name, country, phone, age, email, plan, medicines: [{name, time}], language}}

# -------------------------------
# لوحات الأزرار
# -------------------------------
def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📝 إضافة دواء", "📋 عرض الأدوية")
    kb.row("🔄 تعديل دواء", "❌ حذف دواء")
    kb.row("💰 اختيار الخطة")
    return kb

def payment_buttons_keyboard(country):
    kb = types.InlineKeyboardMarkup()
    if country == "EG":
        kb.add(types.InlineKeyboardButton("الخطة الفردية | 97 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5615069"))
        kb.add(types.InlineKeyboardButton("الخطة العائلية | 190 جنيه", url="https://secure-egypt.paytabs.com/payment/link/140410/5594819"))
    else:  # الخليج
        kb.add(types.InlineKeyboardButton("الخطة الفردية | 59 ريال", url="https://secure-egypt.paytabs.com/payment/link/140410/5763844"))
        kb.add(types.InlineKeyboardButton("الخطة العائلية | 89 ريال", url="https://secure-egypt.paytabs.com/payment/link/140410/5763828"))
    return kb

# -------------------------------
# وظائف التذكير الصوتي باستخدام Azure TTS
# -------------------------------
def generate_voice_message(text, user_id):
    """
    يولد رسالة صوتية MP3 حسب اللغة واللهجة ويخزنها مؤقتًا.
    """
    user = users_data.get(user_id, {})
    country = user.get("country", "DEFAULT")
    # اختيار صوت حسب الدولة
    if country == "EG":
        voice = "ar-EG-HodaNeural"  # عربية مصرية
    else:
        voice = "ar-SA-HamedNeural"  # عربية خليجية سعودية
    tts_url = f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3"
    }
    ssml = f"""
    <speak version='1.0' xml:lang='ar-EG'>
        <voice name='{voice}'>{text}</voice>
    </speak>
    """
    resp = requests.post(tts_url, headers=headers, data=ssml)
    if resp.status_code == 200:
        filename = f"tts_{user_id}.mp3"
        with open(filename, "wb") as f:
            f.write(resp.content)
        return filename
    return None

# -------------------------------
# وظائف التذكير المجدول
# -------------------------------
def schedule_medicine_reminder(user_id, med_name, time_str):
    """
    يضيف مهمة تذكير لكل دواء بوقت محدد
    time_str = "HH:MM" 24h
    """
    hour, minute = map(int, time_str.split(":"))
    now = datetime.now()
    remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if remind_time < now:
        remind_time += timedelta(days=1)

    def reminder():
        text = f"🕒 تذكير بالدواء: {med_name}\n"
        text += f"الجرعة الآن!"
        audio_file = generate_voice_message(f"{users_data[user_id]['name']}، حان موعد تناول دواء {med_name}", user_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ تم تناوله", callback_data=f"taken_{med_name}"))
        kb.add(types.InlineKeyboardButton("⏰ تأجيل 10 دقائق", callback_data=f"snooze_{med_name}"))
        bot.send_message(user_id, text, reply_markup=kb)
        if audio_file:
            with open(audio_file, "rb") as f:
                bot.send_audio(user_id, f)
            os.remove(audio_file)

    scheduler.add_job(reminder, 'date', run_date=remind_time)

# -------------------------------
# التحقق من الدفع بواسطة PayTabs Webhook
# -------------------------------
@app.route("/paytabs_webhook", methods=["POST"])
def paytabs_webhook():
    data = request.json
    if not data or data.get("server_key") != PAYTABS_SERVER_KEY:
        return "Unauthorized", 403
    user_id = int(data.get("custom_user_id", 0))
    status = data.get("transaction_status")
    if user_id in users_data and status == "Successful":
        users_data[user_id]["plan"] = data.get("plan_type", "غير محدد")
        bot.send_message(user_id, "✅ تم تأكيد الدفع. يمكنك الآن إضافة أدوية والبدء بالتذكيرات.", reply_markup=main_menu_keyboard())
    return "OK", 200

# -------------------------------
# تسلسل المستخدم (الفلوي)
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
        user["email"] = message.text.strip()
        user["step"] = "choose_plan"
        bot.send_message(user_id, "شكراً! الآن اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))
    
    elif step == "choose_plan":
        # سيتم التحقق بعد الدفع
        bot.send_message(user_id, "بعد الدفع، اضغط على أي زر للوصول إلى القائمة الرئيسية:", reply_markup=main_menu_keyboard())
        user["step"] = "main_menu"
    
    elif step == "main_menu":
        text = message.text.strip()
        if text == "📝 إضافة دواء":
            user["step"] = "adding_medicine"
            bot.send_message(user_id, "أدخل اسم الدواء الذي تريد إضافته:")
        elif text == "📋 عرض الأدوية":
            meds = user["medicines"]
            if meds:
                bot.send_message(user_id, "قائمة الأدوية:\n" + "\n".join([f"{i+1}. {m['name']} في {m['time']}" for i,m in enumerate(meds)]), reply_markup=main_menu_keyboard())
            else:
                bot.send_message(user_id, "لم تقم بإضافة أي دواء بعد.", reply_markup=main_menu_keyboard())
        elif text == "🔄 تعديل دواء":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لتعديلها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "editing_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد تعديله:\n" + "\n".join([f"{i+1}. {m['name']}" for i,m in enumerate(meds)]))
        elif text == "❌ حذف دواء":
            meds = user["medicines"]
            if not meds:
                bot.send_message(user_id, "لا يوجد أدوية لحذفها.", reply_markup=main_menu_keyboard())
                return
            user["step"] = "deleting_medicine"
            bot.send_message(user_id, "أرسل رقم الدواء الذي تريد حذفه:\n" + "\n".join([f"{i+1}. {m['name']}" for i,m in enumerate(meds)]))
        elif text == "💰 اختيار الخطة":
            bot.send_message(user_id, "اختر خطتك:", reply_markup=payment_buttons_keyboard(user["country"]))
    
    elif step == "adding_medicine":
        med_name = message.text.strip()
        user["step"] = "adding_medicine_time"
        user["new_med"] = {"name": med_name}
        bot.send_message(user_id, "أدخل وقت الدواء بالساعة والدقيقة (مثال 14:30):")
    
    elif step == "adding_medicine_time":
        time_str = message.text.strip()
        try:
            datetime.strptime(time_str, "%H:%M")
        except:
            bot.send_message(user_id, "❌ التنسيق غير صحيح. استخدم HH:MM (مثال 14:30).")
            return
        user["new_med"]["time"] = time_str
        user["medicines"].append(user["new_med"])
        schedule_medicine_reminder(user_id, user["new_med"]["name"], time_str)
        bot.send_message(user_id, f"✅ تم إضافة الدواء: {user['new_med']['name']} في {time_str}", reply_markup=main_menu_keyboard())
        user["step"] = "main_menu"
        user.pop("new_med")
    
    elif step == "editing_medicine":
        index = message.text.strip()
        meds = user["medicines"]
        if not index.isdigit() or int(index)<1 or int(index)>len(meds):
            bot.send_message(user_id, "❌ الرقم غير صحيح. حاول مرة أخرى.")
            return
        user["edit_index"] = int(index)-1
        user["step"] = "editing_medicine_name"
        bot.send_message(user_id, f"أرسل الاسم الجديد للدواء {meds[int(index)-1]['name']}:")
    
    elif step == "editing_medicine_name":
        new_name = message.text.strip()
        idx = user.pop("edit_index")
        user["medicines"][idx]["name"] = new_name
        user["step"] = "main_menu"
        bot.send_message(user_id, f"✅ تم تعديل الدواء إلى: {new_name}", reply_markup=main_menu_keyboard())
    
    elif step == "deleting_medicine":
        index = message.text.strip()
        meds = user["medicines"]
        if not index.isdigit() or int(index)<1 or int(index)>len(meds):
            bot.send_message(user_id, "❌ الرقم غير صحيح. حاول مرة أخرى.")
            return
        deleted = meds.pop(int(index)-1)
        user["step"] = "main_menu"
        bot.send_message(user_id, f"❌ تم حذف الدواء: {deleted['name']}", reply_markup=main_menu_keyboard())

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
def index_web():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    return f"Webhook set: {WEBHOOK_URL}", 200

# -------------------------------
# بدء السيرفر
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
