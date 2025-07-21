import os
import telebot
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен!")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

bot = telebot.TeleBot(BOT_TOKEN)

# Настройки поиска
SEARCH_URL = "https://www.google.com/search?q={}&hl=ru"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

def google_search(query):
    """Выполняет поиск в Google и возвращает топ-3 результата"""
    try:
        formatted_query = query.replace(" ", "+")
        response = requests.get(
            SEARCH_URL.format(formatted_query), 
            headers=HEADERS, 
            timeout=10
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        results = []
        
        # Универсальные селекторы для разных версий Google
        result_blocks = soup.find_all('div', class_='tF2Cxc') or soup.find_all('div', class_='MjjYud')
        
        for block in result_blocks[:3]:
            title_elem = block.find('h3') or block.find('div', role='heading') or block.find('h3', class_='LC20lb')
            link_elem = block.find('a', href=True)
            snippet_elem = block.find('div', class_='VwiC3b') or block.find('div', class_='yXK7lf')
            
            title = title_elem.get_text(strip=True) if title_elem else "Без названия"
            link = link_elem['href'] if link_elem else "#"
            snippet = snippet_elem.get_text(strip=True)[:300] if snippet_elem else "Описание отсутствует"
            
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet
            })
            
        return results if results else None
        
    except requests.exceptions.Timeout:
        return [{"title": "⏱️ Таймаут запроса", "snippet": "Google не ответил вовремя", "url": ""}]
    except Exception as e:
        logger.error(f"Ошибка поиска: {str(e)}")
        return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Я твой поисковый бот-помощник. Просто задай любой вопрос, например:\n\n"
                          "• Что такое ООП?\n"
                          "• Формула дискриминанта\n"
                          "• История Второй мировой войны\n\n"
                          "Я найду ответ и покажу источники!")

@bot.message_handler(func=lambda msg: True)
def handle_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        search_results = google_search(message.text)
        
        if not search_results:
            return bot.reply_to(message, "❌ По вашему запросу ничего не найдено. Попробуйте переформулировать вопрос.")
        
        response = "🔍 Вот что я нашел:\n\n"
        for i, res in enumerate(search_results, 1):
            response += f"<b>{i}. {res['title']}</b>\n"
            response += f"<i>{res['snippet']}</i>\n"
            response += f"<a href='{res['url']}'>🔗 Источник</a>\n\n"
        
        bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {str(e)}")
        bot.reply_to(message, "⚠️ Произошла ошибка при обработке запроса. Попробуйте позже.")

@app.route('/')
def home():
    return "🤖 Telegram Search Bot активен! Используйте /start в Telegram"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad request', 400

def configure_webhook():
    """Настраивает вебхук при запуске приложения"""
    try:
        # Для Render.com
        if os.environ.get('RENDER'):
            external_url = os.environ.get('RENDER_EXTERNAL_URL')
            if external_url:
                webhook_url = f"{external_url}/webhook"
                bot.remove_webhook()
                bot.set_webhook(url=webhook_url)
                logger.info(f"Вебхук установлен: {webhook_url}")
                return
            else:
                logger.warning("RENDER_EXTERNAL_URL не найден!")
        
        # Для других платформ/локального запуска
        bot.remove_webhook()
        logger.info("Вебхук удален, используется polling")
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {str(e)}")

# Конфигурируем вебхук при импорте модуля
configure_webhook()

if __name__ == '__main__':
    # Локальный запуск
    logger.info("Локальный запуск: используется polling")
    bot.remove_webhook()
    bot.infinity_polling()
