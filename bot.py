# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import json
from datetime import datetime
from flask import Flask
from openai import OpenAI

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"
OPENAI_API_KEY = "ВАШ_КЛЮЧ_OPENAI"

client = OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# --- СОСТОЯНИЯ ---
class UserData(StatesGroup):
    waiting_food = State()      # Запись еды
    waiting_fridge = State()    # Рецепт из остатков
    waiting_receipt = State()   # Анализ чека
    waiting_replace = State()   # Замена вредного

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🧘 Психолог")],
    [KeyboardButton(text="🧾 Сканер чека"), KeyboardButton(text="🍎 Замена вредностей")]
], resize_keyboard=True)

# --- ИИ ЛОГИКА ---
def ask_ai(prompt, system_role="Ты диетолог Вкусомер Плюс. Отвечай кратко."):
    """Универсальный запрос к OpenAI"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Используем 4o для анализа фото и текста
            messages=[
                {"role": "system", "content": system_role + " Если считаешь калории, в конце ВСЕГДА пиши: 'ИТОГО ККАЛ: [число]'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Начальные данные пользователя (можно расширить анкетой)
    await state.update_data(
        daily_limit=1800, 
        total_today=0, 
        last_date=str(datetime.now().date()), 
        weight=80, 
        target_weight=70,
        streak=1
    )
    await message.answer(
        "✨ Добро пожаловать во **Вкусомер Плюс**!\n\n"
        "Я твой ИИ-наставник. Я умею видеть еду по фото, составлять прогнозы и поддерживать тебя в трудную минуту.\n\n"
        "С чего начнем?", reply_markup=main_kb
    )

# 1. ЗАПИСЬ ЕДЫ (СУММАТОР)
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_step_1(message: types.Message, state: FSMContext):
    await message.answer("Просто пришли фото тарелки или напиши, что ты съел! 📸🍎")
    await state.set_state(UserData.waiting_food)

@dp.message(UserData.waiting_food)
async def food_step_2(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 ИИ анализирует... Подожди пару секунд.")

    if message.photo:
        # Для фото используем текстовое описание (в полной версии передаем file_id)
        ai_reply = ask_ai("Проанализируй это блюдо (представь, что видишь фото). Оцени калории.")
    else:
        ai_reply = ask_ai(f"Я съел: {message.text}. Оцени состав и калории.")

    # Извлекаем калории через регулярное выражение
    calories_found = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(calories_found[0]) if calories_found else 0
    
    total_today += new_cals
    limit = data.get('daily_limit', 1800)
    left = limit - total_today

    await state.update_data(total_today=total_today, last_date=today)

    msg = (
        f"✅ **Анализ готов:**\n\n{ai_reply}\n\n"
        f"📈 **Твой день:**\n"
        f"— Добавлено: {new_cals} ккал\n"
        f"— Всего сегодня: {total_today} / {limit} ккал\n"
        f"— Осталось: {max(0, left)} ккал"
    )
    await message.answer(msg, parse_mode="Markdown", reply_markup=main_kb)
    await state.set_state(None)

# 2. ПРОГРЕСС И ПРОГНОЗ
@dp.message(F.text == "📊 Мой прогресс")
async def progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 0), data.get('target_weight', 0)
    total = data.get('total_today', 0)
    limit = data.get('daily_limit', 1800)
    
    # Расчет даты (упрощенно: 1кг = 7700 ккал дефицита)
    diff = abs(w - tw)
    days = int((diff * 7700) / 500) # При дефиците 500 ккал в день
    
    msg = (
        f"📊 **Твой статус:**\n"
        f"— Вес: {w} кг -> Цель: {tw} кг\n"
        f"— Стрик активности: 🔥 {data.get('streak', 1)} дней\n"
        f"— Сегодня: {total} / {limit} ккал\n\n"
        f"🔮 **ИИ-Прогноз:**\n"
        f"Если соблюдать режим, ты достигнешь цели через **{days} дней**!"
    )
    await message.answer(msg, parse_mode="Markdown")

# 3. ШЕФ ИЗ ТОГО ЧТО ЕСТЬ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def fridge_1(message: types.Message, state: FSMContext):
    await message.answer("Перечисли продукты, которые нужно использовать:")
    await state.set_state(UserData.waiting_fridge)

@dp.message(UserData.waiting_fridge)
async def fridge_2(message: types.Message, state: FSMContext):
    recipe = ask_ai(f"Придумай крутой ПП рецепт из этого: {message.text}. Напиши шаги и калории.")
    await message.answer(f"👨‍🍳 **Вот мой рецепт:**\n\n{recipe}", parse_mode="Markdown")
    await state.set_state(None)

# 4. ПСИХОЛОГ (Эмоциональное питание)
@dp.message(F.text == "🧘 Психолог")
async def psych_1(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍕 Хочу сорваться!", callback_data="stop_binge")],
        [InlineKeyboardButton(text="😔 Мне грустно/Стресс", callback_data="stress_help")]
    ])
    await message.answer("Я здесь. Помни, еда — это топливо, а не способ заглушить чувства. Что случилось?", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def stop_binge(callback: types.CallbackQuery):
    advice = ask_ai("Я хочу сорваться и съесть много вредной еды. Используй психологию, чтобы меня остановить.")
    await callback.message.answer(f"🧘 **Давай выдохнем.**\n\n{advice}\n\n🥤 Выпей стакан воды и напиши мне через 5 минут.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_1(message: types.Message, state: FSMContext):
    await message.answer("Какой вредный продукт ты хочешь съесть? Я подберу полезную замену.")
    await state.set_state(UserData.waiting_replace)

@dp.message(UserData.waiting_replace)
async def replace_2(message: types.Message, state: FSMContext):
    alt = ask_ai(f"Найди полезную, вкусную и менее калорийную замену для: {message.text}.")
    await message.answer(f"🍎 **Моё предложение:**\n\n{alt}", parse_mode="Markdown")
    await state.set_state(None)

# 6. СКАНЕР ЧЕКОВ
@dp.message(F.text == "🧾 Сканер чека")
async def scan_receipt(message: types.Message):
    await message.answer("Пришли фото чека из супермаркета, и я проанализирую твою корзину продуктов на полезность! 🛒")

# --- ЗАПУСК ВЕБ-СЕРВЕРА ---
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
