# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
import json
import aiohttp
import base64
from datetime import datetime
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAFdCelA83nz2eMRXbcwmlVZaThEeacRQhc"
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
    water INTEGER, streak INTEGER, last_date TEXT, 
    weight INTEGER, target INTEGER, avatar TEXT, activity TEXT)''')

# --- СОСТОЯНИЯ ---
class UserSurvey(StatesGroup):
    gender, goal, target_w, activity, age, height, weight = [State() for _ in range(7)]

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мой статус"), KeyboardButton(text="📝 Записать еду")],
        [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🥗 Что приготовить сегодня?")],
        [KeyboardButton(text="🧘 Психолог"), KeyboardButton(text="🍎 Замена вредностей")],
        [KeyboardButton(text="📅 Меню на месяц"), KeyboardButton(text="💬 Просто поболтать")],
        [KeyboardButton(text="🔔 Напомнить через 3ч"), KeyboardButton(text="💧 +1 Стакан воды")],
        [KeyboardButton(text="🧾 Сканер чека")]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ ---
async def ask_dietologist(user_id, user_text, system_type="default", photo_b64=None):
    prompts = {
        "default": "Ты - Диетолог Вкусомер Плюс. Общайся вежливо. Если пишут про еду - считай калории и пиши в конце СТРОГО: 'ИТОГО ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Давай очень подробные рецепты с ингредиентами, граммами и шагами 1, 2, 3.",
        "psych": "Ты психолог. Поддержи пользователя, помоги не сорваться на вредную еду.",
        "month": "Составь меню на месяц. Раздели на 'Базовую корзину' и 'Еженедельный докуп'. Напиши блюда подробно."
    }
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    messages = [{"role": "system", "content": prompts.get(system_type, prompts["default"])}]
    
    if photo_b64:
        messages.append({"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}}
        ]})
        model = "google/gemini-flash-1.5-8b"
    else:
        messages.append({"role": "user", "content": user_text})
        model = "google/gemma-2-9b-it:free"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json={"model": model, "messages": messages}) as resp:
                res_json = await resp.json()
                return res_json['choices'][0]['message']['content']
    except:
        return "🧘 Диетолог отвлекся... Попробуй еще раз через минуту."

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index(): return "Vkusomer Plus Active!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome = (
        "✨ **Добро пожаловать в мир осознанного питания с Вкусомер Плюс!** 🥗\n\n"
        "Я — твой персональный ИИ-наставник и **Диетолог**. Я докажу, что путь к телу мечты — это вкусно и легко! 💪\n\n"
        "Твой пол? 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
    await message.answer(welcome, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True)
    await message.answer("🎯 Какая наша главная цель?", reply_markup=kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Набрать массу"]:
        await message.answer("🏁 Какой вес твоя цель? (кг)", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserSurvey.target_w)
    else:
        await state.set_state(UserSurvey.activity)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True)
        await message.answer("🏃‍♂️ Твоя активность?", reply_markup=kb)

@dp.message(UserSurvey.target_w)
async def proc_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_w=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True)
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
async def survey_final(message: types.Message, state: FSMContext):
    w = int(message.text); d = await state.get_data()
    bmr = (10 * w) + (6.25 * d['height']) - (5 * d['age']) + (5 if d['gender'] == "Мужской" else -161)
    norma = int(bmr * 1.3)
    if d['goal'] == "Похудеть": norma -= 400
    
    db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, streak, last_date, weight, target, avatar) VALUES (?, ?, 0, 0, 1, ?, ?, ?, ?)",
              (message.from_user.id, norma, str(datetime.now().date()), w, d.get('target_w', w), "🧘 Спокойный дзен"))
    
    await message.answer("✅ **Твой профиль успешно создан! Тест пройден.**")
    await message.answer(f"Твоя норма: **{norma} ккал**. Пиши мне или жми кнопки!", reply_markup=get_main_kb())
    await state.clear()

# --- КНОПКИ ---

@dp.message(F.text == "📊 Мой статус")
async def show_status(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = int((u[1]/u[0])*100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **ТВОЙ СТАТУС:**\nЦель: {u[3]} -> {u[4]} кг\n\n🍎 Еда: {bar} {u[1]}/{u[0]} ккал\n💧 Вода: {'🟦' * u[2]} {u[2]}/8 стаканов\n\n📢 Канал: {TG_CHANNEL}")

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_up(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    if val == 8: await message.answer("🏆 **АЧИВКА: 'Водный Король'!** 🌊")
    else: await message.answer(f"💧 Стакан засчитан! ({val}/8)")

@dp.message(F.text == "📅 Меню на месяц")
async def month_plan(message: types.Message):
    await message.answer("⏳ Составляю стратегию на месяц...")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Отправить сообщением", callback_data="send_text")],
        [InlineKeyboardButton(text="📄 Скачать PDF (в работе)", callback_data="none")]
    ])
    await message.answer("План готов! Как тебе его передать?", reply_markup=kb)

@dp.callback_query(F.data == "send_text")
async def send_month_text(call: types.CallbackQuery):
    res = await ask_dietologist(call.from_user.id, "Составь меню на месяц", "month")
    await call.message.answer(res)
    await call.answer()

# --- УМНЫЙ ЧАТ ---

@dp.message()
async def global_handler(message: types.Message):
    # ПРИОРИТЕТ КНОПОК
    if message.text == "🧘 Психолог": ctx = "psych"
    elif message.text == "👨‍🍳 Шеф: что в холодильнике?": await message.answer("Напиши продукты через запятую 👇"); return
    elif message.text == "🍎 Замена вредностей": await message.answer("Что вредное хочешь съесть? 👇"); return
    elif message.text == "🥗 Что приготовить сегодня?": ctx = "chef"
    elif message.text == "💬 Просто поболтать": await message.answer("Я тебя слушаю! 😊"); return
    elif message.text == "📝 Записать еду": await message.answer("Пришли фото тарелки или напиши текстом! 📸"); return
    elif message.text == "🧾 Сканер чека": await message.answer("Пришли фото чека! 🛒"); return
    elif message.text == "🔔 Напомнить через 3ч":
        scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Пора поесть!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
        await message.answer("✅ Напомню!"); return
    else: ctx = "default"

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    photo_b64 = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        data = await bot.download_file(file.file_path)
        photo_b64 = base64.b64encode(data.read()).decode('utf-8')

    res = await ask_dietologist(message.from_user.id, message.text or message.caption or "Анализ", ctx, photo_b64)
    
    # Сумматор калорий
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    if not cals: cals = re.findall(r"ККАЛ: (\d+)", res)
    if cals:
        u = db_query("SELECT total_today, norma FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_t = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_t, message.from_user.id))
            res += f"\n\n📈 (Записано: +{cals[0]} ккал. Итого за день: {new_t}/{u[1]})"

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
