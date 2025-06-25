import logging
import os
import sys
import sqlite3
import httpx
import requests
import asyncio
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackContext
)

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
logger.info("=== ПРИЛОЖЕНИЕ ЗАПУЩЕНО ===")

# Проверка критически важных переменных среды
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

if not TOKEN:
    logger.critical("ТОКЕН БОТА НЕ НАЙДЕН! Проверьте переменную TELEGRAM_BOT_TOKEN")
    sys.exit(1)

logger.info("Переменные среды загружены успешно")

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
        if conn:
            conn.close()

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

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        user_id = update.effective_user.id
        task = " ".join(context.args)
        if not task:
            await update.message.reply_text("Укажи задачу после команды /add")
            return

        conn = sqlite3.connect('tasks.db')
        c = conn.cursor()
        c.execute("INSERT INTO tasks (user_id, task) VALUES (?, ?)", (user_id, task))
        conn.commit()
        await update.message.reply_text(f"✅ Добавлено: {task}")
    except Exception as e:
        logger.error(f"Ошибка в add_task: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при добавлении задачи")
    finally:
        if conn:
            conn.close()

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        user_id = update.effective_user.id
        conn = sqlite3.connect('tasks.db')
        c = conn.cursor()
        c.execute("SELECT rowid, task FROM tasks WHERE user_id = ? AND completed = 0", (user_id,))
        tasks = c.fetchall()

        if not tasks:
            await update.message.reply_text("🎉 Список задач пуст!")
            return

        task_list = "\n".join([f"{task[0]}. {task[1]}" for task in tasks])
        await update.message.reply_text("📝 Твои задачи:\n" + task_list)
    except Exception as e:
        logger.error(f"Ошибка в list_tasks: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при получении списка задач")
    finally:
        if conn:
            conn.close()

async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text("Укажи номер задачи после команды /done")
            return

        task_id = int(context.args[0])
        conn = sqlite3.connect('tasks.db')
        c = conn.cursor()
        c.execute("SELECT task FROM tasks WHERE rowid = ? AND user_id = ?", (task_id, user_id))
        task = c.fetchone()
        
        if task:
            c.execute("UPDATE tasks SET completed = 1 WHERE rowid = ?", (task_id,))
            conn.commit()
            await update.message.reply_text(f"✅ Выполнено: {task[0]}")
        else:
            await update.message.reply_text("⚠️ Задача не найдена")
    except ValueError:
        await update.message.reply_text("🔢 Укажи номер задачи (цифру)")
    except Exception as e:
        logger.error(f"Ошибка в done_task: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при выполнении задачи")
    finally:
        if conn:
            conn.close()

# === Напоминалка / Reminder ===
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 4 or args[0] != "через" or args[2] != "минут":
            await update.message.reply_text("Используй формат:\n/remind через X минут [сообщение]")
            return

        minutes = int(args[1])
        message = " ".join(args[3:])

        if not message:
            await update.message.reply_text("Нет сообщения для напоминания.")
            return

        job_queue = context.job_queue
        chat_id = update.effective_message.chat_id
        
        # ИСПРАВЛЕННАЯ СТРОКА: добавлена закрывающая скобка
        job_queue.run_once(
            callback=reminder_callback, 
            when=minutes * 60, 
            data=message,
            chat_id=chat_id,
            name=str(chat_id))
        
        await update.message.reply_text(f"⏰ Напоминание установлено! Через {minutes} минут напомню: '{message}'")
    except Exception as e:
        logger.error(f"Ошибка в remind: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при установке напоминания")

async def reminder_callback(context: CallbackContext):
    try:
        job = context.job
        await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ Напоминание: {job.data}")
    except Exception as e:
        logger.error(f"Ошибка в reminder_callback: {e}")

# === Погода / Weather ===
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Укажи город после команды /weather\nНапример: /weather Москва")
            return

        city = " ".join(context.args)
        url = f"https://api.weatherapi.com/v1/current.json?key={os.getenv('WEATHER_API_KEY')}&q={city}&lang=ru"

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()

            if "error" in data:
                error_msg = data['error']['message']
                await update.message.reply_text(f"🚫 Ошибка погодного сервиса: {error_msg}")
                return

            location = data["location"]["name"]
            temp_c = data["current"]["temp_c"]
            condition = data["current"]["condition"]["text"]
            wind_kph = data["current"]["wind_kph"]
            humidity = data["current"]["humidity"]
            feelslike_c = data["current"]["feelslike_c"]

            reply = (
                f"🌤 Погода в {location}:\n"
                f"🌡 Температура: {temp_c}°C (ощущается как {feelslike_c}°C)\n"
                f"☁️ Состояние: {condition}\n"
                f"💨 Ветер: {wind_kph} км/ч\n"
                f"💧 Влажность: {humidity}%"
            )
            await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Ошибка в weather: {e}")
        await update.message.reply_text("⚠️ Не удалось получить данные о погоде. Попробуй позже")

# === Функция для выполнения поиска через Google ===
def search_google(query):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36"
        }
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []

        for result in soup.find_all('div', class_='tF2Cxc'):
            title_element = result.find('h3')
            link_element = result.find('a')
            snippet_element = result.find('div', class_='VwiC3b')
            
            if title_element and link_element:
                title = title_element.text
                link = link_element['href']
                snippet = snippet_element.text if snippet_element else "Описание отсутствует"
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet[:200] + "..." if len(snippet) > 200 else snippet
                })
                
                if len(results) >= 5:
                    break

        return results
    except Exception as e:
        logger.error(f"Ошибка в search_google: {e}")
        return []

# === Команда /search ===
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("🔍 Используй: /search [запрос]\nПримеры:\n"
                                            "/search roblox секретный танк\n"
                                            "/search minecraft как найти крепость")
            return

        query = " ".join(context.args)
        await update.message.reply_text(f"🔎 Ищу: {query}...")

        results = search_google(query)

        if not results:
            await update.message.reply_text("😕 Ничего не найдено. Попробуй другой запрос")
            return

        reply = f"🔍 Результаты по запросу «{query}»:\n\n"
        for i, res in enumerate(results, start=1):
            reply += f"{i}. <b>{res['title']}</b>\n"
            reply += f"{res['snippet']}\n"
            reply += f"<a href='{res['link']}'>Открыть</a>\n\n"

        await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в search_command: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при поиске. Попробуй позже")

# === Обработка ошибок ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logger.error(f"Ошибка: {context.error}", exc_info=context.error)
        if update and hasattr(update, 'message'):
            await update.message.reply_text("⚠️ Произошла ошибка при обработке запроса. Попробуй снова")
    except Exception as e:
        logger.error(f"Ошибка в обработчике ошибок: {e}")

# === Запуск бота === 
async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Очередь обновлений очищена")
        
        me = await application.bot.get_me()
        logger.info(f"Бот успешно запущен: @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")
        raise

def main():
    try:
        logger.info("Создание ApplicationBuilder...")
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
        
        logger.info("Регистрация обработчиков команд...")
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("add", add_task))
        app.add_handler(CommandHandler("list", list_tasks))
        app.add_handler(CommandHandler("done", done_task))
        app.add_handler(CommandHandler("remind", remind))
        app.add_handler(CommandHandler("weather", weather))
        app.add_handler(CommandHandler("search", search_command))
        
        logger.info("Регистрация обработчика ошибок...")
        app.add_error_handler(error_handler)
        
        logger.info("Запуск бота в режиме polling...")
        app.run_polling()
        
    except Exception as e:
        logger.critical(f"ФАТАЛЬНАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    logger.info("Запуск main()")
    main()
