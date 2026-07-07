# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
import base64
import pytz
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
import aiohttp

# --- НАСТРОЙКИ (ВСТАВЬ СВОИ ДАННЫЕ) ---
TOKEN = "8240168479:AAFdCelA83nz2eMRXbcwmlVZaThEeacRQhc"
OPENROUTER_KEY = "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"
TG_CHANNEL = "https://t.me/+YOEpXfsmd9tiODQ6"  # Ссылка на твой канал

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
moscow_tz = pytz.timezone("Europe/Moscow")

# --- БАЗА ДАННЫХ ---
def db_commit(sql, params=()):
    with sqlite3.connect('vkusomer_plus.db') as conn:
        conn.execute(sql, params); conn.commit()

def db_query(sql, params=()):
    with sqlite3.connect('vkusomer_plus.db') as conn:
        cursor = conn.cursor(); cursor.execute(sql, params)
        return cursor.fetchone()

# Создание таблиц: профиль и история
db_commit('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, norma INTEGER, total_today INTEGER, 
    water INTEGER, weight INTEGER, target INTEGER, age INTEGER, 
    height INTEGER, gender TEXT, goal TEXT, activity TEXT, last_reset TEXT)''')

db_commit('''CREATE TABLE IF NOT EXISTS history (
    user_id INTEGER, date TEXT, calories INTEGER, water INTEGER, weight INTEGER)''')

# --- СОСТОЯНИЯ ---
class UserSurvey(StatesGroup):
    gender, goal, target_w, activity, age, height, weight = [State() for _ in range(7)]

class BotModes(StatesGroup):
    chef = State()       # Режим холодильника
    psychologist = State() # Режим поддержки
    replace = State()    # Режим замены вредностей
    menu_scan = State()  # Сканер меню/чеков

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мой статус"), KeyboardButton(text="📝 Записать еду")],
        [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🥗 Что приготовить сегодня?")],
        [KeyboardButton(text="🧘 Психолог (SOS)"), KeyboardButton(text="🍎 Замена вредностей")],
        [KeyboardButton(text="📉 Прогресс"), KeyboardButton(text="💬 Просто поболтать")],
        [KeyboardButton(text="💧 +1 Стакан воды"), KeyboardButton(text="🧾 Сканер чека/меню")],
        [KeyboardButton(text="🔄 Сбросить день")]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ (БЕСПЛАТНЫЕ МОДЕЛИ) ---

async def ask_ai(user_id, message_text, mode="diet", photo_b64=None):
    # Промпты для разных ролей
    prompts = {
        "diet": "Ты Диетолог. Если юзер поел - считай ккал и БЖУ. В конце СТРОГО пиши 'ИТОГО ККАЛ: [число]'.",
        "chef": "Ты Шеф-повар. Придумывай ПП-рецепты из продуктов юзера. Пиши граммы и шаги.",
        "psych": "Ты Психолог по РПП. Поддерживай, помогай не сорваться, будь мягким.",
        "replace": "Ты эксперт по заменам. Предложи ПП-альтернативу вредной еде и добавь упражнение, чтобы 'отработать' вредность, если юзер всё же её съест.",
        "scan": "Ты сканер. Проанализируй фото меню или чека. Выдели самые полезные блюда или посчитай калории из чека."
    }

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    # Используем бесплатные модели: Gemini для фото, Gemma для текста
    model = "google/gemini-flash-1.5-8b" if photo_b64 else "google/gemma-2-9b-it:free"
    
    content = [{"type": "text", "text": message_text}]
    if photo_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}})

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompts.get(mode, prompts["diet"])},
            {"role": "user", "content": content}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                res = await resp.json()
                return res['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return "🧘 Диетолог немного занят, попробуй через минуту."

# --- ПРИВЕТСТВИЕ И ОПРОС ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "✨ **Добро пожаловать в Вкусомер Плюс!** ✨\n\n"
        "Я твой ИИ-наставник. Я умею всё: считать калории по фото и голосу, "
        "спасать от срывов, составлять рецепты из остатков и следить за твоим весом.\n\n"
        "**Как это работает:** Ты можешь просто общаться со мной как с человеком. "
        "Присылай фото тарелки, диктуй голосом или пиши текстом.\n\n"
        "Давай создадим твой профиль! **Твой пол?** 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
    await message.answer(welcome_text, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True)
    await message.answer("🎯 **Твоя цель на ближайшее время?**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await message.answer("🏁 **К какому весу ты стремишься?** (Напиши число в кг)", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
    await state.set_state(UserSurvey.target_w)

@dp.message(UserSurvey.target_w)
async def proc_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_w=int(re.findall(r"\d+", message.text)[0]))
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True)
    await message.answer("🏃‍♂️ **Твой уровень активности?**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(UserSurvey.activity)

@dp.message(UserSurvey.activity)
async def proc_act(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("🎂 **Твой полный возраст?**", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
    await state.set_state(UserSurvey.age)

@dp.message(UserSurvey.age)
async def proc_age(message: types.Message, state: FSMContext):
    await state.update_data(age=int(re.findall(r"\d+", message.text)[0]))
    await message.answer("📏 **Твой рост (см)?**", parse_mode="Markdown")
    await state.set_state(UserSurvey.height)

@dp.message(UserSurvey.height)
async def proc_h(message: types.Message, state: FSMContext):
    await state.update_data(height=int(re.findall(r"\d+", message.text)[0]))
    await message.answer("⚖️ **Твой текущий вес (кг)?**", parse_mode="Markdown")
    await state.set_state(UserSurvey.weight)

@dp.message(UserSurvey.weight)
async def survey_final(message: types.Message, state: FSMContext):
    w = int(re.findall(r"\d+", message.text)[0]); d = await state.get_data()
    # Расчет нормы (Миффлин)
    bmr = (10 * w) + (6.25 * d['height']) - (5 * d['age']) + (5 if d['gender'] == "Мужской" else -161)
    norma = int(bmr * 1.3)
    if d['goal'] == "Похудеть": norma -= 400
    
    db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, weight, target, age, height, gender, goal, activity, last_reset) VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
              (message.from_user.id, norma, w, d['target_w'], d['age'], d['height'], d['gender'], d['goal'], d['activity'], str(datetime.now(moscow_tz).date())))
    
    await message.answer("✅ **Профиль создан!** Теперь я твой личный Диетолог.", reply_markup=get_main_kb(), parse_mode="Markdown")
    await state.clear()

# --- ФУНКЦИИ КНОПОК ---

@dp.message(F.text == "📊 Мой статус")
async def show_status(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = int((u[1]/u[0])*100) if u[1]>0 else 0
        progress = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        await message.answer(f"📊 **ТВОЙ СТАТУС СЕГОДНЯ:**\n\n🍎 Еда: {u[1]} / {u[0]} ккал\n{progress} {percent}%\n💧 Вода: {u[2]} / 8 ст.\n⚖️ Вес: {u[3]} кг (Цель: {u[4]} кг)\n\nПросто напиши мне, что ты поел!", parse_mode="Markdown")

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_up(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    if u:
        new_w = u[0] + 1
        db_commit("UPDATE users SET water=? WHERE id=?", (new_w, message.from_user.id))
        await message.answer(f"💧 Стакан засчитан! ({new_w}/8)")
        if new_w == 8: await message.answer("🏆 **Достижение: 'Водный Король'!** 🌊")

@dp.message(F.text == "🔄 Сбросить день")
async def manual_reset(message: types.Message):
    db_commit("UPDATE users SET total_today=0, water=0 WHERE id=?", (message.from_user.id,))
    await message.answer("🔄 Данные за сегодня обнулены. Начинаем с чистого листа!")

# --- ГЛОБАЛЬНЫЙ ОБРАБОТЧИК (ГОЛОС, ФОТО, ТЕКСТ) ---

@dp.message()
async def main_handler(message: types.Message, state: FSMContext):
    # Смена режимов через текст
    if message.text == "👨‍🍳 Шеф: что в холодильнике?":
        await state.set_state(BotModes.chef); await message.answer("Пришли фото продуктов или напиши их списком 👇"); return
    elif message.text == "🧘 Психолог (SOS)":
        await state.set_state(BotModes.psychologist); await message.answer("Я тебя слушаю. Что тебя беспокоит? 🤗"); return
    elif message.text == "🍎 Замена вредностей":
        await state.set_state(BotModes.replace); await message.answer("Что вредное хочешь съесть? Подберу ПП-замену!"); return
    elif message.text == "🧾 Сканер чека/меню":
        await state.set_state(BotModes.menu_scan); await message.answer("Пришли фото чека из магазина или меню из кафе 👇"); return
    
    current_mode = await state.get_state()
    ai_mode = "diet"
    if current_mode == BotModes.chef: ai_mode = "chef"
    elif current_mode == BotModes.psychologist: ai_mode = "psych"
    elif current_mode == BotModes.replace: ai_mode = "replace"
    elif current_mode == BotModes.menu_scan: ai_mode = "scan"

    await bot.send_chat_action(message.chat.id, "typing")
    
    # Обработка фото
    photo_b64 = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        file_data = await bot.download_file(file.file_path)
        photo_b64 = base64.b64encode(file_data.read()).decode('utf-8')

    # Обработка голоса
    text_to_ai = message.text or message.caption or "Анализ"
    if message.voice:
        await message.answer("👂 Расшифровываю твой голос...")
        # Gemini умеет понимать контекст из аудио промптов через мультимодальность
        text_to_ai = "Это голосовое сообщение. Разбери, что там сказано о еде и ответь."

    res = await ask_ai(message.from_user.id, text_to_ai, ai_mode, photo_b64)
    
    # Если это диетолог, вытаскиваем калории
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    if not cals: cals = re.findall(r"ККАЛ: (\d+)", res)
    
    if cals:
        u = db_query("SELECT total_today FROM users WHERE id=?", (message.from_user.id,))
        if u:
            new_total = u[0] + int(cals[0])
            db_commit("UPDATE users SET total_today=? WHERE id=?", (new_total, message.from_user.id))
            res += f"\n\n📈 **Записано:** +{cals[0]} ккал. (Всего: {new_total})"

    await message.answer(res, reply_markup=get_main_kb())
    if current_mode: await state.clear()

# --- АВТОМАТИЧЕСКИЙ СБРОС В 00:00 ---
async def reset_all_users():
    db_commit("UPDATE users SET total_today=0, water=0")
    logging.info("Глобальный сброс калорий выполнен.")

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    scheduler.add_job(reset_all_users, "cron", hour=0, minute=0)
    scheduler.start()
    threading.Thread(target=run_flask, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
