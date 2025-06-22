from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Словарь для хранения задач пользователей
user_tasks = {}  # {user_id: [список задач]}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой бот-органайзер. Используй:\n"
                                    "/add [задача] — добавить задачу\n"
                                    "/list — посмотреть список задач\n"
                                    "/done [номер] — отметить выполненной")

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

# === Запуск бота ===
app = ApplicationBuilder().token(TOKEN).build()

# Регистрируем команды
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_task))
app.add_handler(CommandHandler("list", list_tasks))
app.add_handler(CommandHandler("done", done_task))

print("Бот запущен...")
app.run_polling()
