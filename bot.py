# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
import json
import aiohttp
from datetime import datetime
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton
)

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
OPENROUTER_KEY = "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" 
TG_CHANNEL = "https://t.me/+YOEpXfsmd9tiODQ6"
PAID_BOT = "https://t.me/TasteMeterPlus_bot"

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
        cursor = conn.cursor()
        cursor.execute(sql, params)
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
        [KeyboardButton(text="💬 Просто поболтать"), KeyboardButton(text="🔔 Напомнить через 3ч")],
        [KeyboardButton(text="💧 +1 Стакан воды"), KeyboardButton(text="🧾 Сканер чека")]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ (OpenRouter) ---
async def ask_dietologist(user_id, user_text, system_type="default"):
    prompts = {
        "default": "Ты - Диетолог Вкусомер Плюс. Общайся вежливо. Если пишут про еду - считай калории и пиши в конце СТРОГО: 'ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Давай подробные рецепты с граммами и шагами приготовления.",
        "psych": "Ты психолог. Поддержи пользователя, помоги не сорваться на вредное.",
        "month": "Составь подробное меню на месяц. Список продуктов и план блюд."
    }

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    payload = {
        "model": "google/gemma-2-9b-it:free",
        "messages": [
            {"role": "system", "content": prompts.get(system_type, prompts["default"])},
            {"role": "user", "content": user_text}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    res_json = await response.json()
                    return res_json['choices'][0]['message']['content']
                else:
                    return "🧘 Диетолог задумался... Попробуй позже."
    except Exception as e:
        return f"🧘 Ошибка связи: {e}"

# --- АНКЕТА ---

@app.route('/')
def index(): return "Бот работает!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome = (
        "✨ **Добро пожаловать в мир осознанного питания с Вкусомер Плюс!** 🥗\n\n"
        "Я — твой персональный ИИ-наставник и **Диетолог**. Пройди тест, чтобы я рассчитал твою норму.\n\n"
        "Твой пол? 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(welcome, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🎯 Какая наша главная цель?", reply_markup=kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Набрать массу"]:
        await message.answer("🏁 К какому весу мы стремимся? (кг)", reply_markup=ReplyKeyboardRemove())
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
    w = int(message.text); data = await state.get_data()
    bmr = (10 * w) + (6.25 * data['height']) - (5 * data['age']) + (5 if data['gender'] == "Мужской" else -161)
    norma = int(bmr * 1.3)
    if data['goal'] == "Похудеть": norma -= 400
    
    db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, last_date, weight, target) VALUES (?, ?, 0, 0, ?, ?, ?)",
              (message.from_user.id, norma, str(datetime.now().date()), w, data.get('target_w', w)))
    
    await message.answer("✅ **Твой профиль успешно создан! Тест пройден.**")
    await message.answer(f"Твоя норма: **{norma} ккал**. Теперь просто пиши мне всё, что хочешь!", reply_markup=get_main_kb())
    await state.clear()

# --- КНОПКИ МЕНЮ ---

@dp.message(F.text == "📊 Мой статус")
async def show_status(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = min(int((u[1]/u[0])*100), 100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **ТВОЙ СТАТУС:**\nВес: {u[3]} -> {u[4]} кг\n\n🍎 Еда: {bar} {u[1]}/{u[0]} ккал\n💧 Вода: {u[2]}/8 ст.\n\n📢 Канал: {TG_CHANNEL}")

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_up(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    if val == 8: await message.answer("🏆 **АЧИВКА: 'Водный Король'!** 🌊")
    else: await message.answer(f"💧 Стакан засчитан! ({val}/8)")

@dp.message(F.text == "📅 Меню на месяц")
async def month_plan(message: types.Message):
    await message.answer("⏳ Диетолог составляет стратегию на месяц...")
    res = await ask_dietologist(message.from_user.id, message.text, "month")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📩 Отправить в чат", callback_data="send_text")]])
    await message.answer("План готов! Как получить?", reply_markup=kb)

@dp.callback_query(F.data == "send_text")
async def send_text_plan(call: types.CallbackQuery):
    await call.message.answer("📅 Полный список продуктов и меню отправлены выше! 👆")
    await call.answer()

# --- ГЛОБАЛЬНЫЙ УМНЫЙ ЧАТ ---

@dp.message()
async def global_handler(message: types.Message):
    # Приоритет кнопок
    if message.text == "🧘 Психолог": ctx = "psych"
    elif message.text == "🍎 Замена вредностей": await message.answer("Напиши вредный продукт 👇"); return
    elif message.text == "👨‍🍳 Шеф: что в холодильнике?": await message.answer("Напиши список продуктов 👇"); return
    elif message.text == "🥗 Что приготовить сегодня?": await message.answer("Напиши пожелание 👇"); return
    elif message.text == "💬 Просто поболтать": await message.answer("Я тебя слушаю! 😊"); return
    elif message.text == "🔔 Напомнить через 3ч":
        scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Пора поесть!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
        await message.answer("✅ Напомню!"); return
    else: ctx = "default"

    await message.answer_chat_action("typing")
    res = await ask_dietologist(message.from_user.id, message.text, ctx)
    
    # Сумматор калорий
    cals = re.findall(r"ККАЛ: (\d+)", res)
    if cals:
        u = db_query("SELECT total_today, norma FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_total = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_total, message.from_user.id))
            res += f"\n\n📈 (Записано: +{cals[0]} ккал. Всего: {new_total}/{u[1]})"

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
