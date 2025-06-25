from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import asyncio
import httpx
import requests
import time
import csv
from datetime import datetime
import logging

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем ID администратора
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", 0))

# Файл для хранения информации о пользователях
USERS_FILE = "bot_users.csv"

# Словарь для хранения задач пользователей
user_tasks = {}  # {user_id: [список задач]}

# === Инициализация файла пользователей ===
def init_users_file():
    try:
        if not os.path.exists(USERS_FILE):
            logger.info("Создаю новый файл пользователей")
            with open(USERS_FILE, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["user_id", "first_name", "last_name", "username", "first_seen"])
        else:
            logger.info("Файл пользователей уже существует")
    except Exception as e:
        logger.error(f"Ошибка при создании файла пользователей: {e}")

# === Регистрация нового пользователя ===
def register_user(user):
    try:
        user_exists = False
        
        # Проверяем существование файла
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                try:
                    next(reader)  # Пропускаем заголовок
                except StopIteration:
                    pass
                
                for row in reader:
                    if row and row[0].isdigit() and int(row[0]) == user.id:
                        user_exists = True
                        break
        
        # Добавляем нового пользователя
        if not user_exists:
            with open(USERS_FILE, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    user.id,
                    user.first_name,
                    user.last_name or "",
                    user.username or "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
            logger.info(f"Зарегистрирован новый пользователь: {user.id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя: {e}")
        return False

# === Отправка уведомления администратору ===
async def notify_admin(context, user, is_new=False):
    try:
        if ADMIN_ID:
            message = "🆕 Новый пользователь!" if is_new else "👤 Повторный вход"
            text = (
                f"{message}\n\n"
                f"ID: {user.id}\n"
                f"Имя: {user.first_name}\n"
                f"Фамилия: {user.last_name or '-'}\n"
                f"Username: @{user.username or '-'}\n"
                f"Время: {datetime.now().strftime('%H:%M:%S')}"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=text)
            logger.info(f"Уведомление отправлено администратору {ADMIN_ID}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")

# === Команда /admin для получения списка пользователей ===
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        
        # Проверяем права администратора
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ Эта команда доступна только администратору")
            return
        
        # Отправляем файл с пользователями
        if os.path.exists(USERS_FILE):
            await update.message.reply_document(
                document=open(USERS_FILE, "rb"),
                filename="bot_users.csv",
                caption="📊 Список пользователей бота"
            )
            logger.info(f"Администратор {ADMIN_ID} запросил файл пользователей")
        else:
            await update.message.reply_text("Файл с пользователями не найден")
            logger.warning("Файл пользователей не найден при запросе администратора")
    except Exception as e:
        logger.error(f"Ошибка в команде /admin: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды")

# === Функции To-do List ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        logger.info(f"Обработка /start от пользователя {user.id}")
        
        # Регистрируем пользователя и отправляем уведомление
        is_new = register_user(user)
        await notify_admin(context, user, is_new)
        
        # Оригинальное сообщение
        await update.message.reply_text("Привет! Я твой бот-кент. Используй:\n"
                                        "/add [задача] — добавить задачу\n"
                                        "/list — посмотреть список задач\n"
                                        "/done [номер] — отметить выполненной\n"
                                        "/remind через [X] минут [сообщение] — настроить напоминание\n"
                                        "/weather [город] — узнать погоду\n"
                                        "/search [запрос] — искать информацию в интернете")
                                       
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        task = " ".join(context.args)
        if not task:
            await update.message.reply_text("Укажи задачу после команды /add")
            return

        if user_id not in user_tasks:
            user_tasks[user_id] = []

        user_tasks[user_id].append(task)
        await update.message.reply_text(f"Добавлено: {task}")
    except Exception as e:
        logger.error(f"Ошибка в команде /add: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении задачи")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        tasks = user_tasks.get(user_id, [])

        if not tasks:
            await update.message.reply_text("Список задач пуст.")
            return

        task_list = "\n".join([f"{i+1}. {task}" for i, task in enumerate(tasks)])
        await update.message.reply_text("Твои задачи:\n" + task_list)
    except Exception as e:
        logger.error(f"Ошибка в команде /list: {e}")
        await update.message.reply_text("Произошла ошибка при получении списка задач")


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        tasks = user_tasks.get(user_id, [])

        if not context.args:
            await update.message.reply_text("Укажи номер задачи после команды /done")
            return

        try:
            index = int(context.args[0]) - 1
            task = tasks.pop(index)
            await update.message.reply_text(f"Выполнено: {task}")
        except (ValueError, IndexError):
            await update.message.reply_text("Неверный номер задачи.")
    except Exception as e:
        logger.error(f"Ошибка в команде /done: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении задачи")


# === Напоминалка / Reminder ===
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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

        await update.message.reply_text(f"Напомню через {minutes} минут: '{message}'")

        # Запуск напоминания в фоне
        asyncio.create_task(reminder_task(update.effective_user.id, minutes, message, context))
    except Exception as e:
        logger.error(f"Ошибка в команде /remind: {e}")
        await update.message.reply_text("Произошла ошибка при создании напоминания")


async def reminder_task(user_id, minutes, message, context):
    try:
        await asyncio.sleep(minutes * 60)
        await context.bot.send_message(chat_id=user_id, text=f"⏰ Напоминание: {message}")
    except Exception as e:
        logger.error(f"Ошибка в напоминании: {e}")


# === Погода / Weather ===
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")  # Берём из .env или Render


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Укажи город после команды /weather")
            return

        city = " ".join(context.args)
        url = f"https://api.weatherapi.com/v1/current.json?key={os.getenv('WEATHER_API_KEY')}&q={city}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url)
                data = response.json()

                if "error" in data:
                    await update.message.reply_text(f"Ошибка WeatherAPI: {data['error']['message']}")
                    return

                temp_c = data["current"]["temp_c"]
                condition = data["current"]["condition"]["text"]
                wind_kph = data["current"]["wind_kph"]
                humidity = data["current"]["humidity"]

                reply = (
                    f"🌤 Погода в {city}:\n"
                    f"Температура: {temp_c}°C\n"
                    f"Состояние: {condition}\n"
                    f"Ветер: {wind_kph} км/ч\n"
                    f"Влажность: {humidity}%"
                )
                await update.message.reply_text(reply)

            except Exception as e:
                await update.message.reply_text(f"Ошибка при получении данных о погоде: {str(e)}")
                logger.error(f"Ошибка WeatherAPI: {e}")
    except Exception as e:
        logger.error(f"Ошибка в команде /weather: {e}")
        await update.message.reply_text("Произошла ошибка при получении погоды")


# === Альтернативная функция поиска через DuckDuckGo API ===
def search_duckduckgo(query, max_results=5):
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1,
        "skip_disambig": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        results = []
        # Основной результат
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", "Основной результат"),
                "snippet": data.get("AbstractText", ""),
                "link": data.get("AbstractURL", "")
            })
        
        # Дополнительные результаты
        for i, topic in enumerate(data.get("RelatedTopics", [])):
            if "Result" in topic:
                result = topic["Result"]
                # Парсим результат (простейший парсинг)
                parts = result.split('">')
                if len(parts) > 1:
                    title = parts[1].split("</a>")[0].strip()
                    snippet = parts[2].split("</a>")[0].strip() if len(parts) > 2 else ""
                    link = parts[0].split('href="')[1].strip()
                    
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "link": link
                    })
            
            if len(results) >= max_results:
                break
        
        return results
    
    except Exception as e:
        logger.error(f"DuckDuckGo search error: {e}")
        return []

# === Обновлённая команда /search ===
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Используй: /search [запрос]. Например:\n"
                                            "/search game 123\n"
                                            "/search game 123")
            return

        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Ищу в интернете: {query}...")

        try:
            results = search_duckduckgo(query)

            if not results:
                await update.message.reply_text("❌ Ничего не найдено. Попробуйте другой запрос.")
                return

            reply = f"🔎 Результаты по запросу «{query}»:\n\n"
            for i, res in enumerate(results, start=1):
                title = res.get('title', 'Без названия')
                snippet = res.get('snippet', 'Без описания')
                link = res.get('link', '')
                
                if link:
                    reply += f"{i}. <b>{title}</b>\n"
                    reply += f"{snippet}\n"
                    reply += f"<a href='{link}'>Открыть</a>\n\n"
                else:
                    reply += f"{i}. <b>{title}</b>\n{snippet}\n\n"

            await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=True)

        except Exception as e:
            await update.message.reply_text(f"⚠️ Ошибка при поиске: {str(e)}")
            logger.error(f"Ошибка поиска: {e}")
    except Exception as e:
        logger.error(f"Ошибка в команде /search: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении поиска")

# === Команда для проверки ID ===
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        await update.message.reply_text(
            f"👤 Ваши данные:\n"
            f"ID: {user.id}\n"
            f"Имя: {user.first_name}\n"
            f"Фамилия: {user.last_name or '-'}\n"
            f"Username: @{user.username or '-'}\n\n"
            f"ADMIN_ID: {ADMIN_ID}"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /myid: {e}")

# === Команда для проверки файла ===
async def check_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        exists = os.path.exists(USERS_FILE)
        size = os.path.getsize(USERS_FILE) if exists else 0
        await update.message.reply_text(
            f"Файл пользователей: {'существует' if exists else 'не существует'}\n"
            f"Размер: {size} байт"
        )
        
        if exists:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                content = f.read(1000)
            await update.message.reply_text(f"Первые 1000 символов:\n{content}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка проверки файла: {e}")

# === Запуск бота === 
if __name__ == "__main__":
    # Инициализируем файл пользователей
    init_users_file()
    
    # Создаем приложение
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("myid", myid))  # Для проверки ID
    app.add_handler(CommandHandler("checkfile", check_file))  # Для проверки файла

    print("Бот запущен...")
    logger.info("Бот запущен")
    app.run_polling()
