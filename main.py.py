import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import sqlite3
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)

TOKEN = "8268554962:AAGnW2I4rPfzAv_aHnfpDwV4Q-Bi4_PvD9M"
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ----------------- База данных -----------------
conn = sqlite3.connect("carpool.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    role TEXT,
    name TEXT,
    origin TEXT,
    destination TEXT,
    phone TEXT,
    timestamp DATETIME,
    clients_count INTEGER DEFAULT 0,
    is_paid INTEGER DEFAULT 0,
    subscription_end TEXT,
    busy INTEGER DEFAULT 0,
    confirmed_with INTEGER
)
""")
conn.commit()

DESTINATIONS = ["Баткен", "Джалал-Абад", "Иссык-Куль", "Нарын", "Ош", "Таласс", "Бишкек"]

# ----------------- Inline клавиатуры -----------------
def destinations_inline(prefix):
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(text=city, callback_data=f"{prefix}_{city}") for city in DESTINATIONS]
    kb.add(*buttons)
    return kb

def change_route_inline():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text="Изменить маршрут", callback_data="change_route"))
    return kb

def poehali_inline(user_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text="Поехал", callback_data=f"poehali_{user_id}"))
    return kb

def admin_inline():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Очистить номера", callback_data="admin_clear"),
        types.InlineKeyboardButton("Выдать подписку на месяц", callback_data="admin_sub_month"),
        types.InlineKeyboardButton("Выдать подписку навсегда", callback_data="admin_sub_forever"),
        types.InlineKeyboardButton("База клиентов", callback_data="admin_clients"),
        types.InlineKeyboardButton("База водителей", callback_data="admin_drivers"),
        types.InlineKeyboardButton("База подписок", callback_data="admin_subs")
    )
    return kb

# ----------------- Вспомогательные функции -----------------
def get_role(user_id):
    cursor.execute("SELECT role FROM users WHERE id=?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r else None

def get_origin(user_id):
    cursor.execute("SELECT origin FROM users WHERE id=?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r else None

def get_destination(user_id):
    cursor.execute("SELECT destination FROM users WHERE id=?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r else None

def clean_old():
    limit = datetime.now() - timedelta(hours=24)
    cursor.execute("UPDATE users SET phone=NULL, origin=NULL, destination=NULL, busy=0, confirmed_with=NULL WHERE timestamp<?", (limit,))
    conn.commit()

# ----------------- /start -----------------
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    cursor.execute("INSERT OR IGNORE INTO users (id, name) VALUES (?, ?)", (user_id, message.from_user.first_name))
    conn.commit()

    if username == "tiedolik":  # админ
        await message.answer("Главное меню (админ):", reply_markup=admin_inline())
    else:
        role_buttons = types.InlineKeyboardMarkup()
        role_buttons.add(types.InlineKeyboardButton("Я пассажир", callback_data="role_passenger"))
        role_buttons.add(types.InlineKeyboardButton("Я водитель", callback_data="role_driver"))
        await message.answer("Кто вы?", reply_markup=role_buttons)

# ----------------- Выбор роли -----------------
@dp.callback_query_handler(lambda c: c.data.startswith("role_"))
async def set_role(call: types.CallbackQuery):
    role = "пассажир" if "passenger" in call.data else "водитель"
    cursor.execute("UPDATE users SET role=? WHERE id=?", (role, call.from_user.id))
    conn.commit()
    await call.message.answer("Где вы?", reply_markup=destinations_inline("origin"))
    await call.answer()

# ----------------- Выбор откуда -----------------
@dp.callback_query_handler(lambda c: c.data.startswith("origin_"))
async def set_origin(call: types.CallbackQuery):
    city = call.data.split("_")[1]
    cursor.execute("UPDATE users SET origin=? WHERE id=?", (city, call.from_user.id))
    conn.commit()
    await call.message.answer("Куда едите?", reply_markup=destinations_inline("dest"))
    await call.answer()

# ----------------- Выбор куда -----------------
@dp.callback_query_handler(lambda c: c.data.startswith("dest_"))
async def set_destination(call: types.CallbackQuery):
    city = call.data.split("_")[1]
    cursor.execute("UPDATE users SET destination=? WHERE id=?", (city, call.from_user.id))
    conn.commit()
    await call.message.answer("Отправьте свой номер телефона:")
    await call.answer()

# ----------------- Получение номера -----------------
@dp.message_handler(lambda m: m.text.replace("+","").isdigit())
async def get_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text
    cursor.execute("UPDATE users SET phone=?, timestamp=? WHERE id=?", (phone, datetime.now(), user_id))
    conn.commit()

    role = get_role(user_id)
    origin = get_origin(user_id)
    destination = get_destination(user_id)

    await message.answer(f"{'Ищем водителя...' if role=='пассажир' else 'Ищем пассажира...'}", reply_markup=change_route_inline())

    # Поиск пары
    cursor.execute("SELECT id, phone, role FROM users WHERE role!=? AND origin=? AND destination=? AND phone IS NOT NULL AND busy=0",
                   (role, origin, destination))
    row = cursor.fetchone()
    if row:
        other_id, other_phone, other_role = row
        cursor.execute("UPDATE users SET busy=1, confirmed_with=? WHERE id=?", (other_id, user_id))
        cursor.execute("UPDATE users SET busy=1, confirmed_with=? WHERE id=?", (user_id, other_id))
        conn.commit()

        await message.answer(f"Найдена пара! Вот телефон: {other_phone}", reply_markup=poehali_inline(other_id))
        await bot.send_message(other_id, f"Найдена пара! Вот телефон: {phone}", reply_markup=poehali_inline(user_id))

# ----------------- Кнопка изменить маршрут -----------------
@dp.callback_query_handler(lambda c: c.data=="change_route")
async def change_route(call: types.CallbackQuery):
    cursor.execute("UPDATE users SET origin=NULL, destination=NULL WHERE id=?", (call.from_user.id,))
    conn.commit()
    await call.message.answer("Где вы?", reply_markup=destinations_inline("origin"))
    await call.answer()

# ----------------- Кнопка "Поехал" -----------------
@dp.callback_query_handler(lambda c: c.data.startswith("poehali_"))
async def poehali(call: types.CallbackQuery):
    user_id = int(call.data.split("_")[1])
    cursor.execute("UPDATE users SET busy=0, confirmed_with=NULL, phone=NULL, origin=NULL, destination=NULL WHERE id IN (?,?)", (call.from_user.id, user_id))
    conn.commit()
    await call.message.answer("Старт!")
    await bot.send_message(user_id, "Старт!")
    await call.answer()

# ----------------- Запуск -----------------
if __name__ == "__main__":
    clean_old()
    executor.start_polling(dp, skip_updates=True)
