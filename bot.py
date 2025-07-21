import os
import logging
from telegram import Update
from telegram.ext import (
    Updater, 
    CommandHandler, 
    MessageHandler, 
    Filters, 
    CallbackContext
)

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База данных (в реальном проекте используйте SQLite/PostgreSQL)
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
    }
}

# Обработчики команд
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Привет! Кидай мне вопрос/задачу, а я найду ответ с источником.\n"
        "Пример: 'теорема пифагора'"
    )

def handle_text(update: Update, context: CallbackContext) -> None:
    user_text = update.message.text.lower().strip()
    response = QA_DATABASE.get(user_text)
    
    if response:
        reply = f"✅ Ответ:\n{response['answer']}\n\n🔗 Источник:\n{response['source']}"
    else:
        reply = "❌ Ответ не найден. Попробуй задать вопрос иначе."
    
    update.message.reply_text(reply)

def main() -> None:
    # Получаем токен из переменных окружения
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TOKEN.")
        return

    # Создаем бота
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Регистрируем обработчики
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    # Режим работы (для Render)
    PORT = int(os.environ.get('PORT', 10000))
    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://your-render-app-name.onrender.com/{TOKEN}"
    )
    updater.idle()

if __name__ == '__main__':
    main()
