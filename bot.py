import os
import telebot
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен!")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

bot = telebot.TeleBot(BOT_TOKEN)
logger.info("Бот инициализирован")

# Настройки поиска
SEARCH_URL = "https://www.google.com/search?q={}&hl=ru"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

# Хранение истории (в реальном проекте используйте базу данных)
user_history = {}

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('Задать вопрос'))
    markup.add(KeyboardButton('История'))
    return markup

def google_search(query):
    """Выполняет поиск в Google и возвращает топ-3 результата"""
    try:
        logger.info(f"Поисковый запрос: {query}")
        formatted_query = query.replace(" ", "+")
        response = requests.get(
            SEARCH_URL.format(formatted_query), 
            headers=HEADERS, 
            timeout=10
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # Поиск результатов по разным возможным селекторам
        result_blocks = soup.select('div.g')[:5]  # Используем CSS-селектор
        
        for block in result_blocks:
            # Извлечение заголовка
            title_elem = block.select_one('h3')
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            
            # Извлечение ссылки
            link_elem = block.find('a', href=True)
            if not link_elem:
                continue
                
            link = link_elem['href']
            if link.startswith('/url?q='):
                link = link[7:].split('&')[0]
            
            # Извлечение описания
            snippet_elem = block.select_one('div.IsZvec, div.VwiC3b, span.aCOpRe')
            snippet = snippet_elem.get_text(strip=True)[:300] if snippet_elem else "Описание отсутствует"
            
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet
            })
            
            if len(results) >= 3:  # Ограничиваемся 3 результатами
                break
        
        logger.info(f"Найдено результатов: {len(results)}")
        return results if results else None
        
    except requests.exceptions.Timeout:
        logger.warning("Таймаут запроса к Google")
        return [{"title": "⏱️ Таймаут запроса", "snippet": "Google не ответил вовремя", "url": ""}]
    except Exception as e:
        logger.error(f"Ошибка поиска: {str(e)}")
        return None

def save_history(user_id, question, response):
    """Сохраняет историю запросов пользователя"""
    if user_id not in user_history:
        user_history[user_id] = []
    
    # Сохраняем только последние 10 записей
    if len(user_history[user_id]) >= 10:
        user_history[user_id].pop(0)
    
    user_history[user_id].append({
        "question": question,
        "response": response
    })

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        logger.info(f"Обработка команды /start от {message.chat.id}")
        response = (
            "👋 Привет! Я твой поисковый бот-помощник.\n\n"
            "Используй кнопки ниже, чтобы задать вопрос или посмотреть историю."
        )
        bot.send_message(
            message.chat.id,
            response,
            reply_markup=create_menu()
        )
        logger.info("Приветственное сообщение отправлено")
    except Exception as e:
        logger.error(f"Ошибка в send_welcome: {str(e)}")

@bot.message_handler(func=lambda message: message.text == 'Задать вопрос')
def handle_ask_question(message):
    try:
        logger.info(f"Обработка 'Задать вопрос' от {message.chat.id}")
        msg = bot.send_message(message.chat.id, "Введите ваш вопрос:", reply_markup=None)
        bot.register_next_step_handler(msg, process_question)
    except Exception as e:
        logger.error(f"Ошибка в handle_ask_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.", reply_markup=create_menu())

def process_question(message):
    try:
        chat_id = message.chat.id
        question = message.text
        logger.info(f"Обработка вопроса от {chat_id}: {question}")
        
        bot.send_chat_action(chat_id, 'typing')
        search_results = google_search(question)
        
        if not search_results:
            bot.send_message(chat_id, "❌ По вашему запросу ничего не найдено. Попробуйте переформулировать вопрос.", reply_markup=create_menu())
            return
        
        response_text = "🔍 Вот что я нашел:\n\n"
        for i, res in enumerate(search_results, 1):
            response_text += f"<b>{i}. {res['title']}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            response_text += f"<a href='{res['url']}'>🔗 Источник</a>\n\n"
        
        # Сохраняем в историю
        save_history(chat_id, question, response_text)
        
        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=create_menu()
        )
        logger.info("Ответ отправлен")
    except Exception as e:
        logger.error(f"Ошибка в process_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())

@bot.message_handler(func=lambda message: message.text == 'История')
def handle_history(message):
    try:
        chat_id = message.chat.id
        logger.info(f"Обработка 'История' от {chat_id}")
        
        if chat_id not in user_history or not user_history[chat_id]:
            bot.send_message(chat_id, "История запросов пуста.", reply_markup=create_menu())
            return
        
        history = user_history[chat_id]
        response = "📚 Ваша история запросов:\n\n"
        
        for i, item in enumerate(reversed(history), 1):
            response += f"<b>{i}. Вопрос:</b> {item['question']}\n"
            # Показываем первый результат из ответа
            first_result = item['response'].split('\n\n')[0] if '\n\n' in item['response'] else item['response'][:100]
            response += f"<b>Ответ:</b> {first_result}...\n"
            response += "─" * 20 + "\n\n"
        
        bot.send_message(
            chat_id,
            response,
            parse_mode='HTML',
            reply_markup=create_menu()
        )
        logger.info("История отправлена")
    except Exception as e:
        logger.error(f"Ошибка в handle_history: {str(e)}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка при получении истории.", reply_markup=create_menu())

@app.route('/')
def home():
    return "🤖 Telegram Search Bot активен! Используйте /start в Telegram"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            json_data = request.get_json()
            logger.info("Получен webhook-запрос")
            
            # Проверяем, что это действительное обновление
            if 'message' in json_data or 'edited_message' in json_data:
                update = telebot.types.Update.de_json(json_data)
                bot.process_new_updates([update])
                return '', 200
            else:
                logger.warning("Получен невалидный webhook-запрос")
                return 'Invalid update', 400
        return 'Bad request', 400
    except Exception as e:
        logger.error(f"Ошибка в webhook: {str(e)}")
        return 'Server error', 500

def configure_webhook():
    """Настраивает вебхук при запуске приложения"""
    try:
        # Для Render.com
        if os.environ.get('RENDER'):
            external_url = os.environ.get('RENDER_EXTERNAL_URL')
            if external_url:
                webhook_url = f"{external_url}/webhook"
                bot.remove_webhook()
                # Даем время для снятия вебхука
                import time; time.sleep(1)
                bot.set_webhook(url=webhook_url)
                logger.info(f"Вебхук установлен: {webhook_url}")
                
                # Логируем информацию о вебхуке
                webhook_info = bot.get_webhook_info()
                logger.info(f"Информация о вебхуке: {webhook_info}")
                return
            else:
                logger.warning("RENDER_EXTERNAL_URL не найден!")
        
        # Для других платформ/локального запуска
        bot.remove_webhook()
        logger.info("Вебхук удален, используется polling")
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {str(e)}")

# Установка вебхука после определения всех обработчиков
configure_webhook()

if __name__ == '__main__':
    # Локальный запуск
    logger.info("Локальный запуск: используется polling")
    bot.remove_webhook()
    bot.infinity_polling()
