# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
from datetime import datetime
import google.generativeai as genai
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, 
    KeyboardButton, ReplyKeyboardRemove, WebAppInfo
)

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GEMINI_KEY = "AIzaSyDijUmn0uvUX6aG9C5wqWcIy6O4QXoXzn4"
TG_CHANNEL = "https://t.me/+YOEpXfsmd9tiODQ6"

genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- БАЗА ДАННЫХ ---
def db_commit(sql, params=()):
    with sqlite3.connect('vkusomer.db') as conn:
        conn.execute(sql, params)
        conn.commit()

def db_query(sql, params=()):
    with sqlite3.connect('vkusomer.db') as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchone()

db_commit('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, norma INTEGER, total_today INTEGER, 
    water INTEGER, streak INTEGER, last_date TEXT, 
    weight INTEGER, target INTEGER, avatar TEXT)''')

# --- СОСТОЯНИЯ ---
class Survey(StatesGroup):
    gender, goal, target_w, activity, params = [State() for _ in range(5)]

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Записать еду"), KeyboardButton(text="📊 Мой статус")],
        [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🥗 Что приготовить?")],
        [KeyboardButton(text="🧘 Психолог"), KeyboardButton(text="🍎 Замена вредностей")],
        [KeyboardButton(text="📅 Меню на месяц"), KeyboardButton(text="💧 +1 Стакан воды")],
        [KeyboardButton(text="📱 Открыть Визуальный Центр", web_app=WebAppInfo(url="https://vkusomer.onrender.com"))]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ ---
# Переменная для хранения истории сообщений (память бота)
chat_history = {}

async def ask_dietologist(user_id, message_obj, system_type="default"):
    # Темы общения
    contexts = {
        "default": "Ты - Диетолог Вкусомер Плюс. Ты можешь просто болтать с пользователем на любые темы, но твоя страсть - ЗОЖ. Если пользователь пишет, что он что-то съел - оцени калории и напиши в конце 'ИТОГО ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Давай подробные рецепты с граммами и этапами приготовления.",
        "psych": "Ты психолог. Поддержи пользователя, помоги не сорваться, будь очень добрым.",
        "month": "Составь меню на месяц. Раздели на 'Базовую корзину' и 'Еженедельный докуп'."
    }
    
    # Собираем историю
    if user_id not in chat_history: chat_history[user_id] = []
    
    prompt = contexts.get(system_type, contexts["default"])
    user_input = message_obj.text or message_obj.caption or "Анализ медиа"
    
    try:
        if message_obj.photo or message_obj.voice or message_obj.video_note:
            # Обработка фото/голоса/кружков
            file_id = None
            mime = "image/jpeg"
            if message_obj.photo: file_id = message_obj.photo[-1].file_id
            elif message_obj.voice: 
                file_id = message_obj.voice.file_id
                mime = "audio/ogg"
            elif message_obj.video_note:
                file_id = message_obj.video_note.file_id
                mime = "video/mp4"
            
            file = await bot.get_file(file_id)
            file_bytes = await bot.download_file(file.file_path)
            content = [prompt + user_input, {"mime_type": mime, "data": file_bytes.read()}]
            response = ai_model.generate_content(content)
        else:
            # Просто текст (с учетом истории)
            history = chat_history[user_id][-6:] # Помним 6 последних фраз
            full_prompt = f"Контекст: {history}\n\nСистемная установка: {prompt}\n\nПользователь: {user_input}"
            response = ai_model.generate_content(full_prompt)
        
        chat_history[user_id].append(f"U: {user_input}")
        chat_history[user_id].append(f"AI: {response.text}")
        return response.text
    except Exception as e:
        return f"❤️ Диетолог задумался... Попробуй еще раз. ({e})"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index(): return "<h1>Бот работает</h1>"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "✨ **Добро пожаловать в Вкусомер Плюс!** 🥗\n\n"
        "Я — твой персональный **Диетолог**. Я умею не только считать калории, но и просто общаться! "
        "Можешь жаловаться мне на стресс, спрашивать рецепты или просто поболтать о жизни.\n\n"
        "Давай создадим твой профиль. Твой пол? 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
    await message.answer(welcome_text, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(Survey.gender)

# --- (Логика анкеты остается такой же, как в предыдущем коде) ---
@dp.message(Survey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Масса"), KeyboardButton(text="Здоровье")]], resize_keyboard=True)
    await message.answer("🎯 Какая наша главная цель?", reply_markup=kb)
    await state.set_state(Survey.goal)

@dp.message(Survey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Масса"]:
        await message.answer("🏁 К какому весу мы стремимся? (кг)", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.target_w)
    else:
        await state.set_state(Survey.params)
        await message.answer("📏 Напиши через пробел: возраст, рост, текущий вес.")

@dp.message(Survey.target_w)
async def proc_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_w=message.text)
    await message.answer("📏 Напиши через пробел: возраст, рост, текущий вес.")
    await state.set_state(Survey.params)

@dp.message(Survey.params)
async def survey_done(message: types.Message, state: FSMContext):
    try:
        age, h, w = map(int, message.text.split())
        norma = int((10 * w) + (6.25 * h) - (5 * age) + 5) # Упрощенно
        db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, streak, last_date, weight, target, avatar) VALUES (?, ?, 0, 0, 1, ?, ?, ?, ?)",
                  (message.from_user.id, norma, str(datetime.now().date()), w, w, "🧘 Спокойный дзен"))
        await message.answer(f"✅ Готово! Твоя норма: **{norma} ккал**. Пиши мне что угодно!", reply_markup=get_main_kb())
        await state.clear()
    except: await message.answer("Напиши три числа через пробел.")

# --- УМНЫЙ ЧАТ (РЕАГИРУЕТ НА ВСЁ) ---

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_up(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    await message.answer(f"💧 Стакан засчитан! ({val}/8)")

@dp.message(F.text == "📊 Мой статус")
async def status(message: types.Message):
    u = db_query("SELECT norma, total_today, water FROM users WHERE id=?", (message.from_user.id,))
    if u:
        # Рисуем шкалу калорий
        percent = int((u[1]/u[0])*100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **Твой прогресс сегодня:**\n\nЕда: {bar} {u[1]}/{u[0]} ккал\nВода: {u[2]}/8 стаканов\n\n📢 Канал: {TG_CHANNEL}")

@dp.message()
async def global_chat(message: types.Message):
    """Этот обработчик читает все сообщения и просто общается"""
    # Если это не кнопка, а просто текст
    await message.answer_chat_action("typing")
    
    # Определяем контекст (если в тексте есть ключевые слова)
    context = "default"
    if "рецепт" in message.text.lower() or "приготовить" in message.text.lower(): context = "chef"
    if "грустно" in message.text.lower() or "сорваться" in message.text.lower(): context = "psych"
    
    res = await ask_dietologist(message.from_user.id, message, context)
    
    # Проверка: если Диетолог нашел еду и выдал калории
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    if cals:
        u = db_query("SELECT total_today, norma FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_total = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_total, message.from_user.id))
            res += f"\n\n📈 (Записано в дневник: +{cals[0]} ккал)"

    await message.answer(res)

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
