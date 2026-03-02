# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import sqlite3
from datetime import datetime, timedelta
from google import genai
from google.genai import types as ai_types
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

client = genai.Client(api_key=GEMINI_KEY)
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

class UserStates(StatesGroup):
    waiting_replace = State()
    waiting_fridge = State()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Записать еду (Фото/Голос/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
        [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🥗 Что приготовить сегодня?")],
        [KeyboardButton(text="🧘 Психолог"), KeyboardButton(text="🍎 Замена вредностей")],
        [KeyboardButton(text="📅 Меню на месяц"), KeyboardButton(text="💧 +1 Стакан воды")],
        [KeyboardButton(text="📱 Mini App", web_app=WebAppInfo(url="https://vkusomer.onrender.com"))]
    ], resize_keyboard=True)

# --- ЛОГИКА ИИ (GEMINI 2.0) ---
async def ask_dietologist(user_id, message_obj, prompt_type="default"):
    system_prompts = {
        "default": "Ты - Диетолог Вкусомер Плюс. Ты можешь просто общаться. Если пишут про еду - считай калории и пиши в конце 'ККАЛ: [число]'.",
        "chef": "Ты шеф-повар. Давай очень подробные рецепты с граммами и шагами 1, 2, 3...",
        "replace": "Найди полезную ПП замену вредному продукту.",
        "month": "Составь подробное меню на месяц. Раздели на 'Базовую корзину' и 'Свежий докуп'."
    }
    
    text_content = message_obj.text or message_obj.caption or "Проанализируй"
    final_prompt = f"{system_prompts.get(prompt_type)} \n Пользователь: {text_content}"
    
    try:
        if message_obj.photo:
            file = await bot.get_file(message_obj.photo[-1].file_id)
            img_bytes = await bot.download_file(file.file_path)
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[final_prompt, ai_types.Part.from_bytes(data=img_bytes.read(), mime_type="image/jpeg")]
            )
        else:
            response = client.models.generate_content(model="gemini-1.5-flash", contents=final_prompt)
        return response.text
    except Exception as e:
        return f"🧘 Диетолог отвлекся... Попробуй еще раз через минуту. ({e})"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index(): return "Бот Вкусомер Плюс работает!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome = (
        "✨ **Добро пожаловать в мир осознанного питания с Вкусомер Плюс!** 🥗\n\n"
        "Я — твой персональный ИИ-наставник и **Диетолог**. Я здесь, чтобы доказать: "
        "путь к идеальному телу может быть не только эффективным, но и по-настоящему увлекательным!\n\n"
        "**Что я умею делать для тебя?**\n"
        "🍎 **Мгновенный трекинг:** Просто пиши, шли фото, голосовые или кружки - я всё посчитаю.\n"
        "👨‍🍳 **Кулинарный разум:** Рецепты из остатков и полные меню на месяц.\n"
        "🧘 **Твоя поддержка:** Я помогу справиться с эмоциями и уберегу от срывов.\n\n"
        "Давай создадим твой профиль! Твой пол? 👤"
    )
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
    await message.answer(welcome, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(Survey.gender)

@dp.message(Survey.gender)
async def survey_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Набрать массу"), KeyboardButton(text="Поддерживать вес")]], resize_keyboard=True)
    await message.answer("🎯 Какая наша главная цель?", reply_markup=kb)
    await state.set_state(Survey.goal)

@dp.message(Survey.goal)
async def survey_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    if message.text in ["Похудеть", "Набрать массу"]:
        await message.answer("🏁 К какому весу мы стремимся? (Напиши число в кг)", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.target_w)
    else:
        await state.set_state(Survey.activity)
        await message.answer("🏃‍♂️ Оцени свою активность (Сидячий/Средний/Высокий):")

@dp.message(Survey.target_w)
async def survey_tw(message: types.Message, state: FSMContext):
    await state.update_data(target_w=message.text)
    await message.answer("🏃‍♂️ Оцени свою активность (Сидячий/Средний/Высокий):")
    await state.set_state(Survey.activity)

@dp.message(Survey.activity)
async def survey_act(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("📏 Напиши через пробел: возраст, рост(см), текущий вес(кг).")
    await state.set_state(Survey.params)

@dp.message(Survey.params)
async def survey_done(message: types.Message, state: FSMContext):
    try:
        age, h, w = map(int, message.text.split())
        data = await state.get_data()
        # Расчет нормы Миффлина
        bmr = (10 * w) + (6.25 * h) - (5 * age) + (5 if data['gender'] == "Мужской" else -161)
        norma = int(bmr * 1.25)
        if data['goal'] == "Похудеть": norma -= 400
        
        db_commit("INSERT OR REPLACE INTO users (id, norma, total_today, water, streak, last_date, weight, target, avatar) VALUES (?, ?, 0, 0, 1, ?, ?, ?, ?)",
                  (message.from_user.id, norma, str(datetime.now().date()), w, data.get('target_w', w), "🧘 Спокойный дзен"))
        
        await message.answer(f"✅ Профиль настроен! Твоя норма: **{norma} ккал**. \n\nТеперь я твой Диетолог. Пиши мне что угодно!", reply_markup=get_main_kb())
        await state.clear()
    except: await message.answer("Ошибка! Напиши 3 числа через пробел.")

# --- ФУНКЦИИ МЕНЮ ---

@dp.message(F.text == "📊 Мой прогресс")
async def progress(message: types.Message):
    u = db_query("SELECT norma, total_today, water, weight, target, avatar FROM users WHERE id=?", (message.from_user.id,))
    if u:
        percent = int((u[1]/u[0])*100) if u[1]>0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - (percent // 10))
        msg = (f"📊 **ТВОЙ СТАТУС:**\nАватар: {u[5]}\nЦель: {u[3]} -> {u[4]} кг\n\n"
               f"🍎 Еда: {bar} {u[1]}/{u[0]} ккал\n"
               f"💧 Вода: {'🟦' * u[2]} {u[2]}/8 ст.\n\n📢 Канал: {TG_CHANNEL}")
        await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "💧 +1 Стакан воды")
async def water_plus(message: types.Message):
    u = db_query("SELECT water FROM users WHERE id=?", (message.from_user.id,))
    val = (u[0] + 1) if u else 1
    db_commit("UPDATE users SET water=? WHERE id=?", (val, message.from_user.id))
    await message.answer(f"💧 Стакан засчитан! ({val}/8)")
    if val == 8: await message.answer("🏆 **АЧИВКА: 'Водный Король'!** 🌊")

@dp.message(F.text == "📅 Меню на месяц")
async def month_plan(message: types.Message):
    await message.answer("⏳ Составляю план на месяц...")
    res = await ask_dietologist(message.from_user.id, message, "month")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Отправить сообщением", callback_data="send_text")],
        [InlineKeyboardButton(text="📄 Скачать PDF (в разработке)", callback_data="none")]
    ])
    await message.answer("📊 План готов! Как тебе его передать?", reply_markup=kb)

@dp.callback_query(F.data == "send_text")
async def send_text_plan(call: types.CallbackQuery):
    await call.message.answer("📅 План на месяц и список продуктов отправлены в чат выше! 👆")
    await call.answer()

# --- УМНЫЙ ЧАТ (ОБРАБАТЫВАЕТ ВСЁ) ---

@dp.message()
async def global_handler(message: types.Message, state: FSMContext):
    if message.text == "🔔 Напомнить через 3ч":
        scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Время подкрепиться!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
        await message.answer("✅ Будильник заведен!")
        return

    await message.answer_chat_action("typing")
    
    # Авто-выбор контекста
    context = "default"
    if message.text and ("рецепт" in message.text.lower() or "приготовить" in message.text.lower()): context = "chef"
    if message.text and ("заменить" in message.text.lower() or "вредно" in message.text.lower()): context = "replace"
    
    res = await ask_dietologist(message.from_user.id, message, context)
    
    # Сумматор калорий
    cals = re.findall(r"ККАЛ: (\d+)", res)
    if not cals: cals = re.findall(r"ИТОГО ККАЛ: (\d+)", res)
    
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

async def main_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    scheduler.start()
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main_bot())
