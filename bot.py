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
TOKEN = "8240168479:AAEP4vPJC7FK_ifnGRUgNbGe)mN-xR0"
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

# --- ИИ ФУНКЦИЯ (VISION + TEXT) ---
async def ask_vkusomer_ai(prompt, photo_bytes=None):
    try:
        messages = [
            {"role": "system", "content": "Ты ИИ-диетолог Вкусомер Плюс. Считай калории точно. В конце ответа ВСЕГДА пиши строго: 'ИТОГО ККАЛ: [число]'. Будь кратким."}
        ]
        
        if photo_bytes:
            # Модель Llama 3.2 Vision для анализа фото
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
            temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}"

# --- ОБРАБОТЧИКИ ---

@app.route('/')
def index():
    return "Vkusomer Plus is Active!"

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Дефолтные настройки: Лимит 1800, Вес 80, Цель 70
    await state.update_data(daily_limit=1800, total_today=0, last_date=str(datetime.now().date()), weight=80, target_weight=70)
    await message.answer(
        "✨ **Вкусомер Плюс приветствует тебя!**\n\n"
        "Я твой умный дневник питания. Я умею всё: от анализа фото тарелки до поддержки при стрессе.\n\n"
        "Нажми кнопку ниже, чтобы начать!", reply_markup=main_kb
    )

# 1. СУММАТОР КАЛОРИЙ (ЕДА)
@dp.message(F.text == "📝 Записать еду (Фото/Текст)")
async def food_start(message: types.Message, state: FSMContext):
    await message.answer("Отправь фото тарелки или напиши текстом (например: '2 сырника и латте') 📸")
    await state.set_state(UserStates.waiting_food)

@dp.message(UserStates.waiting_food)
async def food_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    today = str(datetime.now().date())
    total_today = data.get('total_today', 0) if data.get('last_date') == today else 0
    
    await message.answer("🔍 Вкусомер думает...")

    photo_content = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_io = await bot.download_file(file.file_path)
        photo_content = photo_io.read()
        prompt = "Определи еду на фото и её калорийность."
    else:
        prompt = f"Пользователь съел: {message.text}. Оцени калории."

    ai_reply = await ask_vkusomer_ai(prompt, photo_content)

    # Извлекаем число
    found_cals = re.findall(r"ИТОГО ККАЛ: (\d+)", ai_reply)
    new_cals = int(found_cals[0]) if found_cals else 0
    
    total_today += new_cals
    limit = data.get('daily_limit', 1800)
    
    await state.update_data(total_today=total_today, last_date=today)

    await message.answer(
        f"✅ **Готово!**\n\n{ai_reply}\n\n"
        f"📈 **Статистика за сегодня:**\n"
        f"— Добавлено: +{new_cals} ккал\n"
        f"— Всего съедено: {total_today} / {limit} ккал\n"
        f"— Осталось: {max(0, limit - total_today)} ккал",
        reply_markup=main_kb
    )
    await state.set_state(None)

# 2. МОЙ ПРОГРЕСС И ПРОГНОЗ
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    w, tw = data.get('weight', 80), data.get('target_weight', 70)
    # Считаем дни: разница веса * 7700 ккал / 500 ккал дефицита в день
    days = int((abs(w - tw) * 7700) / 500)
    
    await message.answer(
        f"📊 **Твой статус:**\n"
        f"— Текущий вес: {w} кг\n"
        f"— Цель: {tw} кг\n\n"
        f"🔮 **ИИ-Прогноз:**\n"
        f"Если будешь соблюдать норму, ты весишь {tw} кг уже через **{days} дней**!",
        parse_mode="Markdown"
    )

# 3. ШЕФ: ЧТО В ХОЛОДИЛЬНИКЕ
@dp.message(F.text == "👨‍🍳 Шеф: что в холодильнике?")
async def chef_start(message: types.Message, state: FSMContext):
    await message.answer("Напиши список продуктов, которые залежались:")
    await state.set_state(UserStates.waiting_fridge)

@dp.message(UserStates.waiting_fridge)
async def chef_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Придумай рецепт из: {message.text}", None)
    await message.answer(f"👨‍🍳 **Мой рецепт:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 4. ПСИХОЛОГ (СТОП-СРЫВ)
@dp.message(F.text == "🧘 Психолог")
async def psych_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍕 ХОЧУ СОРВАТЬСЯ!", callback_data="stop_binge")]])
    await message.answer("Еда — это топливо, а не способ заглушить тревогу. Если очень хочется вредного — жми кнопку.", reply_markup=kb)

@dp.callback_query(F.data == "stop_binge")
async def stop_binge(callback: types.CallbackQuery):
    advice = await ask_vkusomer_ai("Я хочу сорваться. Помоги мне остановиться.", None)
    await callback.message.answer(f"🧘 **Тихо...**\n\n{advice}\n\n🥤 Выпей воды и напиши мне через 5 минут.")
    await callback.answer()

# 5. ЗАМЕНА ВРЕДНОСТЕЙ
@dp.message(F.text == "🍎 Замена вредностей")
async def replace_start(message: types.Message, state: FSMContext):
    await message.answer("Что вредное ты хочешь съесть? Я найду замену:")
    await state.set_state(UserStates.waiting_replace)

@dp.message(UserStates.waiting_replace)
async def replace_proc(message: types.Message, state: FSMContext):
    res = await ask_vkusomer_ai(f"Найди ПП-замену для: {message.text}", None)
    await message.answer(f"🍎 **Совет:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# 6. СКАНЕР ЧЕКА
@dp.message(F.text == "🧾 Сканер чека")
async def receipt_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли фото чека из магазина. Я найду в нем полезные и вредные покупки!")
    await state.set_state(UserStates.waiting_receipt)

@dp.message(UserStates.waiting_receipt, F.photo)
async def receipt_proc(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.photo[-1].file_id)
    photo_io = await bot.download_file(file.file_path)
    res = await ask_vkusomer_ai("Проанализируй чек. Что из этого стоит покупать реже?", photo_io.read())
    await message.answer(f"🧾 **Анализ покупок:**\n\n{res}", reply_markup=main_kb)
    await state.set_state(None)

# --- ЗАПУСК ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

async def main():
    # Очищаем вебхуки и сбрасываем старые соединения
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
