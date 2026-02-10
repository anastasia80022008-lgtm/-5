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

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ (КЛЮЧИ ИСПРАВЛЕНЫ) ---
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
        system_msg = "Ты ИИ-диетолог Вкусомер Плюс. Если считаешь калории, в конце ВСЕГДА пиши строго: 'ИТОГО ККАЛ: [число]'. Будь кратким."
        
        if photo_bytes:
            # Модель Vision для анализа фото
            base64_image = base64.b64encode(photo_bytes).decode('utf-8')
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ]
            model = "llama-3.2-11b-vision-preview"
        else:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ]
            model = "llama3-8b-8192"

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ВЕБ-ЧАСТЬ ---
@app.route('/')
def index():
    return "Vkusomer Plus is Active!"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Дефолтные данные (80кг -> 70кг, лимит 1800)
    await state.update_data(daily_limit=1800, total_today=0, last_date=str(datetime.now().date()), weight=80, target_weight=70)
    await message.answer(
        "✨ **Вкусомер Плюс запущен!** ✨\n\n"
        "Я твой ИИ-диетолог. Я умею считать калории по фото, планировать прогресс и поддерживать тебя.\n\n"
        "Выбирай действие на клавиатуре:", reply_markup=main_kb
    )

# 1. СУММАТОР КАЛОРИЙ (ЕДА)
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Опиши текстом, что съел, или пришли фото тарелки! 📸")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    
    # Сброс калорий, если наступил новый день
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Анализирую...")

    photo_data = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_io = await bot.download_file(file.file_path)
        photo_data = photo_io.read()
        prompt = "Распознай еду и оцени калории."
    else:
        prompt = f"Я съел: {message.text}. Оцени калории."

    ai_reply = await ask_vkusomer_ai(prompt, photo_data)

    # Извлечение числа из ответа
    found = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(found[0]) if found else 0
    total_today += new_cals
    
    await state.update_data(total_today=total_today, last_date=today)

    await message.answer(
        f"✅ **Записано!**\n\n{ai_reply}\n\n"
        f"📈 **Твой день:**\n"
        f"— Добавлено: +{new_cals} ккал\n"
        f"— Всего сегодня: {total_today} / {data.get('daily_limit', 1800)} ккал\n"
        f"— Осталось: {max(0, data.get('daily_limit', 1800) - total_today)} ккал",
        reply_markup=main_kb
    )
    await state.set_state(None)

# 2. ПРОГРЕСС
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 80), data.get('target_weight', 70)
    # Расчет: 1кг жира = 7700 ккал дефицита. Дефицит 500/день
    days = int((abs(w - tw) * 7700) / 500)
    
    await message.answer(
        f"📊 **Твой прогресс:**\nВес: {w}кг → Цель: {tw}кг\n\n"
        f"🔮 **ИИ-Прогноз:**\nПри соблюдении лимита ты достигнешь цели через **{days} дней**!"
    )

# 3. ШЕФ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def chef_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши через запятую, что у тебя есть из продуктов:")
    await state.set_state(UserStates.waiting_fridge)

@dp.message(UserStates.waiting_fridge)
async def chef_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Придумай ПП-рецепт из: {message.text}")
    await message.answer(f"👨‍🍳 **Мой рецепт:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 4. ПСИХОЛОГ
@dp.message(F.text == "🧘 Психолог")
async def psych_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 ХОЧУ СОРВАТЬСЯ!", callback_data="stop_binge")]])
    await message.answer("Помни: одна конфета не испортит фигуру, а срыв на 2000 ккал — может. Что чувствуешь?", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def psych_proc(callback: types.CallbackQuery):
    res = await ask_vkusomer_ai("Я хочу сорваться и съесть много вредного. Помоги мне остановиться.")
    await callback.message.answer(f"🧘 **Вдох-выдох...**\n\n{res}\n\n🥤 Выпей стакан воды и подожди 5 минут.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши вредный продукт, а я найду полезную замену:")
    await state.set_state(UserStates.waiting_replace)

@dp.message(UserStates.waiting_replace)
async def replace_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Найди полезную замену для: {message.text}")
    await message.answer(f"🍎 **Совет:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 6. СКАНЕР ЧЕКА
@dp.message(F.text == "🧾 Сканер чека")
async def receipt_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото чека из магазина! 🛒")
    await state.set_state(UserStates.waiting_receipt)

@dp.message(UserStates.waiting_receipt, F.photo)
async def receipt_proc(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.photo[-1].file_id)
    photo_io = await bot.download_file(file.file_path)
    res = await ask_vkusomer_ai("Проанализируй этот чек. Что тут вредное, а что полезное?", photo_io.read())
    await message.answer(f"🧾 **Анализ чека:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
