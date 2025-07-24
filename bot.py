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
import time

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
user_last_activity = {}
executor = ThreadPoolExecutor(max_workers=4)

# Очистка старого контекста (через 1 час неактивности)
async def cleanup_old_contexts():
    while True:
        await asyncio.sleep(3600)  # Каждый час
        current_time = time.time()
        to_remove = []
        for user_id, last_time in user_last_activity.items():
            if current_time - last_time > 3600:  # 1 час
                to_remove.append(user_id)
        
        for user_id in to_remove:
            if user_id in user_context:
                del user_context[user_id]
            del user_last_activity[user_id]
            logger.info(f"Cleaned up context for inactive user {user_id}")

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
        cleaned_text = re.sub(r'\s+', ' ', text).strip()
        return cleaned_text if cleaned_text else "Не удалось распознать текст."
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
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get('answer', 'Ответ не найден')
            # Если ответ слишком короткий или неинформативный
            if not answer or len(answer.strip()) < 2:
                return "Не удалось найти точный ответ. Попробуйте переформулировать вопрос."
            return answer
            
        elif response.status_code == 503:
            retry_after = int(response.headers.get('Retry-After', 30))
            return f"🚧 Модель загружается, попробуйте через {retry_after} секунд"
            
        elif response.status_code == 429:
            return "⏰ Превышен лимит запросов. Попробуйте позже."
            
        else:
            logger.error(f"API error {response.status_code}: {response.text[:200]}")
            return f"❌ Ошибка API: {response.status_code}"
            
    except requests.exceptions.Timeout:
        return "⌛ Таймаут соединения с API"
    except requests.exceptions.ConnectionError:
        return "🔌 Ошибка подключения к API"
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
        # Исправлено: правильно получаем байты
        image_bytes = await photo_file.download_to_memory()
        image_data = image_bytes.getbuffer().tobytes()
        
        # Обновляем время активности пользователя
        user_last_activity[user_id] = time.time()
        
        text = await image_to_text(image_data)
        
        # Проверка результата распознавания
        if "не удалось" in text.lower() or "ошибка" in text.lower() or len(text) < 10:
            await msg.reply_text("⚠️ Не удалось распознать текст. Попробуйте другое изображение.")
            return
            
        user_context[user_id] = text
        logger.info(f"Saved context for user {user_id}: {len(text)} characters")
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
    
    # Обновляем время активности пользователя
    user_last_activity[user_id] = time.time()
    
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
    if not context_text or len(context_text) < 10:
        await msg.reply_text("⚠️ Контекст пуст или слишком короткий. Отправьте новое изображение.")
        return
        
    await msg.reply_chat_action(action="typing")
    status_msg = await msg.reply_text("🔍 Ищу ответ на ваш вопрос...")
    
    try:
        answer = await get_answer(user_text, context_text)
        
        # Форматирование ответа
        response = f"❓ *Вопрос:* {user_text}\n\n💡 *Ответ:* {answer}\n\n"
        response += "_Для нового запроса отправьте /new_"
        
        await status_msg.edit_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error processing question")
        await status_msg.edit_text("⚠️ Произошла ошибка при обработке вашего вопроса")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "🤖 *Как пользоваться ботом:*\n"
        "1. Отправь фото с текстом (тест, контрольная и т.д.)\n"
        "2. Задавай вопросы по содержимому фото\n\n"
        "💡 *Команды:*\n"
        "/help - помощь по командам\n"
        "/new - начать с нового изображения\n\n"
        "_Бот запоминает текст с последнего отправленного фото_",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "🤖 *Помощь по боту*\n\n"
        "📸 *Отправьте фото* с текстом (тест, контрольная и т.д.)\n"
        "❓ *Задавайте вопросы* по содержимому фото\n\n"
        "🔧 *Команды:*\n"
        "• /start - начать работу\n"
        "• /new - очистить контекст и начать заново\n"
        "• /help - показать помощь\n\n"
        "📝 *Примеры вопросов:*\n"
        "• Какой ответ на вопрос 5?\n"
        "• Решение задачи 3\n"
        "• Что написано в пункте 2.1?\n\n"
        "_Контекст сохраняется 1 час после последней активности_"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /new"""
    user_id = update.effective_user.id
    if user_id in user_context:
        del user_context[user_id]
    if user_id in user_last_activity:
        del user_last_activity[user_id]
    logger.info(f"Context cleared for user {user_id}")
    await update.message.reply_text("🔄 Контекст очищен. Отправьте новое изображение.")

def main() -> None:
    """Запуск бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Токен Telegram не найден!")
    
    # Путь к Tesseract
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new", new_command))
    application.add_handler(CommandHandler("clear", new_command))
    
    # Обработчики по типу контента
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запуск задачи очистки старых контекстов
    application.job_queue.run_once(lambda _: asyncio.create_task(cleanup_old_contexts()), 1)
    
    logger.info("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Бот упал с ошибкой")
        raise
