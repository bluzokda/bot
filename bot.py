import logging
import os
import sys

# Самое первое - настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # Гарантированный вывод в stdout
)
logger = logging.getLogger(__name__)
logger.info("=== ПРИЛОЖЕНИЕ ЗАПУЩЕНО ===")

try:
    # Проверка критически важных переменных среды
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
    
    if not TOKEN:
        logger.critical("ТОКЕН БОТА НЕ НАЙДЕН! Проверьте переменную TELEGRAM_BOT_TOKEN")
        sys.exit(1)
        
    logger.info("Переменные среды загружены успешно")
    
    # Импорт зависимостей ПОСЛЕ настройки логгирования
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        CallbackContext
    )
    import sqlite3
    import httpx
    import requests
    from bs4 import BeautifulSoup
    
    logger.info("Зависимости импортированы")

except ImportError as e:
    logger.critical(f"ОШИБКА ИМПОРТА: {e}")
    sys.exit(1)
except Exception as e:
    logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАГРУЗКЕ: {e}")
    sys.exit(1)

# === Инициализация базы данных ===
def init_db():
    try:
        conn = sqlite3.connect('tasks.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (user_id INTEGER, task TEXT, completed INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

init_db()

# === Функции To-do List ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"Команда /start от {update.effective_user.id}")
        await update.message.reply_text("Привет! Я твой бот-кент. Используй:\n"
                                       "/add [задача] — добавить задачу\n"
                                       "/list — посмотреть список задач\n"
                                       "/done [номер] — отметить выполненной\n"
                                       "/remind через [X] минут [сообщение] — настроить напоминание\n"
                                       "/weather [город] — узнать погоду\n"
                                       "/search [запрос] — искать информацию в интернете")
    except Exception as e:
        logger.error(f"Ошибка в /start: {e}")

# ... (остальные функции из предыдущего кода остаются без изменений) ...

# === Запуск бота === 
async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        me = await application.bot.get_me(
