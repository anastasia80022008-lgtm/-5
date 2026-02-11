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

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GROQ_API_KEY = "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"

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
    [KeyboardButton(text="🔔 Напомнить поесть через 3ч")]
], resize_keyboard=True)

gender_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Поддерживать вес"), KeyboardButton(text="Набрать массу")]], resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средняя активность"), KeyboardButton(text="Высокая активность")]], resize_keyboard=True)

# --- ИИ ФУНКЦИЯ ---
async def ask_vkusomer_ai(prompt, photo_bytes=None):
    try:
        system_msg = "Ты ИИ-диетолог Вкусомер Плюс. В конце ответа ВСЕГДА пиши строго: 'ИТОГО ККАЛ: [число]'."
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
    await message.answer("✨ Привет! Я Вкусомер Плюс.\nПрежде чем начать, давай рассчитаем твою норму калорий.\n\nВыбери свой пол:", reply_markup=gender_kb)
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def process_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    await message.answer("Какая у тебя цель?", reply_markup=goal_kb)
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def process_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await message.answer("Твой уровень активности?", reply_markup=activity_kb)
    await state.set_state(UserSurvey.activity)

@dp.message(UserSurvey.activity)
async def process_activity(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    await message.answer("Сколько тебе полных лет?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserSurvey.age)

@dp.message(UserSurvey.age)
async def process_age(message: types.Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    await message.answer("Введи свой рост (в см):")
    await state.set_state(UserSurvey.height)

@dp.message(UserSurvey.height)
async def process_height(message: types.Message, state: FSMContext):
    await state.update_data(height=int(message.text))
    await message.answer("Введи свой текущий вес (в кг):")
    await state.set_state(UserSurvey.weight)

@dp.message(UserSurvey.weight)
async def process_weight(message: types.Message, state: FSMContext):
    await state.update_data(weight=int(message.text))
    await message.answer("Введи свой желаемый вес (цель в кг):")
    await state.set_state(UserSurvey.target_weight)

@dp.message(UserSurvey.target_weight)
async def process_target(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, h, a, gender = data['weight'], data['height'], data['age'], data['gender']
    
    # Формула Миффлина-Сан Жеора
    bmr = (10 * w) + (6.25 * h) - (5 * a)
    bmr += 5 if gender == "Мужской" else -161
    
    act_map = {"Сидячий": 1.2, "Средняя активность": 1.55, "Высокая активность": 1.725}
    norma = bmr * act_map.get(data['activity'], 1.2)
    
    if data['goal'] == "Похудеть": norma -= 400
    elif data['goal'] == "Набрать массу": norma += 400
    
    await state.update_data(daily_limit=int(norma), total_today=0, last_date=str(datetime.now().date()))
    
    await message.answer(f"✅ Расчет окончен!\n\nТвоя норма: **{int(norma)} ккал/день**.\nЯ буду следить за твоим балансом.\n\nТеперь мы можем общаться!", reply_markup=main_kb)
    await state.set_state(None)

# --- ИИ-ОБРАБОТЧИКИ (ОСТАЛЬНЫЕ ФУНКЦИИ) ---

@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото тарелки или напиши, что ты съел! 📸")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    total_today = data.get('total_today', 0) if data.get('last_date') == str(datetime.now().date()) else 0
    
    await message.answer("🔍 Вкусомер анализирует...")
    photo_data = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_io = await bot.download_file(file.file_path)
        photo_data = photo_io.read()
        prompt = "Определи еду на фото и её калорийность."
    else:
        prompt = f"Я съел: {message.text}. Оцени калории."

    ai_reply = await ask_vkusomer_ai(prompt, photo_data)
    found_cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(found_cals[0]) if found_cals else 0
    total_today += new_cals
    
    await state.update_data(total_today=total_today, last_date=str(datetime.now().date()))
    await message.answer(f"✅ {ai_reply}\n\n📊 Сегодня: {total_today} / {data['daily_limit']} ккал", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 0), data.get('target_weight', 0)
    days = int((abs(w - tw) * 7700) / 500)
    await message.answer(f"📊 Текущий вес: {w}кг → Цель: {tw}кг\n🔮 Прогноз: цель будет достигнута через **{days} дней**!")

@dp.message(F.text == "🧘 Психолог")
async def psych_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 ХОЧУ СОРВАТЬСЯ!", callback_data="stop_binge")]])
    await message.answer("Нажми кнопку, если чувствуешь риск срыва.", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def stop_binge(callback: types.CallbackQuery):
    res = await ask_vkusomer_ai("Я хочу сорваться. Помоги мне.")
    await callback.message.answer(f"🧘 {res}\n\n🥤 Выпей воды и подожди 5 мин.")
    await callback.answer()

@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def chef_start(message: types.Message, state: FSMContext):
    await message.answer("Что у тебя есть? Напиши список:")
    await state.set_state(UserStates.waiting_fridge)

@dp.message(UserStates.waiting_fridge)
async def chef_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Придумай рецепт из: {message.text}")
    await message.answer(f"👨‍🍳 **Рецепт:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "🔔 Напомнить поесть через 3ч")
async def set_alarm(message: types.Message):
    scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Время подкрепиться!"), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
    await message.answer("✅ Напомню через 3 часа!")

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
