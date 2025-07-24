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
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

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

# OpenRouter API настройки
OPENROUTER_HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "HTTP-Referer": os.environ.get('RENDER_EXTERNAL_URL', 'https://your-bot.onrender.com'),
    "X-Title": "StudyBot",
    "Content-Type": "application/json"
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

def search_wikipedia(query):
    """Поиск через Wikipedia API (резервный метод)"""
    try:
        logger.info(f"Поиск в Wikipedia (резерв): {query}")
        # Сначала ищем статьи
        search_url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        logger.info(f"Wikipedia status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            results = []
            
            title = data.get("title", "Без названия")
            snippet = data.get("extract", "Описание отсутствует")
            url = data.get("content_urls", {}).get("desktop", {}).get("page", "#")
            
            if title and snippet:
                results.append({
                    "title": title[:150],
                    "url": url,
                    "snippet": snippet[:300]
                })
                logger.info(f"Найдено в Wikipedia: 1 результат")
                return results
        elif response.status_code == 404:
            # Если точное совпадение не найдено, пробуем поиск
            search_url = f"https://ru.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'search',
                'srsearch': query,
                'srlimit': 3
            }
            
            search_response = requests.get(search_url, params=params, headers=HEADERS, timeout=15)
            if search_response.status_code == 200:
                search_data = search_response.json()
                results = []
                search_results = search_data.get("query", {}).get("search", [])
                
                for item in search_results:
                    title = item.get("title", "Без названия")
                    snippet = item.get("snippet", "Описание отсутствует")
                    # Очищаем HTML теги из сниппета
                    snippet = re.sub(r'<.*?>', '', snippet)
                    url = f"https://ru.wikipedia.org/wiki/{quote_plus(title)}"
                    
                    if title and snippet:
                        results.append({
                            "title": title[:150],
                            "url": url,
                            "snippet": snippet[:300]
                        })
                
                if results:
                    logger.info(f"Найдено в Wikipedia поиске: {len(results)} результатов")
                    return results
        else:
            logger.warning(f"Wikipedia вернул статус {response.status_code}")
    except Exception as e:
        logger.error(f"Ошибка поиска в Wikipedia: {str(e)}")
    return None

def get_ai_answer(question, context="", use_internet_context=True):
    """Получает ответ от ИИ через OpenRouter"""
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY не установлен")
        return None, "❌ Ключ OpenRouter не установлен. Не удалось получить ответ от ИИ."

    try:
        logger.info(f"Запрос к OpenRouter: {question}")
        
        # Формируем сообщения для чат-модели
        system_message = (
            "Ты помощник по учебе. Отвечай четко и по делу на русском языке. "
        )
        
        if use_internet_context and context:
            system_message += (
                "Тебе предоставлен контекст из интернета. Используй его для ответа. "
                "Если контекст не содержит нужной информации, скажи об этом и дай лучший ответ на основе своих знаний. "
                "Если ты используешь контекст, укажи об этом. "
                "Отвечай кратко и по существу."
            )
            user_message = f"Контекст:\n{context}\n\nВопрос: {question}"
        else:
            system_message += "Ответь на основе своих знаний."
            user_message = question

        messages = [
            {
                "role": "system",
                "content": system_message
            },
            {
                "role": "user",
                "content": user_message
            }
        ]

        payload = {
            "model": "openai/gpt-3.5-turbo",  # Можно изменить на другую модель
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 800  # Увеличен лимит для более полных ответов
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=OPENROUTER_HEADERS,
            json=payload,
            timeout=45  # Увеличенный таймаут для ИИ
        )

        logger.info(f"OpenRouter status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            answer = data['choices'][0]['message']['content'].strip()
            logger.info(f"Получен ответ от OpenRouter: {len(answer)} символов")
            return answer, None
        elif response.status_code == 429:
            error_msg = "⏰ Превышен лимит запросов к ИИ. Попробуйте позже."
            logger.warning("OpenRouter вернул 429 - Rate Limit")
            return None, error_msg
        elif response.status_code == 502:
            error_msg = "🔌 Ошибка подключения к сервису ИИ. Попробуйте позже."
            logger.warning("OpenRouter вернул 502 - Bad Gateway")
            return None, error_msg
        else:
            error_msg = f"❌ Ошибка API ИИ: {response.status_code}"
            logger.error(f"OpenRouter вернул статус {response.status_code}: {response.text}")
            return None, error_msg

    except requests.exceptions.Timeout:
        error_msg = "⌛ Таймаут соединения с ИИ. Попробуйте позже."
        logger.error("Таймаут при запросе к OpenRouter")
        return None, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "🔌 Ошибка подключения к сервису ИИ."
        logger.error("Ошибка соединения с OpenRouter")
        return None, error_msg
    except Exception as e:
        error_msg = f"⚠️ Ошибка ИИ: {str(e)}"
        logger.error(f"Ошибка запроса к OpenRouter: {str(e)}")
        return None, error_msg

def search_internet(query):
    """Ищет информацию по запросу через несколько источников"""
    try:
        logger.info(f"Поисковый запрос: {query}")
        
        # Пробуем Wikipedia (часто стабильный источник)
        logger.info("Пробуем Wikipedia...")
        results = search_wikipedia(query)
        if results and len(results) > 0:
            logger.info("Успешно получены результаты от Wikipedia")
            return results
            
        logger.warning("Не удалось получить результаты ни от одного источника")
        return [
            {
                "title": "Поиск не удался",
                "url": "#",
                "snippet": "К сожалению, не удалось найти информацию по вашему запросу."
            }
        ]
    except Exception as e:
        logger.error(f"Ошибка общего поиска: {str(e)}")
        return [
            {
                "title": "Ошибка поиска",
                "url": "#",
                "snippet": "Произошла ошибка при поиске информации."
            }
        ]

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
        # Бинаризация
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
            "• Искать ответы на текстовые вопросы (с ИИ!)\n"
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
        
        # 1. Сначала пытаемся получить ответ от ИИ без контекста
        ai_answer, error_msg = get_ai_answer(question, use_internet_context=False)
        
        if ai_answer:
            # Отлично, ИИ дал ответ! Отправляем его.
            response_text = f"🤖 <b>Ответ от ИИ:</b>\n{ai_answer}"
            logger.info("Ответ от ИИ (без контекста) получен успешно")
        else:
            # Если ИИ не дал ответ или была ошибка, сообщаем об этом и пытаемся найти информацию
            logger.info(f"ИИ не дал ответ: {error_msg or 'Нет ответа'}. Пробуем поиск в интернете.")
            
            # 2. Ищем информацию в интернете как резерв
            search_results = search_internet(question)
            
            if search_results and search_results[0]['title'] != "Поиск не удался":
                # Получаем контекст из результатов поиска
                context = "\n\n".join([f"{res['title']}: {res['snippet']}" for res in search_results[:2]])
                
                # 3. Пытаемся получить ответ от ИИ с контекстом
                ai_answer_with_context, _ = get_ai_answer(question, context, use_internet_context=True)
                
                if ai_answer_with_context:
                    # ИИ дал ответ с контекстом
                    response_text = f"🤖 <b>Ответ от ИИ (на основе найденной информации):</b>\n{ai_answer_with_context}\n\n"
                    # Добавляем источник
                    best_result = search_results[0]
                    response_text += f"<b>Источник:</b> {best_result['title']}\n"
                    if best_result['url'] != "#" and best_result['url']:
                        response_text += f"<a href='{best_result['url']}'>🔗 Подробнее</a>"
                else:
                    # Если ИИ не смог обработать даже с контекстом, показываем результаты поиска
                    response_text = "🔍 <b>Найденная информация:</b>\n"
                    best_result = search_results[0]
                    response_text += f"<i>{best_result['snippet']}</i>\n\n"
                    response_text += f"<b>Источник:</b> {best_result['title']}\n"
                    if best_result['url'] != "#" and best_result['url']:
                        response_text += f"<a href='{best_result['url']}'>🔗 Подробнее</a>"
            else:
                # Поиск не дал результатов, показываем ошибку ИИ или сообщение о неудаче
                if error_msg:
                    response_text = error_msg + "\n\n"
                    response_text += "ℹ️ Также не удалось найти информацию в интернете."
                else:
                    response_text = "❌ Не удалось обработать ваш запрос и найти информацию."

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
        bot.send_message(chat_id, "🔍 Обрабатываю распознанный текст...")
        
        # 1. Сначала пытаемся получить ответ от ИИ по распознанному тексту
        ai_answer, error_msg = get_ai_answer(text, use_internet_context=False)
        
        if ai_answer:
            # Отлично, ИИ дал ответ по тексту!
            response_text = f"🤖 <b>Ответ от ИИ (по распознанному тексту):</b>\n{ai_answer}"
            logger.info("Ответ от ИИ (по фото) получен успешно")
        else:
            # Если ИИ не дал ответ или была ошибка, сообщаем об этом
            logger.info(f"ИИ не дал ответ по фото: {error_msg or 'Нет ответа'}.")
            
            # 2. Ищем информацию в интернете как резерв
            search_results = search_internet(text)
            
            if search_results and search_results[0]['title'] != "Поиск не удался":
                # Получаем контекст из результатов поиска
                context = "\n\n".join([f"{res['title']}: {res['snippet']}" for res in search_results[:2]])
                
                # 3. Пытаемся получить ответ от ИИ с контекстом
                ai_answer_with_context, _ = get_ai_answer("Объясни содержание следующего текста: " + text[:200] + "...", context, use_internet_context=True)
                
                if ai_answer_with_context:
                    # ИИ дал ответ с контекстом
                    response_text = f"🤖 <b>Ответ от ИИ (на основе найденной информации по тексту):</b>\n{ai_answer_with_context}\n\n"
                    # Добавляем источник
                    best_result = search_results[0]
                    response_text += f"<b>Источник:</b> {best_result['title']}\n"
                    if best_result['url'] != "#" and best_result['url']:
                        response_text += f"<a href='{best_result['url']}'>🔗 Подробнее</a>"
                else:
                    # Если ИИ не смог обработать даже с контекстом, показываем результаты поиска
                    response_text = "🔍 <b>Найденная информация по тексту:</b>\n"
                    best_result = search_results[0]
                    response_text += f"<i>{best_result['snippet']}</i>\n\n"
                    response_text += f"<b>Источник:</b> {best_result['title']}\n"
                    if best_result['url'] != "#" and best_result['url']:
                        response_text += f"<a href='{best_result['url']}'>🔗 Подробнее</a>"
            else:
                # Поиск не дал результатов, показываем ошибку ИИ или сообщение о неудаче
                if error_msg:
                    response_text = error_msg + "\n\n"
                    response_text += "ℹ️ Также не удалось найти информацию по распознанному тексту."
                else:
                    response_text = "❌ Не удалось обработать распознанный текст и найти информацию."

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

# Для Docker - запускаем Flask приложение
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск Flask приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
