import logging
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters
import os
import asyncio
from transformers import pipeline
from PIL import Image
import pytesseract
import io
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные для моделей
qa_pipeline = None
ocr_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'

# Кэш контекста пользователей (user_id: context)
user_context = {}

def init_qa_model():
    """Инициализация QA модели один раз при старте"""
    global qa_pipeline
    logger.info("Инициализация QA модели...")
    qa_pipeline = pipeline(
        'question-answering',
        model='AlexKay/xlm-roberta-large-qa-multilingual-finedtuned-ru',
        device=0 if os.getenv('USE_GPU', 'false') == 'true' else -1
    )
    logger.info("QA модель инициализирована")

async def image_to_text(image_bytes: bytes) -> str:
    """Конвертирует изображение в текст с помощью Tesseract OCR"""
    try:
        # Открытие изображения из байтов
        image = Image.open(io.BytesIO(image_bytes))
        
        # Предобработка изображения
        image = image.convert('L')  # В градации серого
        image = image.point(lambda x: 0 if x < 140 else 255)  # Бинаризация
        
        # Распознавание текста
        text = pytesseract.image_to_string(
            image,
            lang='rus+eng',
            config=ocr_config
        )
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else "Не удалось распознать текст на изображении."
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return "Ошибка обработки изображения."

async def get_answer(question: str, context: str) -> str:
    """Получение ответа на вопрос с помощью QA модели"""
    try:
        if not qa_pipeline:
            init_qa_model()
            
        # Ограничение контекста (модели имеют лимит токенов)
        max_context_length = 10000
        if len(context) > max_context_length:
            context = context[:max_context_length]
            
        # Запуск модели в отдельном потоке
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, 
            lambda: qa_pipeline(question=question, context=context)
        )
        
        return result['answer'] if result['score'] > 0.1 else "Не могу найти ответ в предоставленном тексте."
    except Exception as e:
        logger.error(f"QA error: {e}")
        return "Ошибка обработки запроса."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входящих сообщений"""
    user_id = update.message.from_user.id
    msg = update.message
    
    # Обработка изображений
    if msg.photo:
        try:
            # Получаем фото с наилучшим качеством
            photo_file = await msg.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            
            # Распознаем текст
            text = await image_to_text(image_bytes)
            
            # Сохраняем контекст для пользователя
            user_context[user_id] = text
            
            # Формируем ответ
            response = "✅ Текст успешно распознан!\n\n"
            response += f"Распознано символов: {len(text)}\n\n"
            response += "Теперь задайте вопрос по этому тексту."
            
            await msg.reply_text(response)
        except Exception as e:
            logger.error(f"Photo processing error: {e}")
            await msg.reply_text("⚠️ Ошибка обработки изображения. Попробуйте другое фото.")
        return
    
    # Обработка текстовых сообщений
    user_text = msg.text.strip()
    
    # Если это первый запрос без контекста
    if user_id not in user_context:
        await msg.reply_text(
            "ℹ️ Пожалуйста, сначала отправьте изображение с текстом, "
            "чтобы я мог его проанализировать, а затем задайте вопрос."
        )
        return
    
    # Проверка на команды управления
    if user_text.lower() == '/clear':
        user_context.pop(user_id, None)
        await msg.reply_text("🔄 Контекст очищен. Отправьте новое изображение.")
        return
    
    # Получаем контекст пользователя
    context_text = user_context[user_id]
    
    # Показываем статус обработки
    status_msg = await msg.reply_text("🔍 Анализирую ваш вопрос...")
    
    try:
        # Получаем ответ
        answer = await get_answer(user_text, context_text)
        
        # Форматируем ответ
        response = f"❓ Вопрос: {user_text}\n\n"
        response += f"💡 Ответ: {answer}\n\n"
        response += "Для нового запроса отправьте /clear"
        
        await status_msg.edit_text(response)
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        await status_msg.edit_text("⚠️ Произошла ошибка при обработке вашего вопроса. Попробуйте снова.")

def main() -> None:
    """Запуск бота."""
    # Получение токена из переменных окружения
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Токен Telegram бота не установлен в переменных окружения!")
    
    # Установка пути к Tesseract (уже настроено в Dockerfile)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    
    # Предварительная инициализация модели (если есть GPU)
    if os.getenv('PRELOAD_MODEL', 'false') == 'true':
        init_qa_model()
    
    # Создание приложения
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков
    application.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчик команды /clear
    application.add_handler(MessageHandler(filters.Regex(r'^/clear$'), handle_message))
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
