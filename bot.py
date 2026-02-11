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
    waiting_recipe_idea = State()
    waiting_chat = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🥗 Что приготовить сегодня?")],
    [KeyboardButton(text="🧘 Психолог"), KeyboardButton(text="🍎 Замена вредностей")],
    [KeyboardButton(text="💬 Просто поболтать"), KeyboardButton(text="🔔 Напомнить через 3ч")],
    [KeyboardButton(text="🧾 Сканер чека")]
], resize_keyboard=True)

chat_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Выйти из чата")]], resize_keyboard=True)

# --- ИИ ФУНКЦИЯ ---
async def ask_ai(prompt, photo_bytes=None, system_context="Ты эксперт-диетолог Вкусомер Плюс."):
    try:
        sys_prompt = system_context + " Если считаешь калории, в конце ВСЕГДА пиши: 'ИТОГО ККАЛ: [число]'. Будь кратким."
        if photo_bytes:
            base64_image = base64.b64encode(photo_bytes).decode('utf-8')
            completion = client.chat.completions.create(
                model="llama-3.2-90b-vision-preview",
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": [{"type": "text", "text": prompt},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]
            )
        else:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]
            )
        return completion.choices[0].message.content
    except Exception as e:
        return f"🧘 Ошибка нейросети. Попробуй позже. ({e})"

# --- ОБРАБОТЧИКИ АНКЕТЫ ---

@app.route('/')
def index():
    return "Vkusomer Plus is Active!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✨ Привет! Я Вкусомер Плюс.\nРассчитаем твою норму калорий.\n\nТвой пол:", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True))
    await state.set_state(UserSurvey.gender)

@dp.message(UserSurvey.gender)
async def proc_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    await message.answer("Твоя цель?", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Похудеть"), KeyboardButton(text="Поддержать вес"), KeyboardButton(text="Набрать массу")]], resize_keyboard=True))
    await state.set_state(UserSurvey.goal)

@dp.message(UserSurvey.goal)
async def proc_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await message.answer("Уровень активности?", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Сидячий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]], resize_keyboard=True))
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
    await message.answer("Вес (кг):")
    await state.set_state(UserSurvey.weight)

@dp.message(UserSurvey.weight)
async def proc_w(message: types.Message, state: FSMContext):
    await state.update_data(weight=int(message.text))
    await message.answer("Желаемый вес (кг):")
    await state.set_state(UserSurvey.target_weight)

@dp.message(UserSurvey.target_weight)
async def proc_target(message: types.Message, state: FSMContext):
    target_w = int(message.text)
    data = await state.get_data()
    w, h, a, gen = data['weight'], data['height'], data['age'], data['gender']
    bmr = (10 * w) + (6.25 * h) - (5 * a) + (5 if gen == "Мужской" else -161)
    norma = int(bmr * 1.2) # Упрощенно
    if data['goal'] == "Похудеть": norma -= 400
    
    await state.update_data(daily_limit=norma, total_today=0, last_date=str(datetime.now().date()), goal_weight=target_w)
    await message.answer(f"✅ Готово! Твоя норма: **{norma} ккал/день**.", reply_markup=main_kb)
    await state.set_state(None)

# --- ГЛАВНЫЕ ФУНКЦИИ ---

@dp.message(F.text == "💬 Просто поболтать")
async def chat_start(message: types.Message, state: FSMContext):
    await message.answer("Я тебя слушаю! Спрашивай что угодно. 😊", reply_markup=chat_kb)
    await state.set_state(UserStates.waiting_chat)

@dp.message(UserStates.waiting_chat)
async def chat_proc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Выйти из чата":
        await message.answer("Возвращаюсь в меню.", reply_markup=main_kb)
        await state.set_state(None)
        return
    res = await ask_ai(message.text, system_context="Ты дружелюбный ИИ-диетолог. Общайся свободно.")
    await message.answer(res)

@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото тарелки или напиши текстом! 📸🍎")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Вкусомер анализирует...")
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
    total += new_cals
    
    await state.update_data(total_today=total, last_date=today)
    await message.answer(f"{ai_reply}\n\n📊 Итог дня: {total} / {data.get('daily_limit', 2000)} ккал", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def chef_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши продукты, которые у тебя есть:")
    await state.set_state(UserStates.waiting_fridge)

@dp.message(UserStates.waiting_fridge)
async def chef_proc(message: types.Message, state: FSMContext):
    res = await ask_ai(f"Придумай ПП рецепт из этого: {message.text}", system_context="Ты шеф-повар.")
    await message.answer(f"👨‍🍳 {res}", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "🥗 Что приготовить сегодня?")
async def recipe_idea_start(message: types.Message, state: FSMContext):
    await message.answer("Какое блюдо ты хочешь? (Например: 'лёгкий ужин' или 'завтрак из яиц')")
    await state.set_state(UserStates.waiting_recipe_idea)

@dp.message(UserStates.waiting_recipe_idea)
async def recipe_idea_proc(message: types.Message, state: FSMContext):
    res = await ask_ai(f"Дай подробный рецепт с граммами и шагами для: {message.text}", system_context="Ты эксперт по кулинарии.")
    await message.answer(f"📖 **Ваш рецепт:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "🧘 Психолог")
async def psych(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 СТОП СРЫВ!", callback_data="stop_b")]])
    await message.answer("Трудно? Нажми кнопку, я помогу.", reply_markup=kb)

@dp.callback_query(F.data == "stop_b")
async def stop_b(callback: types.CallbackQuery):
    res = await ask_ai("Я хочу сорваться. Помоги мне.")
    await callback.message.answer(f"🧘 {res}\n\n🥤 Выпей воды и подожди 5 мин.")
    await callback.answer()

@dp.message(F.text == "🔔 Напомнить через 3ч")
async def set_alarm(message: types.Message):
    scheduler.add_job(lambda: bot.send_message(message.chat.id, "🔔 Пора перекусить! Не забудь записать еду."), "interval", minutes=180, id=f"rem_{message.chat.id}", replace_existing=True)
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
    await message.answer(f"🧾 {res}")
    await state.set_state(None)

@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Что вредное ты хочешь съесть?")
    await state.set_state(UserStates.waiting_replace)

@dp.message(UserStates.waiting_replace)
async def replace_proc(message: types.Message, state: FSMContext):
    res = await ask_ai(f"Найди ПП замену для: {message.text}")
    await message.answer(f"🍎 {res}", reply_markup=main_kb)
    await state.set_state(None)

@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 0), data.get('goal_weight', 0)
    days = int((abs(w - tw) * 7700) / 500) if w and tw else 0
    await message.answer(f"📊 Текущий вес: {w}кг → Цель: {tw}кг\n🔮 Результат через **~{days} дней**!\n\n📢 Наш канал: {TELEGRAM_CHANNEL_URL}")

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
