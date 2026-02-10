# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import base64
from datetime import datetime
from flask import Flask
from groq import Groq  # Используем Groq по вашему ключу

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ (ВАШИ КЛЮЧИ) ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GROQ_API_KEY = "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"

client = Groq(api_key=GROQ_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# --- СОСТОЯНИЯ ---
class UserData(StatesGroup):
    waiting_food = State()
    waiting_fridge = State()
    waiting_replace = State()

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🧘 Психолог")],
    [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="🧾 Сканер чека")]
], resize_keyboard=True)

# --- ИИ ЛОГИКА (GROQ) ---
def ask_ai(prompt, system_role="Ты эксперт-диетолог Вкусомер Плюс."):
    try:
        # Используем мощную модель Llama 3 для текста
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_role + " В конце ответа ВСЕГДА пиши: 'ИТОГО ККАЛ: [число]'."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1024
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index():
    return "Vkusomer Plus is running on Groq AI!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Начальные настройки (вес 80, цель 70, лимит 1800)
    await state.update_data(daily_limit=1800, total_today=0, last_date=str(datetime.now().date()), weight=80, target_weight=70)
    await message.answer(
        "✨ **Вкусомер Плюс запущен!** ✨\n\n"
        "Я — твой ИИ-диетолог на базе Llama 3. Я умею:\n"
        "1. Считать калории и суммировать их за день.\n"
        "2. Предсказывать дату достижения твоей цели.\n"
        "3. Останавливать тебя от срывов (🧘 Психолог).\n"
        "4. Готовить из остатков продуктов.\n\n"
        "Просто напиши, что ты съел!", reply_markup=main_kb
    )

# 1. ЗАПИСЬ ЕДЫ И СУММАТОР
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши текстом, что ты съел. Если пришлешь фото, я постараюсь оценить его визуально! 📸")
    await state.set_state(UserData.waiting_food)

@dp.message(UserData.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 ИИ Вкусомер анализирует...")

    # Если текст
    ai_reply = ask_ai(f"Пользователь съел: {message.text}. Оцени калорийность каждого продукта и выведи сумму.")

    # Извлекаем калории (регулярное выражение ищет число после 'ИТОГО ККАЛ:')
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(cals[0]) if cals else 0
    
    total_today += new_cals
    limit = data.get('daily_limit', 1800)
    left = limit - total_today

    await state.update_data(total_today=total_today, last_date=today)

    msg = (
        f"✅ **Записано в дневник!**\n\n{ai_reply}\n\n"
        f"📊 **Баланс за {today}:**\n"
        f"— Добавлено: +{new_cals} ккал\n"
        f"— Всего съедено: {total_today} из {limit} ккал\n"
        f"— Осталось: {max(0, left)} ккал"
    )
    await message.answer(msg, reply_markup=main_kb)
    await state.set_state(None)

# 2. ПРОГНОЗ ПОХУДЕНИЯ
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 80), data.get('target_weight', 70)
    
    # Расчет: 1кг жира = 7700 ккал дефицита. Допустим дефицит 500 в день.
    days = int((abs(w - tw) * 7700) / 500)
    
    msg = (
        f"📊 **Твой статус:**\n"
        f"— Текущий вес: {w} кг\n"
        f"— Цель: {tw} кг\n\n"
        f"🔮 **Прогноз:**\n"
        f"Если будешь съедать не более {data.get('daily_limit')} ккал, "
        f"ты достигнешь цели через **{days} дней**!"
    )
    await message.answer(msg, parse_mode="Markdown")

# 3. ШЕФ ИЗ ТОГО ЧТО ЕСТЬ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def fridge_start(message: types.Message, state: FSMContext):
    await message.answer("Перечисли через запятую продукты, которые у тебя есть:")
    await state.set_state(UserData.waiting_fridge)

@dp.message(UserData.waiting_fridge)
async def fridge_process(message: types.Message, state: FSMContext):
    recipe = ask_ai(f"Придумай быстрый ПП-рецепт из этих продуктов: {message.text}.", system_role="Ты шеф-повар.")
    await message.answer(f"👨‍🍳 **Мой рецепт для тебя:**\n\n{recipe}", parse_mode="Markdown")
    await state.set_state(None)

# 4. ПСИХОЛОГ (Эмоциональное питание)
@dp.message(F.text == "🧘 Психолог")
async def psych_support(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍕 Хочу сорваться!", callback_data="stop_binge")],
        [InlineKeyboardButton(text="😔 Мне грустно / Стресс", callback_data="psych_mood")]
    ])
    await message.answer("Я здесь. Помни: еда не решает проблемы, она просто дает энергию. Что чувствуешь?", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def stop_binge(callback: types.CallbackQuery):
    advice = ask_ai("Я хочу сорваться и съесть много вредной еды. Помоги мне остановиться.")
    await callback.message.answer(f"🧘 **Вдох-выдох...**\n\n{advice}\n\n🥤 Выпей стакан воды и подожди 5 минут. Желание уйдет.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Какой вредный продукт ты хочешь съесть прямо сейчас?")
    await state.set_state(UserData.waiting_replace)

@dp.message(UserData.waiting_replace)
async def replace_process(message: types.Message, state: FSMContext):
    alt = ask_ai(f"Найди полезную, но вкусную замену для продукта: {message.text}.")
    await message.answer(f"🍏 **Моя рекомендация:**\n\n{alt}", parse_mode="Markdown")
    await state.set_state(None)

# 6. СКАНЕР ЧЕКА
@dp.message(F.text == "🧾 Сканер чека")
async def scan_receipt(message: types.Message):
    await message.answer("Пришли фото чека, и я проанализирую твою корзину на 'вредные' продукты! 🛒")

# --- ЗАПУСК ВЕБ-СЕРВЕРА (Keep-Alive) ---
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
