import os
import telebot
import requests
import logging
import pytesseract
from PIL import Image
import io
from bs4 import BeautifulSoup
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import threading

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

# Проверка доступности Tesseract
try:
    tesseract_version = pytesseract.get_tesseract_version()
    logger.info(f"Tesseract version: {tesseract_version}")
except Exception as e:
    logger.error(f"Tesseract check failed: {str(e)}")
    raise

# Настройки поиска
SEARCH_URL = "https://www.google.com/search?q={}&hl=ru"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

# Хранение истории (в памяти; для продакшена используйте базу данных)
user_history = {}

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📷 Отправить фото'), KeyboardButton('📚 История'))
    markup.add(KeyboardButton('ℹ️ Помощь'))
    return markup

def google_search(query):
    """Выполняет поиск в Google и возвращает топ-3 результата"""
    try:
        logger.info(f"Поисковый запрос: {query}")
        formatted_query = query.replace(" ", "+")
        response = requests.get(
            SEARCH_URL.format(formatted_query), 
            headers=HEADERS, 
            timeout=15
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # Поиск результатов
        result_blocks = soup.find_all('div', class_='tF2Cxc') or soup.find_all('div', class_='MjjYud') or soup.find_all('div', class_='g')
        
        for block in result_blocks[:3]:  # Берем первые 3 результата
            # Извлечение заголовка
            title_elem = block.find('h3') or block.find('h3', class_='LC20lb') or block.find('div', role='heading')
            title = title_elem.get_text(strip=True) if title_elem else "Без названия"
            
            # Извлечение ссылки
            link_elem = block.find('a', href=True)
            if link_elem:
                link = link_elem['href']
                if link.startswith('/url?q='):
                    link = link[7:].split('&')[0]
            else:
                link = "#"
            
            # Извлечение описания
            snippet_elem = block.find('div', class_='VwiC3b') or block.find('div', class_='yXK7lf') or block.find('span', class_='aCOpRe')
            snippet = snippet_elem.get_text(strip=True)[:300] + "..." if snippet_elem else "Описание отсутствует"
            
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet
            })
        
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

def process_image(image_data):
    """Распознает текст на изображении с помощью OCR"""
    try:
        image = Image.open(io.BytesIO(image_data))
        text = pytesseract.image_to_string(image, lang='rus+eng')
        logger.info(f"Распознано символов: {len(text)}")
        return text.strip()
    except Exception as e:
        logger.error(f"Ошибка OCR: {str(e)}")
        return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        logger.info(f"Обработка команды /start от {message.chat.id}")
        response = (
            "👋 Ахуел?\n\n"
            "Я умею:\n"
            "• Искать ответы на текстовые вопросы\n"
            "• Распознавать текст с фотографий\n"
            "• Помогать с учебными материалами\n\n"
            "Просто отправь мне вопрос или фотографию с заданием!"
        )
        bot.send_message(
            message.chat.id,
            response,
            reply_markup=create_menu()
        )
        logger.info("Приветственное сообщение отправлено")
    except Exception as e:
        logger.error(f"Ошибка в send_welcome: {str(e)}")

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def handle_help(message):
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == '📝 Задать вопрос')
def handle_ask_question(message):
    try:
        logger.info(f"Обработка 'Задать вопрос' от {message.chat.id}")
        msg = bot.send_message(message.chat.id, "📝 Введите ваш вопрос:", reply_markup=None)
        bot.register_next_step_handler(msg, process_text_question)
    except Exception as e:
        logger.error(f"Ошибка в handle_ask_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.", reply_markup=create_menu())

@bot.message_handler(func=lambda message: message.text == '📷 Отправить фото')
def handle_ask_photo(message):
    try:
        logger.info(f"Запрос на отправку фото от {message.chat.id}")
        bot.send_message(message.chat.id, "📸 Отправьте фотографию с заданием:", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка в handle_ask_photo: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.", reply_markup=create_menu())

def process_text_question(message):
    try:
        chat_id = message.chat.id
        question = message.text
        logger.info(f"Обработка текстового вопроса от {chat_id}: {question}")
        
        # Удаляем клавиатуру на время обработки
        bot.send_chat_action(chat_id, 'typing')
        
        # Ищем ответ
        search_results = google_search(question)
        
        if not search_results:
            bot.send_message(chat_id, "❌ По вашему запросу ничего не найдено. Попробуйте переформулировать вопрос.", reply_markup=create_menu())
            return
        
        response_text = "🔍 Вот что я нашел по вашему вопросу:\n\n"
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
        logger.info("Ответ на текстовый вопрос отправлен")
    except Exception as e:
        logger.error(f"Ошибка в process_text_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        chat_id = message.chat.id
        logger.info(f"Получено фото от {chat_id}")
        
        # Получаем фото с наилучшим качеством
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_data = bot.download_file(file_info.file_path)
        
        bot.send_message(chat_id, "🖼️ Обрабатываю изображение...")
        bot.send_chat_action(chat_id, 'typing')
        
        # Распознаем текст
        text = process_image(file_data)
        
        if not text:
            bot.send_message(chat_id, "❌ Не удалось распознать текст на фото. Попробуйте другое изображение.", reply_markup=create_menu())
            return
        
        # Обрезаем длинный текст для отображения
        display_text = text[:300] + "..." if len(text) > 300 else text
        
        bot.send_message(
            chat_id,
            f"📝 Распознанный текст:\n\n<code>{display_text}</code>",
            parse_mode='HTML',
            reply_markup=create_menu()
        )
        
        # Ищем ответ по распознанному тексту
        bot.send_message(chat_id, "🔍 Ищу ответ по распознанному тексту...")
        search_results = google_search(text)
        
        if not search_results:
            bot.send_message(chat_id, "❌ По распознанному тексту ничего не найдено.", reply_markup=create_menu())
            return
        
        response_text = "🔍 Вот что я нашел по вашему заданию:\n\n"
        for i, res in enumerate(search_results, 1):
            response_text += f"<b>{i}. {res['title']}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            response_text += f"<a href='{res['url']}'>🔗 Источник</a>\n\n"
        
        # Сохраняем в историю
        save_history(chat_id, f"Фото: {text[:50]}...", response_text)
        
        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=create_menu()
        )
        logger.info("Ответ по фото отправлен")
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {str(e)}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке изображения.", reply_markup=create_menu())

@bot.message_handler(func=lambda message: message.text == '📚 История')
def handle_history(message):
    try:
        chat_id = message.chat.id
        logger.info(f"Обработка 'История' от {chat_id}")
        
        if chat_id not in user_history or not user_history[chat_id]:
            bot.send_message(chat_id, "📭 История запросов пуста.", reply_markup=create_menu())
            return
        
        history = user_history[chat_id]
        response = "📚 Ваша история запросов:\n\n"
        
        for i, item in enumerate(reversed(history), 1):
            # Обрезаем длинные вопросы
            question = item['question'] if len(item['question']) < 50 else item['question'][:50] + "..."
            
            response += f"<b>{i}. Вопрос:</b> {question}\n"
            # Показываем первый результат из ответа
            first_result = item['response'].split('\n\n')[0] if '\n\n' in item['response'] else item['response'][:100] + "..."
            response += f"<b>Ответ:</b> {first_result}\n"
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
    return "🤖 Telegram Study Bot активен! Используйте /start в Telegram"

@app.route('/health')
def health_check():
    """Endpoint для проверки работоспособности"""
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            json_data = request.get_json()
            logger.info("Получен webhook-запрос")
            
            update = telebot.types.Update.de_json(json_data)
            bot.process_new_updates([update])
            return '', 200
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
                
                # Проверка доступности бота
                try:
                    bot.get_me()
                    logger.info("Бот доступен, устанавливаем вебхук")
                except Exception as e:
                    logger.error(f"Ошибка доступа к боту: {str(e)}")
                    return
                
                # Удаляем существующий вебхук перед установкой нового
                bot.remove_webhook()
                logger.info("Старый вебхук удален")
                
                # Устанавливаем новый вебхук в фоновом потоке
                def set_webhook_background():
                    import time
                    time.sleep(3)  # Короткая задержка
                    try:
                        bot.set_webhook(url=webhook_url)
                        logger.info(f"Вебхук установлен: {webhook_url}")
                        
                        # Проверяем информацию о вебхуке
                        webhook_info = bot.get_webhook_info()
                        logger.info(f"Информация о вебхуке: {webhook_info}")
                    except Exception as e:
                        logger.error(f"Ошибка установки вебхука: {str(e)}")
                
                # Запускаем в отдельном потоке
                thread = threading.Thread(target=set_webhook_background)
                thread.daemon = True
                thread.start()
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
