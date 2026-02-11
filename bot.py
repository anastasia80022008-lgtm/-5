# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import base64
from datetime import datetime
from flask import Flask
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# --- НАСТРОЙКИ (ВАШИ КЛЮЧИ) ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GROQ_API_KEY = "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"
TELEGRAM_CHANNEL_URL = "https://t.me/+YOEpXfsmd9tiODQ6"
PAID_BOT_URL = "https://t.me/TasteMeterPlus_bot"

client = Groq(api_key=GROQ_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- СОСТОЯНИЯ ---
class UserSurvey(StatesGroup):
    gender = State()
    goal = State()
    activity = State()
    age = State()
    height = State()
    weight = State()
    target_weight = State()

class UserStates(StatesGroup):
    waiting_food = State()
    waiting_fridge = State()
    waiting_replace = State()
    waiting_receipt = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🧘 Психолог")],
    [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="🧾 Сканер чека")],
    [KeyboardButton(text="🔔 Напомнить через 3ч")]
], resize_keyboard=True)

gender_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Поддерживать вес"), KeyboardButton(text="Набрать массу")]], resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средняя активность"), KeyboardButton(text="Высокая активность")]], resize_keyboard=True)

# --- ИИ ФУНКЦИЯ ---
async def ask_ai(prompt, photo_bytes=None):
    try:
        system_msg = "Ты ИИ-диетолог Вкусомер Плюс. Если считаешь калории, в конце ВСЕГДА пиши строго: 'ИТОГО ККАЛ: [число]'. Будь кратким."
        if photo_bytes:
            base64_image = base64.b64encode(photo_bytes).decode('utf-8')
            completion = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[{"role": "system", "content": system_msg},
                          {"role": "user", "content": [{"type": "text", "text": prompt},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]
            )
        else:
            completion = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}]
            )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ОБРАБОТЧИКИ АНКЕТЫ ---

@app.route('/')
def index():
    return "Vkusomer Plus is Active!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✨ Привет! Я Вкусомер Плюс. Давай рассчитаем твою норму.\nВыбери свой пол:", reply_markup=gender_kb)
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    await message.answer("Твоя цель?", reply_markup=goal_kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await message.answer("Уровень активности?", reply_markup=activity_kb)
    await state.set_state(UserSurvey.activity)

@dp.message(UserSurvey.activity)
async def proc_act(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("Возраст:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserSurvey.age)

@dp.message(UserSurvey.age)
async def proc_age(message: types.Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    await message.answer("Рост (см):")
    await state.set_state(UserSurvey.height)

@dp.message(UserSurvey.height)
async def proc_h(message: types.Message, state: FSMContext):
    await state.update_data(height=int(message.text))
    await message.answer("Текущий вес (кг):")
    await state.set_state(UserSurvey.weight)

@dp.message(UserSurvey.weight)
async def proc_w(message: types.Message, state: FSMContext):
    await state.update_data(weight=int(message.text))
    await message.answer("Желаемый вес (кг):")
    await state.set_state(UserSurvey.target_weight)

@dp.message(UserSurvey.target_weight)
async def proc_target(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, h, a, gender = data['weight'], data['height'], data['age'], data['gender']
    bmr = (10 * w) + (6.25 * h) - (5 * a) + (5 if gender == "Мужской" else -161)
    norma = int(bmr * {"Сидячий": 1.2, "Средняя активность": 1.55, "Высокая активность": 1.725}.get(data['activity'], 1.2))
    if data['goal'] == "Похудеть": norma -= 400
    elif data['goal'] == "Набрать массу": norma += 400
    
    await state.update_data(daily_limit=norma, total_today=0, last_date=str(datetime.now().date()), goal_weight=int(message.text))
    await message.answer(f"✅ Готово! Твоя норма: **{norma} ккал/день**.\nТеперь я буду считать всё, что ты ешь.", reply_markup=main_kb)
    await state.set_state(None)

# --- ГЛАВНЫЕ ФУНКЦИИ ---

@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото тарелки или напиши, что ты съел! 📸")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Анализирую...")
    photo_data = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_io = await bot.download_file(file.file_path)
        photo_data = photo_io.read()
        ai_reply = await ask_ai("Что на фото? Оцени калории.", photo_data)
    else:
        ai_reply = await ask_ai(f"Я съел: {message.text}. Оцени калории.")

    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(cals[0]) if cals else 0
    total_today += new_cals
    
    await state.update_data(total_today=total_today, last_date=today)
    await message.answer(f"{ai_reply}\n\n📊 Итого за день: {total_today} / {data['daily_limit']} ккал", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "📊 Мой прогресс")
async def progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 0), data.get('goal_weight', 0)
    days = int((abs(w - tw) * 7700) / 500)
    await message.answer(f"📊 Текущий вес: {w}кг → Цель: {tw}кг\n🔮 Результат будет через **~{days} дней**!")

@dp.message(F.text == "🧘 Психолог")
async def psych(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 СТОП СРЫВ!", callback_data="stop_b")]])
    await message.answer("Срыв начинается в голове. Нажми кнопку, если трудно.", reply_markup=kb)

@dp.callback_query(F.data == "stop_b")
async def stop_b(callback: types.CallbackQuery):
    res = await ask_ai("Я хочу сорваться. Помоги мне остановиться.")
    await callback.message.answer(f"🧘 {res}\n\n🥤 Выпей воды и напиши мне через 5 минут.")
    await callback.answer()

@dp.message(F.text == "🔔 Напомнить через 3ч")
async def set_alarm(message: types.Message):
    scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Время подкрепиться!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
    await message.answer("✅ Напомню через 3 часа!")

@dp.message(F.text == "🧾 Сканер чека")
async def receipt_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото чека! 🛒")
    await state.set_state(UserStates.waiting_receipt)

@dp.message(UserStates.waiting_receipt, F.photo)
async def receipt_proc(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.photo[-1].file_id)
    photo_io = await bot.download_file(file.file_path)
    res = await ask_ai("Проанализируй чек на полезность продуктов.", photo_io.read())
    await message.answer(f"🧾 {res}\n\n📢 Наш канал: {TELEGRAM_CHANNEL_URL}\n💎 Плюс: {PAID_BOT_URL}")
    await state.set_state(None)

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
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
