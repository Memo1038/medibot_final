```python
# medibot_final_secure.py
import os
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters, ConversationHandler
from apscheduler.schedulers.background import BackgroundScheduler

# ======== تحميل المتغيرات السرية من .env ========
load_dotenv()  # يقرأ القيم من ملف .env

BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_KEY = os.getenv("AZURE_KEY")
AZURE_REGION = os.getenv("AZURE_REGION")
AZURE_ENDPOINT = f"https://{AZURE_REGION}.api.cognitive.microsoft.com/"

# ======== روابط الدفع حسب الدولة ========
PAY_LINKS = {
    "EG": {  # مصر
        "personal": "https://secure-egypt.paytabs.com/payment/link/140410/5615069",  # 97 جنيه
        "family": "https://secure-egypt.paytabs.com/payment/link/140410/5594819"     # 190 جنيه
    },
    "SA": {  # السعودية والخليج
        "personal": "https://paytabs.com/sa-personal",
        "family": "https://paytabs.com/sa-family"
    },
    "INTL": {  # باقي الدول
        "personal": "https://paytabs.com/int-personal",
        "family": "https://paytabs.com/int-family"
    }
}

DB_PATH = "medibot_final_complete.db"

# ======== قاعدة البيانات ========
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    phone TEXT,
    full_name TEXT,
    country TEXT,
    city TEXT,
    age INTEGER,
    plan_type TEXT DEFAULT 'شخصي',
    paid INTEGER DEFAULT 0
)""")

c.execute("""CREATE TABLE IF NOT EXISTS meds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    name TEXT,
    times TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS med_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    med_name TEXT,
    time TEXT,
    status TEXT DEFAULT 'Pending'
)""")

conn.commit()
scheduler = BackgroundScheduler()
scheduler.start()

# ======== ConversationHandler مراحل إدخال البيانات ========
PHONE, NAME, COUNTRY, CITY, AGE, PLAN, MED_NAME, MED_TIMES = range(8)

def start(update: Update, context: CallbackContext):
    tg_id = update.message.from_user.id
    c.execute("INSERT OR IGNORE INTO users (tg_id) VALUES (?)", (tg_id,))
    conn.commit()
    context.user_data['step_stack'] = [PHONE]
    update.message.reply_text("مرحبًا! قبل متابعة البوت، يرجى إدخال بياناتك الأساسية.\nأرسل رقم جوالك:")
    return PHONE

def go_back(update: Update, context: CallbackContext):
    if 'step_stack' in context.user_data and len(context.user_data['step_stack'])>1:
        context.user_data['step_stack'].pop()  # إزالة الخطوة الحالية
        previous_step = context.user_data['step_stack'][-1]
        if previous_step == PHONE:
            update.message.reply_text("الرجوع لرقم الهاتف. أرسل رقمك مرة أخرى:")
            return PHONE
        elif previous_step == NAME:
            update.message.reply_text("الرجوع للاسم الكامل. أرسل اسمك:")
            return NAME
        elif previous_step == COUNTRY:
            update.message.reply_text("الرجوع للدولة. أرسل دولتك:")
            return COUNTRY
        elif previous_step == CITY:
            update.message.reply_text("الرجوع للمدينة. أرسل مدينتك:")
            return CITY
        elif previous_step == AGE:
            update.message.reply_text("الرجوع للسن. أرسل عمرك:")
            return AGE
    else:
        update.message.reply_text("لا يمكن الرجوع أكثر من ذلك.")
        return ConversationHandler.END

def phone(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    tg_id = update.message.from_user.id

    if text.lower() == "⬅️ العودة للخطوة السابقة":
        return go_back(update, context)

    # حفظ الرقم
    c.execute("UPDATE users SET phone=? WHERE tg_id=?", (text, tg_id))
    conn.commit()

    # اكتشاف الدولة
    country_code_map = {"+20":"EG","+966":"SA","+971":"AE","+974":"QA","+965":"KW"}
    detected_country = "INTL"
    for code, country in country_code_map.items():
        if text.startswith(code):
            detected_country = country
            break
    context.user_data['detected_country'] = detected_country
    c.execute("UPDATE users SET country=? WHERE tg_id=?", (detected_country, tg_id))
    conn.commit()

    update.message.reply_text("أرسل اسمك الكامل:")
    context.user_data['step_stack'].append(NAME)
    return NAME

def name(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    tg_id = update.message.from_user.id
    if text.lower() == "⬅️ العودة للخطوة السابقة":
        return go_back(update, context)
    c.execute("UPDATE users SET full_name=? WHERE tg_id=?", (text, tg_id))
    conn.commit()
    context.user_data['step_stack'].append(CITY)
    update.message.reply_text("أرسل مدينتك:")
    return CITY

def city(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    tg_id = update.message.from_user.id
    if text.lower() == "⬅️ العودة للخطوة السابقة":
        return go_back(update, context)
    c.execute("UPDATE users SET city=? WHERE tg_id=?", (text, tg_id))
    conn.commit()
    context.user_data['step_stack'].append(AGE)
    update.message.reply_text("أرسل عمرك:")
    return AGE

def age(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    tg_id = update.message.from_user.id
    if text.lower() == "⬅️ العودة للخطوة السابقة":
        return go_back(update, context)
    c.execute("UPDATE users SET age=? WHERE tg_id=?", (text, tg_id))
    conn.commit()

    # بعد إدخال البيانات نعرض خطة الدفع المناسبة
    detected_country = context.user_data.get('detected_country','INTL')
    pay_links = PAY_LINKS.get(detected_country, PAY_LINKS['INTL'])

    keyboard = [
        [InlineKeyboardButton("الخطة الشخصية", callback_data="plan_personal")],
        [InlineKeyboardButton("الخطة العائلية", callback_data="plan_family")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("اختر نوع الخطة لتفعيل البوت:", reply_markup=reply_markup)
    context.user_data['pay_links'] = pay_links
    context.user_data['step_stack'].append(PLAN)
    return PLAN

def plan_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    tg_id = query.from_user.id
    pay_links = context.user_data.get('pay_links', PAY_LINKS['INTL'])
    if query.data == "plan_personal":
        c.execute("UPDATE users SET plan_type='شخصي' WHERE tg_id=?", (tg_id,))
        conn.commit()
        link = pay_links.get("personal")
        price = "97 جنيه" if context.user_data.get('detected_country')=="EG" else ""
        query.edit_message_text(f"تم اختيار الخطة الشخصية ✅\nيرجى الدفع لتفعيل البوت: {link} {price}")
    elif query.data == "plan_family":
        c.execute("UPDATE users SET plan_type='عائلي' WHERE tg_id=?", (tg_id,))
        conn.commit()
        link = pay_links.get("family")
        price = "190 جنيه" if context.user_data.get('detected_country')=="EG" else ""
        query.edit_message_text(f"تم اختيار الخطة العائلية ✅\nيرجى الدفع لتفعيل البوت: {link} {price}")

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

# ======== إعداد البوت ========
updater = Updater(BOT_TOKEN, use_context=True)
dp = updater.dispatcher

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        PHONE: [MessageHandler(Filters.text & ~Filters.command, phone)],
        NAME: [MessageHandler(Filters.text & ~Filters.command, name)],
        CITY: [MessageHandler(Filters.text & ~Filters.command, city)],
        AGE: [MessageHandler(Filters.text & ~Filters.command, age)],
        PLAN: [CallbackQueryHandler(plan_callback)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

dp.add_handler(conv_handler)

updater.start_polling()
updater.idle()
```
