import os
import logging
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
    # Получаем токен
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    
    # Проверяем формат токена
    if not TOKEN or ':' not in TOKEN:
        logger.error("Неверный формат токена! Токен должен быть в формате 'число:строка'")
        logger.error(f"Текущий токен: '{TOKEN}'")
        return

    # Получаем имя приложения
    RENDER_APP_NAME = os.getenv('RENDER_APP_NAME', '').strip()
    if not RENDER_APP_NAME:
        logger.warning("RENDER_APP_NAME не установлен. Используется локальный режим.")
    
    # Получаем порт
    try:
        PORT = int(os.environ.get('PORT', 1000))
    except ValueError:
        PORT = 1000
        logger.warning(f"Некорректное значение PORT, используется {PORT}")

    # Создаем приложение
    try:
        app = ApplicationBuilder().token(TOKEN).build()
        logger.info("Бот успешно инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации бота: {e}")
        return

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_APP_NAME:
        # Режим для облака
        webhook_url = f"https://{RENDER_APP_NAME}.onrender.com"
        logger.info(f"Попытка запуска в облаке: {webhook_url}")
        
        try:
            # Установка вебхука
            app.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                webhook_url=webhook_url,
                secret_token='RENDER',
                drop_pending_updates=True
            )
            logger.info(f"Бот запущен в облаке")
        except Exception as e:
            logger.error(f"Ошибка запуска вебхука: {e}")
            logger.info("Попытка запуска в режиме polling")
            app.run_polling()
    else:
        # Локальный режим
        logger.info("Запуск в локальном режиме (polling)")
        app.run_polling()

if __name__ == '__main__':
    main()
