from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
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

# === Инициализация базы данных ===
def init_db():
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (user_id INTEGER, task TEXT, completed INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# === Функции To-do List ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой бот-кент. Используй:\n"
                                    "/add [задача] — добавить задачу\n"
                                    "/list — посмотреть список задач\n"
                                    "/done [номер] — отметить выполненной\n"
                                    "/remind через [X] минут [сообщение] — настроить напоминание\n"
                                    "/weather [город] — узнать погоду\n"
                                    "/search [запрос] — искать информацию в интернете")


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    task = " ".join(context.args)
    if not task:
        await update.message.reply_text("Укажи задачу после команды /add")
        return

    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user_id, task) VALUES (?, ?)", (user_id, task))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Добавлено: {task}")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute("SELECT rowid, task FROM tasks WHERE user_id = ? AND completed = 0", (user_id,))
    tasks = c.fetchall()
    conn.close()

    if not tasks:
        await update.message.reply_text("🎉 Список задач пуст!")
        return

    task_list = "\n".join([f"{task[0]}. {task[1]}" for task in tasks])
    await update.message.reply_text("📝 Твои задачи:\n" + task_list)


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Укажи номер задачи после команды /done")
        return

    try:
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
        
        conn.close()
    except ValueError:
        await update.message.reply_text("🔢 Укажи номер задачи (цифру)")

# === Напоминалка / Reminder ===
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4 or args[0] != "через" or args[2] != "минут":
        await update.message.reply_text("Используй формат:\n/remind через X минут [сообщение]")
        return

    try:
        minutes = int(args[1])
        message = " ".join(args[3:])
    except ValueError:
        await update.message.reply_text("Время должно быть числом.")
        return

    if not message:
        await update.message.reply_text("Нет сообщения для напоминания.")
        return

    # Добавляем задание в JobQueue
    job_queue = context.job_queue
    chat_id = update.effective_message.chat_id
    
    job_queue.run_once(
        callback=reminder_callback, 
        when=minutes * 60, 
        data=message,
        chat_id=chat_id,
        name=str(chat_id)
    
    await update.message.reply_text(f"⏰ Напоминание установлено! Через {minutes} минут напомню: '{message}'")


async def reminder_callback(context: CallbackContext):
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ Напоминание: {job.data}")

# === Погода / Weather ===
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи город после команды /weather\nНапример: /weather Москва")
        return

    city = " ".join(context.args)
    url = f"https://api.weatherapi.com/v1/current.json?key={os.getenv('WEATHER_API_KEY')}&q={city}&lang=ru"

    async with httpx.AsyncClient() as client:
        try:
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
            logger.error(f"Weather error: {e}")
            await update.message.reply_text("⚠️ Не удалось получить данные о погоде. Попробуй позже")

# === Функция для выполнения поиска через Google ===
def search_google(query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36"
    }
    url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []

        # Ищем блоки с результатами 
        for result in soup.find_all('div', class_='tF2Cxc'):  # Актуальный класс для результатов
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
                
                if len(results) >= 5:  # Ограничиваем 5 результатами
                    break

        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

# === Команда /search ===
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔍 Используй: /search [запрос]\nПримеры:\n"
                                        "/search roblox секретный танк\n"
                                        "/search minecraft как найти крепость")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"🔎 Ищу: {query}...")

    try:
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
        logger.error(f"Search command error: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при поиске. Попробуй позже")

# === Обработка ошибок ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    
    if update and hasattr(update, 'message'):
        await update.message.reply_text("⚠️ Произошла ошибка при обработке запроса. Попробуй снова")

# === Запуск бота === 
async def post_init(application):
    # Очищаем обновления при запуске
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Очередь обновлений очищена")

def main():
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

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
