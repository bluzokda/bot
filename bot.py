from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import asyncio
import httpx
import requests
import time
from bs4 import BeautifulSoup 

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Словарь для хранения задач пользователей
user_tasks = {}  # {user_id: [список задач]}

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

    if user_id not in user_tasks:
        user_tasks[user_id] = []

    user_tasks[user_id].append(task)
    await update.message.reply_text(f"Добавлено: {task}")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = user_tasks.get(user_id, [])

    if not tasks:
        await update.message.reply_text("Список задач пуст.")
        return

    task_list = "\n".join([f"{i+1}. {task}" for i, task in enumerate(tasks)])
    await update.message.reply_text("Твои задачи:\n" + task_list)


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await update.message.reply_text(f"Напомню через {minutes} минут: '{message}'")

    # Запуск напоминания в фоне
    asyncio.create_task(reminder_task(update.effective_user.id, minutes, message, context))


async def reminder_task(user_id, minutes, message, context):
    await asyncio.sleep(minutes * 60)
    await context.bot.send_message(chat_id=user_id, text=f"⏰ Напоминание: {message}")


# === Погода / Weather ===
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")  # Берём из .env или Render


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            print(e)  # Для отладки 


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
        print(f"DuckDuckGo search error: {e}")
        return []

# === Обновлённая команда /search ===
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Используй: /search [запрос]. Например:\n"
                                        "/search roblox секретный танк\n"
                                        "/search minecraft как найти крепость")
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
        print(f"Search error: {e}")
# === Запуск бота === 
app = ApplicationBuilder().token(TOKEN).build()

# Регистрируем команды
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_task))
app.add_handler(CommandHandler("list", list_tasks))
app.add_handler(CommandHandler("done", done_task))
app.add_handler(CommandHandler("remind", remind))
app.add_handler(CommandHandler("weather", weather))
app.add_handler(CommandHandler("search", search_command))

print("Бот запущен...")
app.run_polling()
