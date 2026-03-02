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
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
)

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GEMINI_KEY = "AIzaSyDijUmn0uvUX6aG9C5wqWcIy6O4QXoXzn4"
TG_CHANNEL = "https://t.me/+YOEpXfsmd9tiODQ6"

# Настройка бесплатной нейросети Gemini
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- БАЗА ДАННЫХ ---
def db_commit(sql, params=()):
    with sqlite3.connect('vkusomer.db') as conn:
        conn.execute(sql, params); conn.commit()

def db_query(sql, params=()):
    with sqlite3.connect('vkusomer.db') as conn:
        cursor = conn.cursor(); cursor.execute(sql, params)
        return cursor.fetchone()

db_commit('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, norma INTEGER, total_today INTEGER, 
    water INTEGER, last_date TEXT, weight INTEGER, target INTEGER)''')

# --- СОСТОЯНИЯ ---
class UserSurvey(StatesGroup):
    gender = State()
    goal = State()
    target_w = State()
    activity = State()
    age = State()
    height = State()
    weight = State()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мой статус"), KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?")],
        [KeyboardButton(text="🥗 Что приготовить сегодня?"), KeyboardButton(text="🧘 Психолог")],
        [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="📅 Меню на месяц")],
        [KeyboardButton(text="🔔 Напомнить через 3ч"), KeyboardButton(text="💧 +1 Стакан воды")],
        [KeyboardButton(text="💬 Просто поболтать"), KeyboardButton(text="🧾 Сканер чека")]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ ---
async def ask_dietologist(user_id, message_obj, system_type="default"):
    prompts = {
        "default": "Ты - Диетолог Вкусомер Плюс. Ты можешь просто болтать. Если пишут про еду - считай калории и пиши в конце СТРОГО: 'ИТОГО ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Давай очень подробные рецепты с граммами и шагами 1, 2, 3...",
        "replace": "Найди полезную ПП замену вредному продукту.",
        "month": "Составь меню на месяц. Список продуктов (база + свежее) и план блюд."
    }
    
    prompt_text = prompts.get(system_type, prompts["default"])
    user_text = message_obj.text or message_obj.caption or "Анализ"
    
    try:
        if message_obj.photo:
            file = await bot.get_file(message_obj.photo[-1].file_id)
            img = await bot.download_file(file.file_path)
            # Gemini Vision требует байты
            response = model.generate_content([prompt_text + "\nПользователь: " + user_text, {"mime_type": "image/jpeg", "data": img.read()}])
        else:
            response = model.generate_content(prompt_text + "\nПользователь: " + user_text)
        return response.text
    except Exception as e:
        return f"🧘 Диетолог отвлекся... Попробуй еще раз. ({e})"

# --- АНКЕТА ---

@app.route('/')
def index(): return "OK"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome = "✨ **Привет! Я Вкусомер Плюс.** 🥗\n\nЯ твой ИИ-Диетолог. Давай создадим профиль. Твой пол? 👤"
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(welcome, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🎯 Твоя цель?", reply_markup=kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Набрать массу"]:
        await message.answer("🏁 Какой вес твоя цель? (кг)", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserSurvey.target_w)
    else:
        await state.set_state(UserSurvey.activity)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True, one_time_keyboard=True)
        await message.answer("🏃‍♂️ Твоя активность?", reply_markup=kb)

@dp.message(UserSurvey.target_w)
async def proc_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_w=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🏃‍♂️ Твоя активность?", reply_markup=kb)
    await state.set_state(UserSurvey.activity)

@dp.message(UserSurvey.activity)
async def proc_act(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("🎂 Твой возраст?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserSurvey.age)

@dp.message(UserSurvey.age)
async def proc_age(message: types.Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    await message.answer("📏 Твой рост (см)?")
    await state.set_state(UserSurvey.height)

@dp.message(UserSurvey.height)
async def proc_h(message: types.Message, state: FSMContext):
    await state.update_data(height=int(message.text))
    await message.answer("⚖️ Твой текущий вес (кг)?")
    await state.set_state(UserSurvey.weight)

@dp.message(UserSurvey.weight)
async def survey_final(message: types.Message, state: FSMContext):
    w = int(message.text); d = await state.get_data()
    bmr = (10 * w) + (6.25 * d['height']) - (5 * d['age']) + (5 if d['gender'] == "Мужской" else -161)
    norma = int(bmr * 1.3)
    if d['goal'] == "Похудеть": norma -= 400
    db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, last_date, weight, target) VALUES (?, ?, 0, 0, ?, ?, ?)",
              (message.from_user.id, norma, str(datetime.now().date()), w, d.get('target_w', w)))
    await message.answer("✅ **Твой профиль успешно создан! Тест пройден.**")
    await message.answer(f"Твоя норма: **{norma} ккал**. Теперь я твой Диетолог. Пиши мне что угодно!", reply_markup=get_main_kb())
    await state.clear()

# --- ФУНКЦИИ ---

@dp.message(F.text == "📊 Мой статус")
async def show_status(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = min(int((u[1]/u[0])*100), 100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **СТАТУС:**\nЦель: {u[3]} -> {u[4]} кг\n🍎 Еда: {bar} {u[1]}/{u[0]}\n💧 Вода: {'🟦' * u[2]} {u[2]}/8\n\n📢 Канал: {TG_CHANNEL}")

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_up(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    await message.answer(f"💧 Стакан засчитан! ({val}/8)")
    if val == 8: await message.answer("🏆 **АЧИВКА: 'Водный Король'!** 🌊")

# --- УМНЫЙ ЧАТ ---

@dp.message()
async def global_chat(message: types.Message):
    if message.text == "🧘 Психолог": ctx = "psych"
    elif message.text == "🍎 Замена вредностей": await message.answer("Напиши вредный продукт 👇"); return
    elif message.text == "👨‍🍳 Шеф: что в холодильнике?": await message.answer("Напиши список продуктов 👇"); return
    elif message.text == "🥗 Что приготовить сегодня?": await message.answer("Какое блюдо хочешь? 👇"); return
    elif message.text == "📅 Меню на месяц": ctx = "month"
    elif message.text == "🔔 Напомнить через 3ч":
        scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Пора поесть!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
        await message.answer("✅ Напомню!"); return
    else: ctx = "default"

    await message.answer_chat_action("typing")
    res = await ask_dietologist(message.from_user.id, message, ctx)
    
    # Сумматор калорий
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    if not cals: cals = re.findall(r"ККАЛ: (\d+)", res)
    if cals:
        u = db_query("SELECT total_today, norma FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_t = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_t, message.from_user.id))
            res += f"\n\n📈 (Записано: +{cals[0]} ккал. Итого: {new_t}/{u[1]})"

    await message.answer(res, reply_markup=get_main_kb())

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    scheduler.start()
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
