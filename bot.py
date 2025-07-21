import os
import logging
import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База знаний
QA_DATABASE = {
    "теорема пифагора": {
        "answer": "a² + b² = c²",
        "source": "https://ru.wikipedia.org/wiki/Теорема_Пифагора"
    },
    "формула дискриминанта": {
        "answer": "D = b² - 4ac",
        "source": "https://ru.wikipedia.org/wiki/Дискриминант"
    },
    "столица россии": {
        "answer": "Москва",
        "source": "https://ru.wikipedia.org/wiki/Москва"
    },
    "формула эйнштейна": {
        "answer": "E = mc²",
        "source": "https://ru.wikipedia.org/wiki/Эквивалентность_массы_и_энергии"
    },
    "закон ома": {
        "answer": "I = U/R",
        "source": "https://ru.wikipedia.org/wiki/Закон_Ома"
    }
}

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Кидай мне вопрос/задачу, а я найду ответ с источником.\n"
        "Примеры вопросов:\n"
        "- теорема пифагора\n"
        "- формула дискриминанта\n"
        "- столица россии\n"
        "- формула эйнштейна\n"
        "- закон ома"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text.lower().strip()
    
    # Поиск наиболее подходящего вопроса
    response = None
    for question in QA_DATABASE:
        if question in user_text:
            response = QA_DATABASE[question]
            break
    
    if response:
        reply = f"✅ Ответ:\n{response['answer']}\n\n🔗 Источник:\n{response['source']}"
    else:
        reply = "❌ Ответ не найден. Попробуй задать вопрос иначе."
    
    await update.message.reply_text(reply)

def main() -> None:
    # Получаем токен и исправляем возможные проблемы
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip().replace(' ', '').replace(':', '')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TELEGRAM_BOT_TOKEN.")
        return

    # Получаем имя приложения из URL
    app_url = os.getenv('REDDER_APP_NAME', '').strip()
    if app_url:
        # Извлекаем имя приложения из URL
        match = re.search(r'https?://([^.]+)\.onrender\.com', app_url)
        if match:
            RENDER_APP_NAME = match.group(1)
        else:
            # Если не смогли распарсить, используем весь URL
            RENDER_APP_NAME = app_url
            logger.warning(f"Не удалось извлечь имя приложения из URL: {app_url}")
    else:
        RENDER_APP_NAME = ""
        logger.warning("REDDER_APP_NAME не установлен")

    # Получаем порт
    try:
        PORT = int(os.environ.get('PORT', 1000))
    except ValueError:
        PORT = 1000
        logger.warning(f"Некорректное значение PORT, используется {PORT}")

    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_APP_NAME:
        # Режим для облака
        webhook_url = f"https://{RENDER_APP_NAME}.onrender.com/{TOKEN}"
        
        # Установка вебхука
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=webhook_url,
            secret_token='RENDER',
            drop_pending_updates=True
        )
        logger.info(f"Бот запущен в облаке: {webhook_url}")
    else:
        # Локальный режим
        app.run_polling()
        logger.info("Бот запущен локально")

if __name__ == '__main__':
    main()
