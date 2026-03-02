# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
import base64
from datetime import datetime
import google.generativeai as genai
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
)

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GEMINI_KEY = "AIzaSyDijUmn0uvUX6aG9C5wqWcIy6O4QXoXzn4"
TG_CHANNEL = "https://t.me/+YOEpXfsmd9tiODQ6"
PAID_BOT = "https://t.me/TasteMeterPlus_bot"

# Настройка ИИ (Gemini 1.5 Flash - бесплатно и мощно)
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
    water INTEGER, streak INTEGER, last_date TEXT, 
    weight INTEGER, target INTEGER, avatar TEXT)''')

# --- СОСТОЯНИЯ ---
class UserSurvey(StatesGroup):
    gender = State()
    goal = State()
    target_weight = State()
    activity = State()
    age = State()
    height = State()
    weight = State()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мой статус"), KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?")],
        [KeyboardButton(text="🥗 Что приготовить?"), KeyboardButton(text="🧘 Психолог")],
        [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="📅 Меню на месяц")],
        [KeyboardButton(text="🔔 Напомнить через 3ч"), KeyboardButton(text="💧 +1 Стакан воды")],
        [KeyboardButton(text="💎 Продлить Плюс (Звезды)")]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ (ДИЕТОЛОГ) ---
chat_sessions = {}

async def ask_dietologist(user_id, message_obj, system_mode="default"):
    # Промпты для разных режимов
    modes = {
        "default": "Ты - Диетолог Вкусомер Плюс. Общайся вежливо, используй эмодзи. Если пользователь пишет, что он поел - посчитай калории и напиши в конце: 'ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Дай очень подробный рецепт с граммами и шагами 1, 2, 3...",
        "month": "Составь меню на месяц. Список продуктов (база и свежее) и план блюд.",
        "psych": "Ты психолог. Поддержи пользователя, чтобы он не сорвался на вредную еду."
    }
    
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]
    user_text = message_obj.text or message_obj.caption or "Анализ"
    full_prompt = f"ИНСТРУКЦИЯ: {modes.get(system_mode)} \n Пользователь: {user_text}"

    try:
        if message_obj.photo:
            file = await bot.get_file(message_obj.photo[-1].file_id)
            img_data = await bot.download_file(file.file_path)
            response = model.generate_content([full_prompt, {"mime_type": "image/jpeg", "data": img_data.read()}])
        else:
            response = chat.send_message(full_prompt)
        return response.text
    except Exception as e:
        return f"🧘 Диетолог отвлекся... Попробуй еще раз через минуту. ({e})"

# --- ОБРАБОТЧИКИ АНКЕТЫ ---

@app.route('/')
def index(): return "Бот Вкусомер Плюс запущен!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome = (
        "✨ **Привет! Я Вкусомер Плюс.** 🥗\n\n"
        "Я твой личный ИИ-Диетолог. Я научу тебя есть вкусно и худеть без стресса!\n"
        "Я понимаю текст, фото, голос и даже видео-кружки.\n\n"
        "Давай создадим твой профиль. Твой пол? 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(welcome, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🎯 Какая наша цель?", reply_markup=kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Набрать массу"]:
        await message.answer("🏁 К какому весу стремимся? (кг)", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserSurvey.target_weight)
    else:
        await state.set_state(UserSurvey.activity)
        await ask_activity(message)

async def ask_activity(message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🏃‍♂️ Твоя активность?", reply_markup=kb)

@dp.message(UserSurvey.target_weight)
async def proc_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_weight=message.text)
    await state.set_state(UserSurvey.activity)
    await ask_activity(message)

@dp.message(UserSurvey.activity)
async def proc_act(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("🎂 Сколько тебе лет?", reply_markup=ReplyKeyboardRemove())
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
async def proc_survey_finish(message: types.Message, state: FSMContext):
    w = int(message.text); d = await state.get_data()
    # Формула Миффлина-Сан Жеора
    bmr = (10 * w) + (6.25 * d['height']) - (5 * d['age']) + (5 if d['gender'] == "Мужской" else -161)
    norma = int(bmr * 1.3)
    if d['goal'] == "Похудеть": norma -= 400
    
    db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, streak, last_date, weight, target, avatar) VALUES (?, ?, 0, 0, 1, ?, ?, ?, ?)",
              (message.from_user.id, norma, str(datetime.now().date()), w, d.get('target_weight', w), "🧘 Спокойный дзен"))
    
    await message.answer("✅ **Профиль успешно создан! Тест пройден.**")
    await message.answer(f"Твоя норма: **{norma} ккал**. Теперь я твой Диетолог. Просто пиши мне что угодно!", reply_markup=get_main_kb())
    await state.clear()

# --- ФУНКЦИИ МЕНЮ ---

@dp.message(F.text == "📊 Мой статус")
async def show_status(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target, avatar FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = min(int((u[1]/u[0])*100), 100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **ТВОЙ СТАТУС:**\nЦель: {u[3]} -> {u[4]} кг\nАватар: {u[5]}\n\n🍎 Еда: {bar} {u[1]}/{u[0]} ккал\n💧 Вода: {'🟦' * u[2]} {u[2]}/8 стаканов\n\n📢 Канал: {TG_CHANNEL}")

@dp.message(F.text == "💧 +1 Стакан воды")
async def add_water(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    await message.answer(f"💧 Стакан засчитан! ({val}/8)")
    if val == 8: await message.answer("🏆 **АЧИВКА: 'Водный Король'!** 🌊")

@dp.message(F.text == "💎 Продлить Плюс (Звезды)")
async def buy_stars(message: types.Message):
    await message.answer_invoice(title="Вкусомер Плюс", description="Подписка на 30 дней", payload="sub", currency="XTR", prices=[LabeledPrice(label="Звезды", amount=150)])

@dp.pre_checkout_query()
async def checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

# --- ГЛОБАЛЬНЫЙ ЧАТ ---

@dp.message()
async def smart_chat(message: types.Message):
    if message.text == "🧘 Психолог": ctx = "psych"
    elif message.text == "🍎 Замена вредностей": await message.answer("Что вредное ты хочешь съесть? 👇"); return
    elif message.text == "👨‍🍳 Шеф: что в холодильнике?": await message.answer("Напиши список продуктов 👇"); return
    elif message.text == "🥗 Что приготовить?": await message.answer("Какое блюдо хочешь? 👇"); return
    elif message.text == "📅 Меню на месяц": ctx = "month"
    elif message.text == "🔔 Напомнить через 3ч":
        scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Пора перекусить!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
        await message.answer("✅ Будильник заведен!"); return
    else: ctx = "default"

    await message.answer_chat_action("typing")
    res = await ask_dietologist(message.from_user.id, message, ctx)
    
    # Сумматор калорий
    cals = re.findall(r"ККАЛ: (\d+)", res)
    if not cals: cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    if cals:
        u = db_query("SELECT total_today, norma FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_t = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_t, message.from_user.id))
            res += f"\n\n📈 (Записано: +{cals[0]} ккал. Всего: {new_t}/{u[1]})"

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
