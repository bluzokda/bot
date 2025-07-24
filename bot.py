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
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY') # Получаем ключ из переменных окружения

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

# Настройки OpenRouter
OPENROUTER_HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "HTTP-Referer": os.environ.get('RENDER_EXTERNAL_URL', 'https://your-bot-url.onrender.com'), # Замени на свой URL если нужно
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

# --- ФУНКЦИИ ПОИСКА (оставляем как есть, они работают как резерв) ---
def search_brave(query):
    """Поиск через Brave Search API (основной метод)"""
    # ... (оставь код search_brave как есть) ...
    pass # Заглушка, замени на реальный код

def search_searx(query):
    """Запасной поиск через Searx (если Brave не работает)"""
    # ... (оставь код search_searx как есть) ...
    pass # Заглушка, замени на реальный код

# --- НОВАЯ ФУНКЦИЯ ПОИСКА С ИИ ---
def search_internet_with_ai(query):
    """Ищет информацию и использует ИИ для генерации ответа"""
    try:
        logger.info(f"Обработка запроса с ИИ: {query}")

        # 1. Попробуем получить информацию из интернета (резервные источники)
        search_results = None
        logger.info("Пробуем получить информацию из интернета...")
        # Пробуем Brave Search (основной)
        if 'search_brave' in globals():
             results = search_brave(query)
             if results and len(results) > 0:
                 search_results = results
                 logger.info("Успешно получены результаты от Brave Search")
        # Если Brave не сработал, пробуем Searx (резерв)
        if not search_results and 'search_searx' in globals():
             results = search_searx(query)
             if results and len(results) > 0:
                 search_results = results
                 logger.info("Успешно получены результаты от Searx")

        # 2. Подготовим контекст для ИИ
        context_text = ""
        if search_results:
             context_text = "\n\n".join([f"Источник: {res['title']}\n{res['snippet']}" for res in search_results[:3]])
             logger.info(f"Контекст для ИИ подготовлен ({len(context_text)} символов)")
        else:
             logger.warning("Информация из интернета не найдена, отправляем запрос без контекста")
             context_text = "Информация по запросу не найдена в интернете."

        # 3. Отправим запрос в OpenRouter
        if not OPENROUTER_API_KEY:
             logger.error("OPENROUTER_API_KEY не установлен!")
             # Если ключа нет, возвращаем результаты поиска напрямую или сообщение об ошибке
             if search_results:
                 return search_results
             else:
                 return [{"title": "Ошибка ИИ", "url": "#", "snippet": "Ключ OpenRouter не установлен. Не удалось получить ответ от ИИ."}]

        logger.info("Отправка запроса в OpenRouter...")

        payload = {
            "model": "openai/gpt-3.5-turbo", # Можешь выбрать другую модель, например, "mistralai/mistral-7b-instruct"
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты полезный помощник для студентов и школьников. "
                        "Твоя задача - отвечать на вопросы, используя предоставленный контекст. "
                        "Отвечай четко, по делу и на русском языке. "
                        "Если контекст не содержит нужной информации, скажи об этом."
                    )
                },
                {
                    "role": "user",
                    "content": f"Контекст:\n{context_text}\n\nВопрос: {query}"
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=OPENROUTER_HEADERS,
                json=payload,
                timeout=30 # Увеличенный таймаут для ИИ
            )
            response.raise_for_status() # Проверка на HTTP ошибки

            data = response.json()
            ai_answer = data['choices'][0]['message']['content'].strip()

            logger.info(f"Ответ от OpenRouter получен ({len(ai_answer)} символов)")

            # Создаем результат, имитирующий формат поиска
            ai_result = {
                "title": "🤖 Ответ от ИИ (на основе найденной информации)",
                "url": "#",
                "snippet": ai_answer
            }

            # Добавляем исходные результаты поиска, если они были
            final_results = [ai_result]
            if search_results:
                final_results.extend(search_results[:2]) # Добавляем максимум 2 исходных результата

            return final_results

        except requests.exceptions.Timeout:
            logger.error("Таймаут при запросе к OpenRouter")
            error_result = {"title": "Ошибка ИИ", "url": "#", "snippet": "Таймаут: Запрос к ИИ занял слишком много времени. Попробуйте позже или переформулируйте вопрос."}
            # Возвращаем ошибку ИИ + исходные результаты поиска, если есть
            return [error_result] + (search_results[:3] if search_results else [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при запросе к OpenRouter: {e}")
            error_result = {"title": "Ошибка ИИ", "url": "#", "snippet": f"Ошибка сети: {str(e)}. Попробуйте позже."}
            return [error_result] + (search_results[:3] if search_results else [])
        except KeyError as e:
            logger.error(f"Ошибка парсинга ответа от OpenRouter: {e}. Ответ: {data}")
            error_result = {"title": "Ошибка ИИ", "url": "#", "snippet": "Ошибка обработки ответа от ИИ. Попробуйте позже."}
            return [error_result] + (search_results[:3] if search_results else [])
        except Exception as e:
            logger.exception("Неожиданная ошибка при запросе к OpenRouter")
            error_result = {"title": "Ошибка ИИ", "url": "#", "snippet": f"Неизвестная ошибка: {str(e)}. Попробуйте позже."}
            return [error_result] + (search_results[:3] if search_results else [])

    except Exception as e:
        logger.exception("Ошибка в search_internet_with_ai")
        # В случае критической ошибки в самой функции, пытаемся вернуть хотя бы результаты поиска
        if 'search_results' in locals() and search_results:
            search_results.insert(0, {"title": "Ошибка ИИ", "url": "#", "snippet": f"Не удалось обработать запрос ИИ: {str(e)}. Показаны результаты поиска."})
            return search_results
        else:
            return [{"title": "Ошибка", "url": "#", "snippet": f"Произошла ошибка: {str(e)}"}]


# --- ФУНКЦИИ ОБРАБОТКИ ИЗОБРАЖЕНИЙ И СООБЩЕНИЙ (обновляем вызов search_internet) ---
def save_history(user_id, question, response):
    """Сохраняет историю запросов пользователя"""
    # ... (оставь как есть) ...

def process_image(image_data):
    """Распознает текст на изображении с улучшенной предобработкой"""
    # ... (оставь как есть) ...

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    # ... (оставь как есть) ...

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def handle_help(message):
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == '📝 Задать вопрос')
def handle_ask_question(message):
    # ... (оставь как есть) ...

@bot.message_handler(func=lambda message: message.text == '📷 Отправить фото')
def handle_ask_photo(message):
    # ... (оставь как есть) ...

def process_text_question(message):
    """Обработчик текстовых вопросов с использованием ИИ"""
    try:
        chat_id = message.chat.id
        question = message.text
        logger.info(f"Обработка текстового вопроса от {chat_id}: {question}")

        if len(question) < 3:
            bot.send_message(chat_id, "❌ Вопрос слишком короткий. Пожалуйста, уточните запрос.", reply_markup=create_menu())
            return

        # Удаляем клавиатуру на время обработки
        bot.send_chat_action(chat_id, 'typing')

        # Ищем ответ с помощью ИИ
        search_results = search_internet_with_ai(question)

        if not search_results or (len(search_results) == 1 and search_results[0]['title'] in ["Поиск не удался", "Ошибка"]):
            bot.send_message(
                chat_id,
                "❌ Не удалось обработать ваш запрос. Попробуйте переформулировать вопрос.",
                reply_markup=create_menu()
            )
            return

        response_text = "🔍 Результаты поиска:\n\n"
        for i, res in enumerate(search_results[:3], 1):  # Только топ-3 результата
            # Укорачиваем слишком длинные заголовки
            title = res['title'] if len(res['title']) < 100 else res['title'][:97] + "..."
            response_text += f"<b>{i}. {title}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            if res['url'] != "#" and res['url']:
                response_text += f"<a href='{res['url']}'>🔗 Подробнее</a>\n"
            else:
                response_text += "\n"

        # Сохраняем в историю
        save_history(chat_id, question, response_text)

        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,  # Отключаем для стабильности
            reply_markup=create_menu()
        )
        logger.info("Ответ на текстовый вопрос отправлен")

    except Exception as e:
        logger.error(f"Ошибка в process_text_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())


def process_photo_question(chat_id, text):
    """Обработчик текста, распознанного с фото, с использованием ИИ"""
    try:
        logger.info(f"Обработка текста с фото от {chat_id}: {text[:50]}...")

        if len(text) < 10:
            bot.send_message(chat_id, "❌ Распознанный текст слишком короткий для поиска.", reply_markup=create_menu())
            return

        # Удаляем клавиатуру на время обработки
        bot.send_chat_action(chat_id, 'typing')

        # Ищем ответ с помощью ИИ, используя распознанный текст как запрос
        search_results = search_internet_with_ai(text)

        if not search_results or (len(search_results) == 1 and search_results[0]['title'] in ["Поиск не удался", "Ошибка"]):
             bot.send_message(
                 chat_id,
                 "❌ Не удалось обработать запрос по распознанному тексту. Попробуйте другое изображение или задайте вопрос вручную.",
                 reply_markup=create_menu()
             )
             return

        response_text = "🔍 Результаты по распознанному тексту:\n\n"
        for i, res in enumerate(search_results[:3], 1):  # Только топ-3 результата
            # Укорачиваем слишком длинные заголовки
            title = res['title'] if len(res['title']) < 100 else res['title'][:97] + "..."
            response_text += f"<b>{i}. {title}</b>\n"
            response_text += f"<i>{res['snippet']}</i>\n"
            if res['url'] != "#" and res['url']:
                response_text += f"<a href='{res['url']}'>🔗 Подробнее</a>\n"
            else:
                response_text += "\n"

        # Сохраняем в историю
        save_history(chat_id, f"Фото: {text[:50]}...", response_text)

        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            disable_web_page_preview=True,  # Отключаем для стабильности
            reply_markup=create_menu()
        )
        logger.info("Ответ по фото отправлен")

    except Exception as e:
        logger.error(f"Ошибка в process_photo_question: {str(e)}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке запроса по фото.", reply_markup=create_menu())


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
     """Обработчик фото: распознает текст и передает его в ИИ"""
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
         # Ищем ответ по распознанному тексту с помощью ИИ
         bot.send_message(chat_id, "🔍 Обрабатываю распознанный текст с помощью ИИ...")
         process_photo_question(chat_id, text) # Вызываем новую функцию

     except Exception as e:
         logger.error(f"Ошибка обработки фото: {str(e)}")
         bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке изображения.", reply_markup=create_menu())


@bot.message_handler(func=lambda message: message.text == '📚 История')
def handle_history(message):
    # ... (оставь как есть) ...

@app.route('/')
def home():
    return "🤖 Telegram Study Bot активен! Используйте /start в Telegram"

@app.route('/health')
def health_check():
    """Endpoint для проверки работоспособности"""
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    # ... (оставь как есть) ...

def configure_webhook():
    # ... (оставь как есть) ...

# Установка вебхука после определения всех обработчиков
configure_webhook()

# Для Docker - запускаем Flask приложение
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск Flask приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
