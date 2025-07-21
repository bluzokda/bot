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

# База данных
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Кидай мне вопрос/задачу, а я найду ответ с источником.\n"
        "Пример: 'теорема пифагора'"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text.lower().strip()
    response = QA_DATABASE.get(user_text)
    
    if response:
        reply = f"✅ Ответ:\n{response['answer']}\n\n🔗 Источник:\n{response['source']}"
    else:
        reply = "❌ Ответ не найден. Попробуй задать вопрос иначе."
    
    await update.message.reply_text(reply)

def main() -> None:
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TOKEN.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Режим работы для Render
    PORT = int(os.environ.get('PORT', 10000))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
