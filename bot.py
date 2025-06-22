from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import asyncio
import httpx

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Словарь для хранения задач пользователей
user_tasks = {}  # {user_id: [список задач]}

# === Функции To-do List ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой бот-органайзер. Используй:\n"
                                    "/add [задача] — добавить задачу\n"
                                    "/list — посмотреть список задач\n"
                                    "/done [номер] — отметить выполненной\n"
                                    "/remind через [X] минут [сообщение] — настроить напоминание\n"
                                    "/weather [город] — узнать погоду")


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
    url = f"https://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={city}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            data = response.json()

            if "error" in data:
                await update.message.reply_text("Не удалось найти такой город.")
                return

            temp_c = data["current"]["temp_c"]
            condition = data["current"]["condition"][0]["text"]
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
            await update.message.reply_text("Ошибка при получении данных о погоде.")
            print(e)


# === Запуск бота === 
app = ApplicationBuilder().token(TOKEN).build()

# Регистрируем команды
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_task))
app.add_handler(CommandHandler("list", list_tasks))
app.add_handler(CommandHandler("done", done_task))
app.add_handler(CommandHandler("remind", remind))
app.add_handler(CommandHandler("weather", weather))

print("Бот запущен...")
app.run_polling()
