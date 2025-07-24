import os
import logging
import requests
from io import BytesIO
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from PIL import Image
import base64

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание клавиатуры
def make_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Текстовый запрос"))
    builder.add(types.KeyboardButton(text="🖼️ Запрос по фото"))
    builder.add(types.KeyboardButton(text="❓ Помощь"))
    return builder.as_markup(resize_keyboard=True)

# Обработчик команды /start
@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "Привет! Я твой помощник в учебе 🤓\n"
        "Выбери тип запроса:",
        reply_markup=make_keyboard()
    )

# Обработчик кнопки "Помощь"
@dp.message(F.text == "❓ Помощь")
async def help_command(message: Message):
    help_text = (
        "📚 Доступные команды:\n\n"
        "📝 Текстовый запрос - задай вопрос текстом\n"
        "🖼️ Запрос по фото - отправь фото с вопросом\n"
        "❓ Помощь - показать это сообщение\n\n"
        "Примеры запросов:\n"
        "• Объясни теорему Пифагора\n"
        "• Реши уравнение: 2x + 5 = 15\n"
        "• Что изображено на картинке?"
    )
    await message.answer(help_text, reply_markup=make_keyboard())

# Обработчик текстовых запросов
@dp.message(F.text == "📝 Текстовый запрос")
async def text_request(message: Message):
    await message.answer("Отправь свой вопрос текстом:")

# Функция для запроса к Hugging Face
def query_hf(payload, model="mistralai/Mistral-7B-Instruct-v0.3", is_image=False):
    API_URL = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    if is_image:
        response = requests.post(API_URL, headers=headers, data=payload)
    else:
        response = requests.post(API_URL, headers=headers, json={"inputs": payload})
    
    return response

# Обработчик текстовых сообщений
@dp.message(F.text)
async def handle_text(message: Message):
    if len(message.text) < 5:
        return await message.answer("❌ Запрос слишком короткий. Попробуй сформулировать подробнее.")
    
    try:
        response = query_hf(message.text)
        
        if response.status_code == 200:
            result = response.json()[0]['generated_text']
            await message.answer(f"🤖 Ответ:\n\n{result}")
        else:
            logger.error(f"HF API error: {response.status_code} - {response.text}")
            await message.answer("⚠️ Ошибка обработки запроса. Попробуй позже.")
    
    except Exception as e:
        logger.exception("Text processing error")
        await message.answer("❌ Произошла ошибка. Попробуй другой запрос.")

# Обработчик запросов по фото
@dp.message(F.text == "🖼️ Запрос по фото")
async def photo_request(message: Message):
    await message.answer("Отправь фото с вопросом:")

# Обработчик фотографий
@dp.message(F.photo)
async def handle_photo(message: Message):
    try:
        # Скачивание фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path
        
        # Загрузка изображения
        photo_data = await bot.download_file(file_path)
        
        # Конвертация в base64
        image = Image.open(BytesIO(photo_data.read()))
        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Подготовка запроса
        payload = {
            "inputs": {
                "image": img_str,
                "question": "Что изображено на картинке? Подробно опиши содержание изображения."
            }
        }
        
        # Отправка запроса в Hugging Face
        response = query_hf(
            payload,
            model="Salesforce/blip-vqa-capfilt-large",
            is_image=True
        )
        
        if response.status_code == 200:
            result = response.json()[0]['generated_text']
            await message.answer(f"🤖 Описание изображения:\n\n{result}")
        else:
            logger.error(f"Image API error: {response.status_code} - {response.text}")
            await message.answer("⚠️ Ошибка обработки изображения. Попробуй другое фото.")
    
    except Exception as e:
        logger.exception("Image processing error")
        await message.answer("❌ Произошла ошибка при обработке фото.")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
