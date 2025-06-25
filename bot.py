from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackContext
)
import os
import sqlite3
import httpx
import requests
from bs4 import BeautifulSoup
import logging
import time

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("Токен бота не найден! Убедитесь, что TELEGRAM_BOT_TOKEN установлен в переменных окружения.")
    exit(1)

# === Инициализация базы данных ===
def init_db():
    try:
        conn = sqlite3.connect('tasks.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (user_id INTEGER, task TEXT, completed INTEGER DEFAULT 0)''')
        conn.commit()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
    finally:
        conn.close()

init_db()

# === Функции To-do List ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"Обработка /start от пользователя {update.effective_user.id}")
        await update.message.reply_text("Привет! Я твой бот-кент. Используй:\n"
                                       "/add [задача] — добавить задачу\n"
                                       "/list — посмотреть список задач\n"
                                       "/done [номер] — отметить выполненной\n"
                                       "/remind через [X] минут [сообщение] — настроить напоминание\n"
                                       "/weather [город] — узнать погоду\n"
                                       "/search [запрос] — искать информацию в интернете")
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")

# ... (остальные функции остаются без изменений из предыдущего рабочего кода) ...

# === Запуск бота === 
async def post_init(application):
    try:
        # Очищаем обновления при запуске
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Очередь обновлений очищена")
        
        # Проверяем доступность бота
        me = await application.bot.get_me()
        logger.info(f"Бот успешно запущен: @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")
        raise

def main():
    try:
        logger.info("Попытка запуска бота...")
        
        # Создаем приложение с очисткой обновлений
        app = ApplicationBuilder() \
            .token(TOKEN) \
            .post_init(post_init) \
            .build()

        # Регистрируем команды
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("add", add_task))
        app.add_handler(CommandHandler("list", list_tasks))
        app.add_handler(CommandHandler("done", done_task))
        app.add_handler(CommandHandler("remind", remind))
        app.add_handler(CommandHandler("weather", weather))
        app.add_handler(CommandHandler("search", search_command))
        
        # Регистрируем обработчик ошибок
        app.add_error_handler(error_handler)

        logger.info("Запуск бота в режиме polling...")
        app.run_polling()
        
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}")

if __name__ == '__main__':
    main()
