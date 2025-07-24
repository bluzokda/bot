import os
import telebot
import requests
import logging
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import io
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import threading
import re
import time
import json
from urllib.parse import quote_plus

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

# Улучшенные заголовки для обхода блокировок
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0"
}

# Хранение истории
user_history = {}

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📷 Отправить фото'), KeyboardButton('📚 История'))
    markup.add(KeyboardButton('ℹ️ Помощь'))
    return markup

def search_brave(query):
    """Поиск через Brave Search (альтернатива DuckDuckGo)"""
    try:
        logger.info(f"Поиск в Brave: {query}")
        encoded_query = quote_plus(query)
        url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count=5&search_lang=ru"
        
        brave_headers = HEADERS.copy()
        brave_headers["X-Subscription-Token"] = "BSAkvgKRhAoFTHCWyQqMqNwN8gkf4QDN"  # Публичный ключ
        
        response = requests.get(url, headers=brave_headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = []
            web_results = data.get("web", {}).get("results", [])
            
            for item in web_results[:5]:
                results.append({
                    "title": item.get("title", "Без названия"),
                    "url": item.get("url", "#"),
                    "snippet": item.get("description", "Описание отсутствует")
                })
            
            if results:
                logger.info(f"Найдено в Brave: {len(results)} результатов")
                return results
        else:
            logger.warning(f"Brave API вернул статус {response.status_code}")
    except Exception as e:
        logger.error(f"Ошибка поиска в Brave: {str(e)}")
    return None

def search_duckduckgo_html(query):
    """Поиск через DuckDuckGo HTML (обход API)"""
    try:
        logger.info(f"Поиск в DuckDuckGo HTML: {query}")
        encoded_query = quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}&kl=ru-ru"
        
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        # Простой парсинг HTML (в идеале использовать BeautifulSoup)
        html_content = response.text
        results = []
        
        # Ищем результаты в HTML
        import re
        # Находим заголовки результатов
        title_matches = re.findall(r'<a[^>]*class="result__a"[^>]*>([^<]*)</a>', html_content)
        url_matches = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"', html_content)
        snippet_matches = re.findall(r'<a[^>]*class="result__snippet"[^>]*>([^<]*)', html_content)
        
        for i in range(min(5, len(title_matches))):
            title = title_matches[i] if i < len(title_matches) else "Без названия"
            url = url_matches[i] if i < len(url_matches) else "#"
            snippet = snippet_matches[i] if i < len(snippet_matches) else "Описание отсутствует"
            
            if title and snippet:
                results.append({
                    "title": title.strip(),
                    "url": url.strip(),
                    "snippet": snippet.strip()
                })
        
        if results:
            logger.info(f"Найдено в DuckDuckGo HTML: {len(results)} результатов")
            return results
            
    except Exception as e:
        logger.error(f"Ошибка поиска в DuckDuckGo HTML: {str(e)}")
    return None

def search_internet(query):
    """Ищет информацию по запросу через несколько источников"""
    try:
        logger.info(f"Поисковый запрос: {query}")
        
        # Пробуем разные источники по очереди
        sources = [
            ("Brave", search_brave),
            ("DuckDuckGo HTML", search_duckduckgo_html)
        ]
        
        for source_name, search_func in sources:
            try:
                logger.info(f"Пробуем источник: {source_name}")
                results = search_func(query)
                if results and len(results) > 0:
                    logger.info(f"Успешно получены результаты от {source_name}")
                    return results
            except Exception as e:
                logger.error(f"Ошибка поиска в {source_name}: {str(e)}")
                continue
        
        logger.warning("Не удалось получить результаты ни от одного источника")
        return None
        
    except Exception as e:
        logger.error(f"Ошибка общего поиска: {str(e)}")
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
    """Распознает текст на изображении с улучшенной предобработкой"""
    try:
        image = Image.open(io.BytesIO(image_data))
        # Конвертация в градации серого
        if image.mode != 'L':
            image = image.convert('L')
        # Автоконтраст
        image = ImageOps.autocontrast(image, cutoff=10)
        # Увеличение контраста
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.5)
        # Увеличение резкости
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(3.0)
        # Легкое размытие для уменьшения шума
        image = image.filter(ImageFilter.GaussianBlur(radius=0.7))
        # Бинаризация (адаптивное пороговое преобразование)
        image = ImageOps.autocontrast(image)
        image = image.point(lambda p: 255 if p > 160 else 0)
        # Масштабирование для мелкого текста
        if min(image.size) < 1000:
            scale_factor = max(2500 / min(image.size), 2.5)
            new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
            image = image.resize(new_size, Image.LANCZOS)
        # Повышение резкости после масштабирования
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(2.0)
        # Распознаем текст с оптимальными параметрами
        custom_config = r'--oem 3 --psm 6 -l rus+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        # Очистка текста
        text = re.sub(r'\s+', ' ', text).strip()
        logger.info(f"Распознано символов: {len(text)}")
        return text
    except Exception as e:
        logger.error(f"Ошибка OCR: {str(e)}")
        return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        logger.info(f"Обработка команды /start от {message.chat.id}")
        response = (
            "👋 Привет! Я твой бот-помощник для учебы!\n"
            "Я умею:\n"
            "• Искать ответы на текстовые вопросы\n"
            "• Распознавать текст с фотографий\n"
            "• Помогать с учебными материалами\n"
            "📌 Советы для лучшего результата:\n"
            "1. Формулируйте вопросы четко (например: 'Что такое фотосинтез?')\n"
            "2. Фотографируйте текст при хорошем освещении\n"
            "3. Держите камеру параллельно тексту\n"
            "4. Убедитесь, что текст занимает большую часть кадра\n"
            "Попробуй отправить мне вопрос или фотографию с заданием!"
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
        msg = bot.send_message(message.chat.id, "📝 Введите ваш вопрос (например: 'Что такое фотосинтез?'):", reply_markup=None)
        bot.register_next_step_handler(msg, process_text_question)
    except Exception as e:
        logger.error(f"Ошибка в handle_ask_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.", reply_markup=create_menu())

@bot.message_handler(func=lambda message: message.text == '📷 Отправить фото')
def handle_ask_photo(message):
    try:
        logger.info(f"Запрос на отправку фото от {message.chat.id}")
        bot.send_message(message.chat.id, "📸 Отправьте фотографию с заданием:\n• Сфокусируйтесь на тексте\n• Обеспечьте хорошее освещение\n• Держите камеру параллельно тексту", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка в handle_ask_photo: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.", reply_markup=create_menu())

def process_text_question(message):
    try:
        chat_id = message.chat.id
        question = message.text
        logger.info(f"Обработка текстового вопроса от {chat_id}: {question}")
        
        if len(question) < 3:
            bot.send_message(chat_id, "❌ Вопрос слишком короткий. Пожалуйста, уточните запрос.", reply_markup=create_menu())
            return
        
        # Удаляем клавиатуру на время обработки
        bot.send_chat_action(chat_id, 'typing')
        
        # Ищем ответ
        search_results = search_internet(question)
        if not search_results:
            bot.send_message(
                chat_id, 
                "❌ По вашему запросу ничего не найдено.\nПопробуйте:\n• Переформулировать вопрос\n• Использовать другие ключевые слова\n• Проверить орфографию",
                reply_markup=create_menu()
            )
            return
        
        response_text = "🔍 Вот что я нашел по вашему вопросу:\n\n"
        for i, res in enumerate(search_results[:3], 1):  # Только топ-3 результата
            # Укорачиваем слишком длинные заголовки
            title = res['title'] if len(res['title']) < 100 else res['title'][:97] + "..."
            response_text += f"<b>{i}. {title}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            if res['url'] != "#":
                response_text += f"<a href='{res['url']}'>🔗 Подробнее</a>\n"
            else:
                response_text += "\n"
        
        # Сохраняем в историю
        save_history(chat_id, question, response_text)
        
        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,  # Отключаем предпросмотр для лучшей стабильности
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
        start_time = time.time()
        text = process_image(file_data)
        elapsed_time = time.time() - start_time
        logger.info(f"OCR занял {elapsed_time:.2f} секунд")
        if not text or len(text) < 10:
            bot.send_message(
                chat_id, 
                "❌ Не удалось распознать текст на фото.\nПопробуйте:\n• Улучшить освещение\n• Сфокусироваться на тексте\n• Сделать фото под прямым углом\n• Отправить более четкое изображение",
                reply_markup=create_menu()
            )
            return
        # Обрезаем длинный текст для отображения
        display_text = text[:300] + "..." if len(text) > 300 else text
        bot.send_message(
            chat_id,
            f"📝 Распознанный текст:\n<code>{display_text}</code>",
            parse_mode='HTML',
            reply_markup=create_menu()
        )
        # Ищем ответ по распознанному тексту
        bot.send_message(chat_id, "🔍 Ищу ответ по распознанному тексту...")
        search_results = search_internet(text)
        if not search_results:
            # Попробуем найти по ключевым словам
            keywords = ' '.join(text.split()[:10])
            search_results = search_internet(keywords)
            if not search_results:
                bot.send_message(chat_id, "❌ По распознанному тексту ничего не найдено.", reply_markup=create_menu())
                return
        
        response_text = "🔍 Вот что я нашел по вашему заданию:\n\n"
        for i, res in enumerate(search_results[:3], 1):  # Только топ-3 результата
            # Укорачиваем слишком длинные заголовки
            title = res['title'] if len(res['title']) < 100 else res['title'][:97] + "..."
            response_text += f"<b>{i}. {title}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            if res['url'] != "#":
                response_text += f"<a href='{res['url']}'>🔗 Подробнее</a>\n"
            else:
                response_text += "\n"
        
        # Сохраняем в историю
        save_history(chat_id, f"Фото: {text[:50]}...", response_text)
        
        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,  # Отключаем предпросмотр для лучшей стабильности
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
            first_result = item['response'].split('\n')[0] if '\n' in item['response'] else item['response'][:100] + "..."
            response += f"<b>Ответ:</b> {first_result}\n"
            response += "─" * 20 + "\n"
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
                    time.sleep(3)
                    try:
                        bot.set_webhook(url=webhook_url)
                        logger.info(f"Вебхук установлен: {webhook_url}")
                        # Проверяем информацию о вебхуке
                        webhook_info = bot.get_webhook_info()
                        logger.info(f"Информация о вебхуке: {webhook_info}")
                    except Exception as e:
                        logger.error(f"Ошибка установки вебхука: {str(e)}")
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
