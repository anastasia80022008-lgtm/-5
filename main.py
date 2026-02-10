# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import threading
import json
import random
from flask import Flask

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, ReplyKeyboardRemove
)

# ПОДКЛЮЧАЕМ GROQ
from groq import Groq

# --- НАСТРОЙКИ ---
TOKEN = os.environ.get('TOKEN', "8240168479:AAEP4vPJC7FK_ifnGRUgNbGeM0yovmN-xR0")
GROQ_API_KEY = os.environ.get('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')

# Инициализация клиента Groq
client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище данных пользователей
USER_DB = {}

# --- ЗАГРУЗКА РЕЦЕПТОВ (без изменений) ---
ALL_RECIPES = []
def load_recipes():
    global ALL_RECIPES
    try:
        if os.path.exists('recipes.json'):
            with open('recipes.json', 'r', encoding='utf-8') as f:
                ALL_RECIPES = json.load(f)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
load_recipes()

# --- СОСТОЯНИЯ ---
class Survey(StatesGroup):
    gender = State()
    goal = State()
    activity = State()
    age = State()
    height = State()
    weight = State()
    allergies = State()
    viewing_plan = State()
    ai_chat = State() # Состояние для чата с ИИ

# --- КЛАВИАТУРЫ ---
start_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Погнали! 🚀")]], resize_keyboard=True)
main_menu_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📅 Мой план питания"), KeyboardButton(text="🤖 Спросить ИИ-диетолога")],
    [KeyboardButton(text="⚙️ Перезаполнить анкету")]
], resize_keyboard=True)

# ... (функции get_user_block и generate_7_day_plan остаются как были) ...
def get_user_block(goal, activity):
    mapping = {
        ("Похудеть", "Сидячий образ жизни"): "А",
        ("Похудеть", "Средняя активность"): "Б",
        ("Похудеть", "Высокая активность"): "В",
        ("Поддерживать вес", "Сидячий образ жизни"): "Г",
        ("Поддерживать вес", "Средняя активность"): "Д",
        ("Поддерживать вес", "Высокая активность"): "Е",
        ("Набрать массу", "Сидячий образ жизни"): "Ж",
        ("Набрать массу", "Средняя активность"): "З",
        ("Набрать массу", "Высокая активность"): "И",
    }
    return mapping.get((goal, activity), "А")

def generate_7_day_plan(user_block, user_allergens):
    suitable = [r for r in ALL_RECIPES if user_block in r.get("blocks", [])]
    # (упрощено для краткости примера)
    if len(suitable) < 3: return None
    plan = []
    for i in range(1, 8):
        plan.append({"day": i, "meals": random.sample(suitable, 3)})
    return plan

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Я — Вкусомер 🥗. Давай настроим профиль?", reply_markup=start_kb)

@dp.message(F.text == "Погнали! 🚀")
@dp.message(F.text == "⚙️ Перезаполнить анкету")
async def start_survey(message: types.Message, state: FSMContext):
    await message.answer("Выбери свой пол:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True))
    await state.set_state(Survey.gender)

# Сохраняем данные по ходу анкеты (пример для веса)
@dp.message(Survey.weight)
async def proc_weight(message: types.Message, state: FSMContext):
    await state.update_data(weight=message.text)
    data = await state.get_data()
    USER_DB[message.from_user.id] = data # Сохраняем промежуточные данные
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово / Я всё ем", callback_data="calc_7_days")]
    ])
    await message.answer("Есть ли аллергии?", reply_markup=kb)
    await state.set_state(Survey.allergies)

@dp.callback_query(F.data == "calc_7_days")
async def calculate_7(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    USER_DB[callback.from_user.id] = data # Сохраняем полные данные пользователя
    
    await callback.message.answer("Регистрация завершена! Теперь вы можете пользоваться ИИ-диетологом.", reply_markup=main_menu_kb)
    await state.set_state(Survey.viewing_plan)

# --- ЛОГИКА ИИ-ДИЕТОЛОГА (Через Groq) ---

@dp.message(F.text == "🤖 Спросить ИИ-диетолога")
async def ai_welcome(message: types.Message, state: FSMContext):
    await message.answer(
        "Я ваш личный ИИ-диетолог. Я помню ваш вес и цели.\n"
        "Спросите меня о чем угодно или напишите, что вы съели.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Выход из чата ИИ")]], resize_keyboard=True)
    )
    await state.set_state(Survey.ai_chat)

@dp.message(Survey.ai_chat, F.text == "⬅️ Выход из чата ИИ")
async def exit_ai(message: types.Message, state: FSMContext):
    await message.answer("Возвращаемся в главное меню.", reply_markup=main_menu_kb)
    await state.set_state(Survey.viewing_plan)

@dp.message(Survey.ai_chat)
async def ai_answer(message: types.Message):
    # Достаем данные пользователя, которые он вводил в начале
    user_info = USER_DB.get(message.from_user.id, {})
    
    # Создаем "инструкцию" для ИИ, подставляя данные пользователя
    system_prompt = (
        f"Ты — профессиональный ИИ-диетолог проекта 'Вкусомер'. "
        f"Данные клиента: пол: {user_info.get('gender', 'не указан')}, "
        f"цель: {user_info.get('goal', 'здоровое питание')}, "
        f"возраст: {user_info.get('age', '-')}, рост: {user_info.get('height', '-')}, "
        f"вес: {user_info.get('weight', '-')}. "
        "Отвечай кратко, давай советы по калориям и продуктам. Используй дружелюбный тон."
    )

    sent_msg = await message.answer("⏳ Диетолог думает...")

    try:
        # Запрос к Groq
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message.text}
            ],
            model="llama-3.3-70b-versatile", # Самая мощная модель в Groq
        )
        
        answer = chat_completion.choices[0].message.content
        await sent_msg.edit_text(answer)
    except Exception as e:
        logging.error(f"Ошибка Groq: {e}")
        await sent_msg.edit_text("Извините, сейчас я не могу ответить. Попробуйте через минуту.")

# --- ВЕБ-ЧАСТЬ (для Render) ---
@app.route('/')
def index(): return "Bot is running!"

async def run_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

def run_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

if __name__ == "__main__":
    threading.Thread(target=run_bot_thread, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
