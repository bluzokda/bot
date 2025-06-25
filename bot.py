import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение переменных окружения (на Render.com они задаются в Dashboard)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')

# Если запускаем локально (для теста)
if not TELEGRAM_TOKEN or not WEATHER_API_KEY:
    from dotenv import load_dotenv
    load_dotenv()
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен!")
if not WEATHER_API_KEY:
    raise ValueError("WEATHER_API_KEY не установлен!")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_html(
        f"👋 Привет {user.mention_html()}!\n"
        "Я бот с функцией погоды!\n\n"
        "Используй команды:\n"
        "/start - это сообщение\n"
        "/help - помощь\n"
        "/weather <город> - погода в указанном городе\n\n"
        "Пример: /weather Москва"
    )

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Помощь:\n/weather <город> - узнать погоду")

# Команда /weather
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args)
    if not city:
        await update.message.reply_text("⚠️ Укажите город!\nПример: /weather Москва")
        return
    
    try:
        weather_data = get_weather(city)
        await update.message.reply_text(weather_data)
    except Exception as e:
        logger.error(f"Weather error: {e}")
        await update.message.reply_text("😢 Не удалось получить погоду. Попробуйте позже.")

def get_weather(city: str) -> str:
    """Получение погоды через OpenWeatherMap API"""
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        'q': city,
        'appid': WEATHER_API_KEY,
        'units': 'metric',
        'lang': 'ru'
    }
    
    response = requests.get(base_url, params=params, timeout=10)
    data = response.json()
    
    if response.status_code != 200:
        logger.error(f"API Error: {data.get('message', 'Unknown error')}")
        return "❌ Ошибка при запросе погоды. Проверьте название города."
    
    weather_desc = data['weather'][0]['description'].capitalize()
    temp = data['main']['temp']
    feels_like = data['main']['feels_like']
    humidity = data['main']['humidity']
    wind = data['wind']['speed']
    
    return (
        f"🌆 Погода в {city}:\n"
        f"🌡 {temp}°C (ощущается как {feels_like}°C)\n"
        f"📝 {weather_desc}\n"
        f"💧 Влажность: {humidity}%\n"
        f"💨 Ветер: {wind} м/с"
    )

def main():
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("weather", weather))
    
    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
