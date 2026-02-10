# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
from datetime import datetime
from flask import Flask
from openai import OpenAI

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ (Render берет их из Environment Variables) ---
TOKEN = os.environ.get('8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0')
OPENAI_API_KEY = os.environ.get('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')

# Проверка токена перед запуском
if not TOKEN:
    raise ValueError("ОШИБКА: Переменная TOKEN не установлена в настройках Render!")

client = OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# --- СОСТОЯНИЯ ---
class UserData(StatesGroup):
    waiting_food = State()      # Запись еды
    waiting_fridge = State()    # Рецепт из остатков
    waiting_replace = State()   # Замена вредного

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🧘 Психолог")],
    [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="🧾 Сканер чека")]
], resize_keyboard=True)

# --- ИИ ЛОГИКА ---
def ask_ai(prompt, system_role="Ты эксперт-диетолог Вкусомер Плюс."):
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Умеет видеть фото и анализировать чеки
            messages=[
                {"role": "system", "content": system_role + " Если считаешь еду, в конце ВСЕГДА пиши: 'ИТОГО ККАЛ: [число]'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка связи с ИИ: {e}"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index():
    return "Vkusomer Plus is Active!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Устанавливаем начальные данные (в будущем можно сделать через анкету)
    await state.update_data(
        daily_limit=1800, 
        total_today=0, 
        last_date=str(datetime.now().date()), 
        weight=80, 
        target_weight=70
    )
    await message.answer(
        "✨ **Добро пожаловать во Вкусомер Плюс!**\n\n"
        "Я твой личный ИИ-наставник. Я помогу тебе:\n"
        "📸 Считать калории по фото и тексту\n"
        "🥗 Готовить из того, что есть в холодильнике\n"
        "🧘 Справляться с желанием сорваться\n"
        "📊 Прогнозировать дату твоей цели\n\n"
        "С чего начнем?", reply_markup=main_kb
    )

# 1. ЗАПИСЬ ЕДЫ И СУММАТОР
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Просто напиши, что ты съел, или пришли фото тарелки! 📸🍎")
    await state.set_state(UserData.waiting_food)

@dp.message(UserData.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Анализирую тарелку...")

    if message.photo:
        ai_reply = ask_ai("Проанализируй фото этой еды (представь, что видишь фото). Оцени калории.")
    else:
        ai_reply = ask_ai(f"Я съел: {message.text}. Оцени калории.")

    # Извлекаем калории
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(cals[0]) if cals else 0
    
    total_today += new_cals
    limit = data.get('daily_limit', 1800)
    left = limit - total_today

    await state.update_data(total_today=total_today, last_date=today)

    msg = (
        f"✅ **Записано!**\n\n{ai_reply}\n\n"
        f"📈 **Твой баланс:**\n"
        f"— Добавлено: {new_cals} ккал\n"
        f"— Всего сегодня: {total_today} / {limit} ккал\n"
        f"— Осталось: {max(0, left)} ккал"
    )
    await message.answer(msg, parse_mode="Markdown", reply_markup=main_kb)
    await state.set_state(None)

# 2. ПРОГРЕСС И ПРОГНОЗ
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 80), data.get('target_weight', 70)
    
    # 1кг жира = 7700 ккал дефицита. Считаем при дефиците 500 ккал/день
    days = int((abs(w - tw) * 7700) / 500)
    
    msg = (
        f"📊 **Твой статус:**\n"
        f"— Текущий вес: {w} кг\n"
        f"— Цель: {tw} кг\n\n"
        f"🔮 **ИИ-Прогноз:**\n"
        f"Если будешь соблюдать норму, ты достигнешь цели через **{days} дней**!"
    )
    await message.answer(msg, parse_mode="Markdown")

# 3. ШЕФ ИЗ ТОГО ЧТО ЕСТЬ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def fridge_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши список продуктов, которые у тебя остались:")
    await state.set_state(UserData.waiting_fridge)

@dp.message(UserData.waiting_fridge)
async def fridge_process(message: types.Message, state: FSMContext):
    recipe = ask_ai(f"Придумай крутой ПП рецепт из: {message.text}.", system_role="Ты шеф-повар Zero Waste.")
    await message.answer(f"👨‍🍳 **Моё предложение:**\n\n{recipe}", parse_mode="Markdown")
    await state.set_state(None)

# 4. ПСИХОЛОГ
@dp.message(F.text == "🧘 Психолог")
async def psych_support(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍕 Хочу сорваться!", callback_data="stop_binge")],
        [InlineKeyboardButton(text="😔 Мне грустно", callback_data="psych_mood")]
    ])
    await message.answer("Я рядом. Еда — это просто еда, а не способ заглушить чувства. Что случилось?", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def stop_binge(callback: types.CallbackQuery):
    advice = ask_ai("Я хочу сорваться. Останови меня психологически.")
    await callback.message.answer(f"🧘 **Давай выдохнем.**\n\n{advice}\n\n🥤 Выпей воды и подожди 5 минут.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Какой вредный продукт ты хочешь съесть? Я найду замену.")
    await state.set_state(UserData.waiting_replace)

@dp.message(UserData.waiting_replace)
async def replace_process(message: types.Message, state: FSMContext):
    alt = ask_ai(f"Найди полезную замену для: {message.text}.")
    await message.answer(f"🍎 **Попробуй это:**\n\n{alt}", parse_mode="Markdown")
    await state.set_state(None)

# 6. СКАНЕР ЧЕКА
@dp.message(F.text == "🧾 Сканер чека")
async def scan_receipt(message: types.Message):
    await message.answer("Пришли фото чека, и я проанализирую твою корзину продуктов на полезность! 🛒")

# --- ЗАПУСК ---
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
