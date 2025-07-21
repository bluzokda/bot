import os
import telebot
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

# Инициализация Flask приложения
app = Flask(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
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
        
        # Поиск результатов (Google часто меняет структуру, поэтому проверяем несколько вариантов)
        for block in soup.find_all('div', class_=['tF2Cxc', 'MjjYud', 'g Ww4FFb vt6azd tF2Cxc'])[:3]:
            title_elem = block.find('h3') or block.find('div', role='heading')
            if not title_elem:
                continue
                
            title = title_elem.text
            link_elem = block.find('a', href=True)
            link = link_elem['href'] if link_elem else "#"
            
            snippet_elem = block.find(attrs={'data-sncf': True}) or block.find('div', class_=['VwiC3b', 'yXK7lf'])
            snippet = snippet_elem.text if snippet_elem else "Описание отсутствует"
            
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet[:300] + "..." if len(snippet) > 300 else snippet  # Ограничение длины
            })
            
        return results if results else None
        
    except requests.exceptions.Timeout:
        return [{"title": "⏱️ Таймаут запроса", "snippet": "Google не ответил вовремя", "url": ""}]
    except Exception as e:
        print(f"Ошибка поиска: {str(e)}")
        return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Задай любой вопрос, и я найду ответ с источниками!\n\n"
                          "Например: \n• Что такое ООП?\n• Формула дискриминанта\n• История второй мировой войны")

@bot.message_handler(func=lambda msg: True)
def handle_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        search_results = google_search(message.text)
        
        if not search_results:
            return bot.reply_to(message, "❌ Ничего не найдено. Попробуйте переформулировать вопрос.")
        
        response = "🔍 Вот что я нашел по вашему запросу:\n\n"
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
        print(f"Ошибка обработки сообщения: {str(e)}")
        bot.reply_to(message, f"⚠️ Произошла ошибка: {str(e)}")

# Вебхук обработчики
@app.route('/')
def home():
    return "🤖 Telegram Search Bot работает! Добавьте /webhook для обработки сообщений."

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad request', 400

def setup_webhook():
    """Настройка вебхука при запуске на Render"""
    if os.environ.get('RENDER'):
        external_url = os.environ.get('RENDER_EXTERNAL_URL')
        if external_url:
            webhook_url = f"{external_url}/webhook"
            bot.remove_webhook()
            bot.set_webhook(url=webhook_url)
            print(f"Webhook установлен: {webhook_url}")
        else:
            print("RENDER_EXTERNAL_URL не установлен!")
    else:
        print("Локальный режим: вебхук не используется")

if __name__ == '__main__':
    setup_webhook()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
