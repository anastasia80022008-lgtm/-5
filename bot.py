# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import re
import io
import base64
from datetime import datetime
from flask import Flask
from groq import Groq

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0"
GROQ_API_KEY = "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"

client = Groq(api_key=GROQ_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# --- СОСТОЯНИЯ ---
class UserStates(StatesGroup):
    waiting_food = State()
    waiting_fridge = State()
    waiting_replace = State()
    waiting_receipt = State()

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записать еду (Фото/Текст)"), KeyboardButton(text="📊 Мой прогресс")],
    [KeyboardButton(text="👨‍🍳 Шеф: что в холодильнике?"), KeyboardButton(text="🧘 Психолог")],
    [KeyboardButton(text="🍎 Замена вредностей"), KeyboardButton(text="🧾 Сканер чека")]
], resize_keyboard=True)

# --- ИИ ФУНКЦИЯ (ТЕКСТ + ФОТО) ---
async def ask_vkusomer_ai(prompt, photo_bytes=None):
    try:
        messages = [
            {"role": "system", "content": "Ты диетолог Вкусомер Плюс. Если считаешь калории, в конце ВСЕГДА пиши строго: 'ИТОГО ККАЛ: [число]'. Будь кратким и полезным."}
        ]
        
        if photo_bytes:
            # Используем Vision модель для анализа фото
            base64_image = base64.b64encode(photo_bytes).decode('utf-8')
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            })
            model = "llama-3.2-11b-vision-preview"
        else:
            messages.append({"role": "user", "content": prompt})
            model = "llama3-8b-8192"

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=1024
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index():
    return "Vkusomer Plus is LIVE!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Начальные данные: вес 80кг, цель 70кг, лимит 1800ккал
    await state.update_data(daily_limit=1800, total_today=0, last_date=str(datetime.now().date()), weight=80, target_weight=70, streak=1)
    await message.answer(
        "✨ **Добро пожаловать во Вкусомер Плюс!** ✨\n\n"
        "Я твой ИИ-диетолог. Я считаю калории за тебя (даже по фото!), придумываю рецепты и помогаю не сорваться.\n\n"
        "С чего начнем?", reply_markup=main_kb
    )

# 1. СУММАТОР КАЛОРИЙ (ТЕКСТ И ФОТО)
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Просто опиши текстом, что ты съел, или пришли фото тарелки! 📸")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def process_food(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Анализирую...")

    photo_bytes = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_io = await bot.download_file(file.file_path)
        photo_bytes = photo_io.read()
        prompt = "Что на этом фото? Оцени калорийность."
    else:
        prompt = f"Я съел: {message.text}. Оцени калорийность."

    ai_reply = await ask_vkusomer_ai(prompt, photo_bytes)

    # Математика калорий
    cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(cals[0]) if cals else 0
    total_today += new_cals
    limit = data.get('daily_limit', 1800)
    
    await state.update_data(total_today=total_today, last_date=today)

    res = (
        f"✅ **Записано!**\n\n{ai_reply}\n\n"
        f"📈 **Твой баланс сегодня:**\n"
        f"— Добавлено: +{new_cals} ккал\n"
        f"— Итого съедено: {total_today} из {limit} ккал\n"
        f"— Осталось: {max(0, limit - total_today)} ккал"
    )
    await message.answer(res, reply_markup=main_kb)
    await state.set_state(None)

# 2. ПРОГНОЗ
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 80), data.get('target_weight', 70)
    # Формула: 1кг жира = 7700 ккал дефицита. Дефицит ~500 ккал/день
    days = int((abs(w - tw) * 7700) / 500)
    await message.answer(f"📊 **Твой статус:**\nВес: {w}кг → Цель: {tw}кг\n🔥 Стрик: {data.get('streak', 1)} дней\n\n🔮 **Прогноз:**\nПри текущем режиме ты достигнешь цели через **{days} дней**!")

# 3. ШЕФ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def chef_start(message: types.Message, state: FSMContext):
    await message.answer("Что у тебя есть? Напиши список через запятую:")
    await state.set_state(UserStates.waiting_fridge)

@dp.message(UserStates.waiting_fridge)
async def chef_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Придумай ПП рецепт из этого: {message.text}", None)
    await message.answer(f"👨‍🍳 **Моё предложение:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 4. ПСИХОЛОГ
@dp.message(F.text == "🧘 Психолог")
async def psych_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 ХОЧУ СОРВАТЬСЯ!", callback_data="stop_eat")]])
    await message.answer("Я рядом. Если чувствуешь стресс или хочешь съесть лишнего — нажми кнопку.", reply_markup=kb)

@dp.callback_query(F.data == "stop_eat")
async def psych_proc(callback: types.CallbackQuery):
    res = await ask_vkusomer_ai("Я хочу сорваться и съесть много вредного. Помоги мне остановиться.", None)
    await callback.message.answer(f"🧘 **Тихо...**\n\n{res}\n\n🥤 Выпей стакан воды и подожди 5 минут.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Что вредное ты хочешь съесть? Я найду замену:")
    await state.set_state(UserStates.waiting_replace)

@dp.message(UserStates.waiting_replace)
async def replace_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Найди полезную замену для: {message.text}", None)
    await message.answer(f"🍎 **Совет от Вкусомера:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 6. СКАНЕР ЧЕКА
@dp.message(F.text == "🧾 Сканер чека")
async def receipt_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото чека из магазина! Я найду в нем вредные продукты.")
    await state.set_state(UserStates.waiting_receipt)

@dp.message(UserStates.waiting_receipt, F.photo)
async def receipt_proc(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.photo[-1].file_id)
    photo_io = await bot.download_file(file.file_path)
    res = await ask_vkusomer_ai("Проанализируй этот чек. Какие продукты тут вредные, а какие полезные?", photo_io.read())
    await message.answer(f"🧾 **Анализ чека:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
