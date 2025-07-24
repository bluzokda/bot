import os
import telebot
import requests
import logging
import pytesseract
from PIL import Image, ImageEnhance
import io
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import threading
import time
import base64
import hashlib
from collections import deque
import json
from concurrent.futures import ThreadPoolExecutor

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен!")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY не установлен! Будет использоваться только поиск")

# Настройка Tesseract (если требуется)
if os.environ.get('PYTESSERACT_TESSERACT_CMD'):
    pytesseract.pytesseract.tesseract_cmd = os.environ['PYTESSERACT_TESSERACT_CMD']

bot = telebot.TeleBot(BOT_TOKEN)
logger.info("Бот инициализирован")

# Проверка доступности Tesseract
try:
    tesseract_version = pytesseract.get_tesseract_version()
    logger.info(f"Tesseract version: {tesseract_version}")
except Exception as e:
    logger.error(f"Tesseract check failed: {str(e)}")

# Хранение истории и кэша
user_history = {}
question_cache = {}
image_executor = ThreadPoolExecutor(max_workers=2)
MAX_HISTORY_ITEMS = 10

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📷 Отправить фото'), KeyboardButton('📚 История'))
    markup.add(KeyboardButton('ℹ️ Помощь'))
    return markup

def compress_image(image_data, max_size=1.5*1024*1024):
    """Сжимает изображение до приемлемого размера для API"""
    if len(image_data) <= max_size:
        return image_data
        
    try:
        img = Image.open(io.BytesIO(image_data))
        quality = 85
        while len(image_data) > max_size and quality > 20:
            buffer = io.BytesIO()
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img = img.convert('RGB')
            img.save(buffer, format="JPEG", quality=quality)
            image_data = buffer.getvalue()
            quality -= 15
        return image_data
    except Exception as e:
        logger.error(f"Ошибка сжатия изображения: {str(e)}")
        return image_data

def ask_deepseek(prompt, image_data=None):
    """Запрашивает ответ у DeepSeek API с поддержкой изображений"""
    if not DEEPSEEK_API_KEY:
        return None
        
    try:
        # Кэширование запросов
        cache_str = prompt
        if image_data:
            # Для изображений используем первые 100 байт для хэша
            cache_str += image_data[:100].hex()
        cache_key = hashlib.md5(cache_str.encode('utf-8')).hexdigest()
        
        if cache_key in question_cache:
            logger.info("Используется кэшированный ответ")
            return question_cache[cache_key]
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = [
            {
                "role": "system",
                "content": "Ты полезный учебный помощник. Отвечай точно и информативно. Форматируй ответы с использованием HTML."
            }
        ]
        
        # Формируем запрос с изображением
        if image_data:
            # Сжимаем изображение перед отправкой
            compressed_image = compress_image(image_data)
            base64_image = base64.b64encode(compressed_image).decode('utf-8')
            
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
            messages.append({"role": "user", "content": user_content})
            model = "deepseek-vision"
        else:
            messages.append({"role": "user", "content": prompt})
            model = "deepseek-chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120
        )
        
        # Проверка статус кода
        if response.status_code == 402:
            logger.error("Ошибка 402: Требуется оплата или лимит исчерпан")
            return None
            
        response.raise_for_status()
        data = response.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            result = data["choices"][0]["message"]["content"]
            # Сохраняем в кэш
            question_cache[cache_key] = result
            return result
            
    except requests.exceptions.RequestException as e:
        error_detail = e.response.text if hasattr(e, 'response') and e.response else str(e)
        logger.error(f"DeepSeek API error: {e} | Response: {error_detail}")
    except Exception as e:
        logger.error(f"General error in ask_deepseek: {str(e)}")
    
    return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        logger.info(f"Обработка команды /start от {message.chat.id}")
        response = (
            "👋 Привет! Я твой умный бот-помощник для учебы!\n\n"
            "Я использую продвинутый ИИ для ответов на вопросы. Могу помочь с:\n"
            "• Текстовыми вопросами по любой теме\n"
            "• Распознаванием и анализом фотографий\n"
            "• Поиском учебных материалов\n\n"
            "📌 Просто задай вопрос или отправь фото с заданием!"
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
        
        if len(question) < 3:
            bot.send_message(chat_id, "❌ Вопрос слишком короткий. Пожалуйста, уточните запрос.", reply_markup=create_menu())
            return
            
        bot.send_chat_action(chat_id, 'typing')
        
        # Запрос к DeepSeek
        ai_response = ask_deepseek(question)
        
        if ai_response:
            # Форматируем ответ
            formatted_response = f"<b>🤖 Ответ от DeepSeek:</b>\n\n{ai_response}"
            
            # Сохраняем в историю
            if chat_id not in user_history:
                user_history[chat_id] = deque(maxlen=MAX_HISTORY_ITEMS)
            user_history[chat_id].append({
                "type": "text",
                "question": question,
                "response": formatted_response
            })
            
            # Отправляем ответ
            bot.send_message(
                chat_id,
                formatted_response,
                parse_mode='HTML',
                reply_markup=create_menu()
            )
            logger.info("Ответ от DeepSeek отправлен")
        else:
            bot.send_message(
                chat_id,
                "⚠️ Не удалось получить ответ. Проверьте баланс API ключа или попробуйте позже.",
                reply_markup=create_menu()
            )
            
    except Exception as e:
        logger.error(f"Ошибка в process_text_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())

def handle_photo_result(future, message):
    """Обработка результата анализа изображения"""
    try:
        chat_id = message.chat.id
        result = future.result()
        if not result:
            bot.send_message(chat_id, "⚠️ Ошибка обработки изображения", reply_markup=create_menu())
            return
            
        file_data, original_file_size, compressed_size = result
        
        logger.info(f"Обработка фото: оригинал {original_file_size/1024:.1f}KB → сжато {compressed_size/1024:.1f}KB")
        bot.send_message(chat_id, "🤖 Анализирую изображение...")
        
        # Запрос к DeepSeek Vision
        prompt = "Пользователь отправил фотографию с учебным заданием. Проанализируй изображение и дай развернутый ответ."
        ai_response = ask_deepseek(prompt, image_data=file_data)
        
        if ai_response:
            # Форматируем ответ
            formatted_response = (
                f"<b>📸 Анализ изображения:</b>\n\n"
                f"<b>🤖 Ответ от DeepSeek Vision:</b>\n{ai_response}"
            )
            
            # Сохраняем в историю
            if chat_id not in user_history:
                user_history[chat_id] = deque(maxlen=MAX_HISTORY_ITEMS)
            user_history[chat_id].append({
                "type": "image",
                "question": "Фото с заданием",
                "response": formatted_response,
                "file_size": f"{compressed_size/1024:.1f}KB"
            })
            
            # Отправляем ответ
            bot.send_message(
                chat_id,
                formatted_response,
                parse_mode='HTML',
                reply_markup=create_menu()
            )
        else:
            bot.send_message(
                chat_id,
                "⚠️ Не удалось проанализировать изображение. Попробуйте еще раз.",
                reply_markup=create_menu()
            )
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото результата: {str(e)}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке изображения.", reply_markup=create_menu())

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        chat_id = message.chat.id
        logger.info(f"Получено фото от {chat_id}")
        
        # Получаем фото с наилучшим качеством
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_data = bot.download_file(file_info.file_path)
        original_size = len(file_data)
        
        bot.send_message(chat_id, "🖼️ Обрабатываю изображение...")
        
        # Отправляем в отдельный поток для сжатия
        future = image_executor.submit(
            lambda data: (compress_image(data), original_size, len(compress_image(data))),
            file_data
        )
        future.add_done_callback(lambda f: handle_photo_result(f, message))
        
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
            item_type = "📷" if item['type'] == "image" else "📝"
            
            response += f"{item_type} <b>{i}. {question}</b>\n"
            if item['type'] == "image":
                response += f"   └ Размер: {item.get('file_size', 'N/A')}\n"
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
        if os.environ.get('RENDER'):
            external_url = os.environ.get('RENDER_EXTERNAL_URL')
            if external_url:
                webhook_url = f"{external_url}/webhook"
                
                try:
                    bot.get_me()
                    logger.info("Бот доступен, устанавливаем вебхук")
                except Exception as e:
                    logger.error(f"Ошибка доступа к боту: {str(e)}")
                    return
                
                bot.remove_webhook()
                logger.info("Старый вебхук удален")
                
                def set_webhook_background():
                    import time
                    time.sleep(3)
                    try:
                        bot.set_webhook(url=webhook_url)
                        logger.info(f"Вебхук установлен: {webhook_url}")
                        webhook_info = bot.get_webhook_info()
                        logger.info(f"Информация о вебхуке: {json.dumps(webhook_info.__dict__, indent=2)}")
                    except Exception as e:
                        logger.error(f"Ошибка установки вебхука: {str(e)}")
                
                thread = threading.Thread(target=set_webhook_background)
                thread.daemon = True
                thread.start()
                return
            else:
                logger.warning("RENDER_EXTERNAL_URL не найден!")
        
        bot.remove_webhook()
        logger.info("Вебхук удален, используется polling")
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {str(e)}")

# Установка вебхука после определения всех обработчиков
configure_webhook()

if __name__ == '__main__':
    logger.info("Локальный запуск: используется polling")
    bot.remove_webhook()
    bot.infinity_polling()
