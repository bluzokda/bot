import logging
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters
import os
import asyncio
from PIL import Image
import pytesseract
import io
import re
import requests
import time  # Добавлено для обработки ожидания модели

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
API_URL = "https://api-inference.huggingface.co/models/deepset/roberta-base-squad2"
HF_TOKEN = os.getenv("HF_TOKEN")
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}
OCR_CONFIG = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'

# Кэш контекста пользователей
user_context = {}

async def image_to_text(image_bytes: bytes) -> str:
    """Конвертирует изображение в текст с помощью Tesseract OCR"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert('L')
        text = pytesseract.image_to_string(
            image,
            lang='rus+eng',
            config=OCR_CONFIG
        )
        return re.sub(r'\s+', ' ', text).strip() or "Не удалось распознать текст."
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return "Ошибка обработки изображения."

async def get_answer(question: str, context: str) -> str:
    """Получение ответа через Hugging Face API"""
    if not HF_TOKEN:
        return "⚠️ Ошибка: API токен не настроен"
    
    payload = {
        "inputs": {
            "question": question,
            "context": context[:5000]  # Ограничение контекста
        }
    }
    
    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload)
        
        # Обработка разных статусов API
        if response.status_code == 200:
            result = response.json()
            return result['answer'] if result['score'] > 0.01 else "Ответ не найден в тексте"
        elif response.status_code == 503:
            # Модель загружается - пробуем подождать
            retry_after = int(response.headers.get('Retry-After', 20))
            logger.warning(f"Model loading, retry after {retry_after}s")
            return f"Модель загружается, попробуйте через {retry_after} секунд"
        else:
            logger.error(f"API error: {response.status_code} - {response.text}")
            return f"Ошибка API: {response.status_code}"
    except Exception as e:
        logger.error(f"Request error: {e}")
        return "Ошибка соединения с API"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входящих сообщений"""
    user_id = update.message.from_user.id
    msg = update.message
    
    # Обработка изображений
    if msg.photo:
        try:
            photo_file = await msg.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            text = await image_to_text(image_bytes)
            
            user_context[user_id] = text
            response = f"✅ Текст распознан ({len(text)} символов)\nЗадайте вопрос по тексту"
            await msg.reply_text(response)
        except Exception as e:
            logger.error(f"Photo error: {e}")
            await msg.reply_text("⚠️ Ошибка обработки изображения")
        return
    
    # Обработка текста
    user_text = msg.text.strip()
    
    if not user_text:
        return
    
    # Команда сброса
    if user_text.lower() in ['/start', '/clear', '/new']:
        user_context.pop(user_id, None)
        await msg.reply_text("🔄 Контекст очищен. Отправьте новое изображение.")
        return
    
    # Проверка контекста
    if user_id not in user_context:
        await msg.reply_text("ℹ️ Сначала отправьте изображение с текстом")
        return
    
    # Получение ответа
    context_text = user_context[user_id]
    status_msg = await msg.reply_text("🔍 Анализирую вопрос...")
    
    try:
        answer = await get_answer(user_text, context_text)
        
        # Форматирование ответа
        response = f"❓ Вопрос: {user_text}\n\n💡 Ответ: {answer}\n\n"
        response += "Для нового запроса отправьте /new"
        
        await status_msg.edit_text(response)
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        await status_msg.edit_text("⚠️ Произошла ошибка при обработке вашего вопроса")

def main() -> None:
    """Запуск бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Токен Telegram не найден!")
    
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.PHOTO | filters.TEXT, handle_message))
    
    # Обработчик команд
    application.add_handler(MessageHandler(filters.Regex(r'^/(start|clear|new)$'), handle_message))
    
    application.run_polling()

if __name__ == "__main__":
    main()
