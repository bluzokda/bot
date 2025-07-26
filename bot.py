import os
import telebot
import requests
import logging
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import io
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import re
import time
import json

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

if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY не установлен!")
    raise ValueError("OPENROUTER_API_KEY не установлен")

bot = telebot.TeleBot(BOT_TOKEN)
logger.info("Бот инициализирован")

# Проверка доступности Tesseract
try:
    tesseract_version = pytesseract.get_tesseract_version()
    logger.info(f"Tesseract version: {tesseract_version}")
except Exception as e:
    logger.error(f"Tesseract check failed: {str(e)}")
    raise

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

def query_openrouter_api(prompt):
    """Отправляет запрос в OpenRouter API с использованием Qwen 2.5"""
    try:
        logger.info(f"Запрос к OpenRouter API: {prompt[:100]}...")
        
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Используем корректный идентификатор Qwen 2.5
        model_id = "qwen/qwen2.5-72b-chat"
        
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты полезный помощник для студентов и школьников. Отвечай четко, по делу и на русском языке. Если не знаешь точного ответа, скажи об этом."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.2
        }
        
        response = requests.post(url, headers=OPENROUTER_HEADERS, json=payload, timeout=60)
        logger.info(f"OpenRouter API status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            answer = data['choices'][0]['message']['content'].strip()
            logger.info(f"Получен ответ от OpenRouter API: {len(answer)} символов")
            return answer
        else:
            # Детальный анализ ошибки
            try:
                error_data = response.json()
                error_info = error_data.get('error', {})
                error_code = error_info.get('code', 'UNKNOWN')
                error_message = error_info.get('message', 'Без описания')
                
                logger.error(f"OpenRouter API error {response.status_code}: [{error_code}] {error_message}")
                
                # Формируем понятное сообщение об ошибке
                if response.status_code == 400:
                    return f"❌ Ошибка запроса к ИИ: {error_message}"
                elif response.status_code == 401:
                    return "❌ Ошибка авторизации OpenRouter API. Проверьте токен."
                elif response.status_code == 403:
                    return "❌ Доступ к OpenRouter API запрещен. Проверьте токен и ограничения."
                elif response.status_code == 429:
                    return "⏰ Превышен лимит запросов к OpenRouter API. Попробуйте позже."
                else:
                    return f"❌ Ошибка OpenRouter API: {response.status_code} - {error_code}"
            except json.JSONDecodeError:
                logger.error(f"OpenRouter API вернул невалидный JSON: {response.text[:200]}")
                return f"❌ Ошибка OpenRouter API: {response.status_code}"
            
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе к OpenRouter API")
        return "⌛ Таймаут соединения с ИИ-сервисом"
    except requests.exceptions.ConnectionError:
        logger.error("Ошибка подключения к OpenRouter API")
        return "🔌 Ошибка подключения к ИИ-сервису"
    except Exception as e:
        logger.error(f"Ошибка запроса к OpenRouter API: {str(e)}")
        return f"⚠️ Непредвиденная ошибка: {str(e)}"

def check_model_availability():
    """Проверяет доступность модели на OpenRouter"""
    try:
        logger.info("Проверка доступности модели...")
        url = "https://openrouter.ai/api/v1/models"
        response = requests.get(url, headers=OPENROUTER_HEADERS, timeout=15)
        
        if response.status_code == 200:
            models = [m['id'] for m in response.json().get('data', [])]
            target_model = "qwen/qwen2.5-72b-chat"
            
            if target_model in models:
                logger.info(f"✅ Модель {target_model} доступна")
            else:
                available_models = ", ".join(models)
                logger.warning(f"❌ Модель {target_model} недоступна! Доступные модели: {available_models}")
        else:
            logger.error(f"Ошибка получения списка моделей: {response.status_code}")
    except Exception as e:
        logger.error(f"Ошибка проверки моделей: {str(e)}")

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
    """Распознает текст на изображении с оптимизированной обработкой"""
    try:
        image = Image.open(io.BytesIO(image_data))
        
        # Оптимизированная предобработка
        if image.mode != 'L':
            image = image.convert('L')
        
        # Быстрая обработка
        image = ImageOps.autocontrast(image, cutoff=5)
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        image = image.filter(ImageFilter.SHARPEN)
        image = image.point(lambda p: 255 if p > 160 else 0)
        
        # Распознаем текст
        custom_config = r'--oem 3 --psm 6 -l rus+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
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
        status_msg = bot.send_message(chat_id, "🔍 Обрабатываю ваш вопрос с помощью ИИ...")
        
        # Получаем ответ от ИИ через OpenRouter
        ai_answer = query_openrouter_api(question)
        
        # Обновляем статус
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text="✅ Ответ получен!"
        )
        
        # Форматирование ответа
        if "❌" in ai_answer or "⚠️" in ai_answer or "⏰" in ai_answer:
            response_text = f"🤖 <b>Ошибка обработки запроса:</b>\n{ai_answer}"
        else:
            response_text = f"🤖 <b>Ответ от ИИ:</b>\n{ai_answer}\n\n"
            response_text += "<i>Ответ сгенерирован с помощью Qwen 2.5 AI</i>"
        
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
        
        # Распознаем текст
        bot.send_chat_action(chat_id, 'typing')
        start_time = time.time()
        text = process_image(file_data)
        elapsed_time = time.time() - start_time
        logger.info(f"OCR занял {elapsed_time:.2f} секунд")
        
        if not text or len(text) < 5:
            bot.send_message(
                chat_id, 
                "❌ Не удалось распознать текст на фото.\nПопробуйте:\n• Улучшить освещение\n• Сфокусироваться на тексте\n• Сделать фото под прямым углом",
                reply_markup=create_menu()
            )
            return
            
        # Обрезаем длинный текст для отображения
        display_text = text[:300] + "..." if len(text) > 300 else text
        bot.send_message(
            chat_id,
            f"📝 Распознанный текст:\n<code>{display_text}</code>",
            parse_mode='HTML'
        )
        
        # Ищем ответ по распознанному тексту
        processing_msg = bot.send_message(chat_id, "🔍 Обрабатываю распознанный текст с помощью ИИ...")
        ai_answer = query_openrouter_api(text)
        
        # Удаляем сообщение о обработке
        try:
            bot.delete_message(chat_id, processing_msg.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {str(e)}")
        
        # Форматирование ответа
        if "❌" in ai_answer or "⚠️" in ai_answer or "⏰" in ai_answer:
            response_text = f"🤖 <b>Ошибка обработки фото:</b>\n{ai_answer}"
        else:
            response_text = f"🤖 <b>Ответ от ИИ (по распознанному тексту):</b>\n{ai_answer}\n\n"
            response_text += "<i>Ответ сгенерирован с помощью Qwen 2.5 AI</i>"
        
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
            if not external_url:
                logger.error("RENDER_EXTERNAL_URL не установлен!")
                return
                
            webhook_url = f"{external_url}/webhook"
            logger.info(f"Попытка установки вебхука: {webhook_url}")
            
            # Удаляем существующий вебхук
            try:
                bot.remove_webhook()
                logger.info("Старый вебхук удален")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка удаления вебхука: {str(e)}")
            
            # Устанавливаем новый вебхук
            try:
                bot.set_webhook(url=webhook_url)
                logger.info(f"Вебхук установлен: {webhook_url}")
                
                # Проверяем информацию о вебхуке
                webhook_info = bot.get_webhook_info()
                logger.info(f"Информация о вебхуке: {webhook_info.url}")
                
            except Exception as e:
                logger.error(f"Ошибка установки вебхука: {str(e)}")
        else:
            # Для локальной разработки
            bot.remove_webhook()
            logger.info("Вебхук удален, используется polling")
            
        # Проверяем доступность модели
        check_model_availability()
            
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {str(e)}")

# Установка вебхука после определения всех обработчиков
configure_webhook()

# Для Docker - запускаем Flask приложение
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск Flask приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
