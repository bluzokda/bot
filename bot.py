import logging
from telegram import Update
from telegram.ext import (
    Application, 
    ContextTypes, 
    MessageHandler, 
    filters,
    CommandHandler
)
import os
import asyncio
from PIL import Image
import pytesseract
import io
import re
import requests
from concurrent.futures import ThreadPoolExecutor

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
executor = ThreadPoolExecutor(max_workers=4)

def sync_image_to_text(image_bytes: bytes) -> str:
    """Синхронная обработка изображения"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        
        # Улучшение качества изображения
        if image.width > 1000 or image.height > 1000:
            new_width = 1000
            new_height = int(new_width * image.height / image.width)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            
        image = image.convert('L')  # Grayscale
        image = image.point(lambda x: 0 if x < 140 else 255)  # Увеличение контраста
        
        text = pytesseract.image_to_string(
            image,
            lang='rus+eng',
            config=OCR_CONFIG
        )
        return re.sub(r'\s+', ' ', text).strip() or "Не удалось распознать текст."
    except Exception as e:
        logger.exception("OCR error")
        return "Ошибка обработки изображения"

async def image_to_text(image_bytes: bytes) -> str:
    """Конвертирует изображение в текст с помощью Tesseract OCR"""
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            executor,
            sync_image_to_text,
            image_bytes
        )
        return text
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
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=20)
        
        if response.status_code == 200:
            result = response.json()
            return result.get('answer', 'Ответ не найден')
            
        elif response.status_code == 503:
            retry_after = int(response.headers.get('Retry-After', 30))
            return f"🚧 Модель загружается, попробуйте через {retry_after} секунд"
            
        else:
            logger.error(f"API error {response.status_code}: {response.text[:200]}")
            return f"❌ Ошибка API: {response.status_code}"
            
    except requests.exceptions.Timeout:
        return "⌛ Таймаут соединения с API"
    except Exception as e:
        logger.exception("HF request exception")
        return f"⚠️ Ошибка: {str(e)}"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фото"""
    user = update.effective_user
    user_id = user.id if user else None
    
    if not user_id:
        logger.warning("Не удалось определить user_id")
        return
        
    msg = update.message
    
    try:
        await msg.reply_chat_action(action="typing")
        photo_file = await msg.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        text = await image_to_text(image_bytes)
        
        # Проверка результата распознавания
        if "не удалось" in text.lower() or "ошибка" in text.lower() or len(text) < 10:
            await msg.reply_text("⚠️ Не удалось распознать текст. Попробуйте другое изображение.")
            return
            
        user_context[user_id] = text
        logger.info(f"Saved context for user {user_id}: {text[:50]}...")
        response = f"✅ Текст распознан ({len(text)} символов)\nТеперь вы можете задавать вопросы по этому тексту"
        await msg.reply_text(response)
    except Exception as e:
        logger.exception("Photo processing error")
        await msg.reply_text("⚠️ Ошибка обработки изображения")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    user_id = user.id if user else None
    
    if not user_id:
        logger.warning("Не удалось определить user_id")
        return
        
    msg = update.message
    user_text = msg.text.strip() if msg.text else ""
    
    if not user_text:
        return
    
    # Команда сброса
    if user_text.lower() in ['/start', '/clear', '/new']:
        if user_id in user_context:
            del user_context[user_id]
            logger.info(f"Context cleared for user {user_id}")
        await msg.reply_text("🔄 Контекст очищен. Отправьте новое изображение.")
        return
    
    # Команда помощи
    if user_text.lower() in ['/help', 'помощь']:
        help_text = (
            "🤖 *Помощь по боту*\n\n"
            "Отправьте фото с текстом (тест, контрольная и т.д.), а затем задавайте вопросы по нему.\n\n"
            "Команды:\n"
            "/start, /new, /clear - очистить текущий контекст\n"
            "/help - показать это сообщение\n\n"
            "После отправки фото задавайте вопросы по тексту, например:\n"
            "• Какой ответ на вопрос 5?\n"
            "• Решение задачи 3\n"
            "• Что написано в пункте 2.1?"
        )
        await msg.reply_text(help_text)
        return
    
    # Проверка контекста
    if user_id not in user_context:
        logger.warning(f"Context not found for user {user_id}")
        await msg.reply_text(
            "ℹ️ Сначала отправьте изображение с текстом\n"
            "После этого вы сможете задавать вопросы по его содержанию."
        )
        return
    
    # Получение контекста и ответа
    context_text = user_context.get(user_id, "")
    if not context_text:
        await msg.reply_text("⚠️ Контекст пуст. Отправьте новое изображение.")
        return
        
    await msg.reply_chat_action(action="typing")
    status_msg = await msg.reply_text("🔍 Ищу ответ на ваш вопрос...")
    
    try:
        answer = await get_answer(user_text, context_text)
        
        # Форматирование ответа
        response = f"❓ *Вопрос:* {user_text}\n\n💡 *Ответ:* {answer}\n\n"
        response += "Для нового запроса отправьте /new"
        
        await status_msg.edit_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error processing question")
        await status_msg.edit_text("⚠️ Произошла ошибка при обработке вашего вопроса")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        "Отправьте фото с текстом (тест, контрольная и т.д.), "
        "а затем задавайте вопросы по его содержанию.\n\n"
        "Используйте /help для получения дополнительной информации."
    )

def main() -> None:
    """Запуск бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Токен Telegram не найден!")
    
    # Путь к Tesseract
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", handle_text))
    application.add_handler(CommandHandler("new", handle_text))
    application.add_handler(CommandHandler("clear", handle_text))
    
    # Обработчики по типу контента
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Обработчик для команд в тексте
    application.add_handler(MessageHandler(filters.COMMAND, handle_text))
    
    logger.info("Бот запущен")
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Бот упал с ошибкой")
        raise
