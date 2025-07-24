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
HF_API_TOKEN = os.environ.get('HF_API_TOKEN')  # Ключ для Hugging Face

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен!")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

if not HF_API_TOKEN:
    logger.warning("HF_API_TOKEN не установлен! Будет использоваться только OCR")

# Настройка Tesseract
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

# Модели Hugging Face
TEXT_MODEL = "IlyaGusev/rugpt3medium_sum_gazeta"  # Русскоязычная модель
IMAGE_MODEL = "Salesforce/blip-image-captioning-base"
HF_API_URL = "https://api-inference.huggingface.co/models"

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📷 Отправить фото'), KeyboardButton('📚 История'))
    markup.add(KeyboardButton('ℹ️ Помощь'))
    return markup

def compress_image(image_data, max_size=1024*1024):
    """Оптимизированное сжатие изображений"""
    try:
        img = Image.open(io.BytesIO(image_data))
        original_size = len(image_data)
        
        # Ресайз больших изображений
        if max(img.size) > 1600:
            ratio = 1600 / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        
        # Конвертация в JPEG
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Постепенное снижение качества
        quality = 85
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG", quality=quality, optimize=True)
        compressed_data = output_buffer.getvalue()
        
        # Логирование степени сжатия
        compression_ratio = original_size / len(compressed_data) if compressed_data else 1
        logger.info(f"Изображение сжато: {original_size/1024:.1f}KB → {len(compressed_data)/1024:.1f}KB (ratio: {compression_ratio:.1f}x)")
        
        return compressed_data
        
    except Exception as e:
        logger.error(f"Ошибка сжатия изображения: {str(e)}")
        return image_data

def ask_hf(prompt, image_data=None):
    """Запрашивает ответ у Hugging Face API"""
    if not HF_API_TOKEN:
        return None
        
    try:
        # Кэширование запросов
        cache_str = prompt
        if image_data:
            cache_str += hashlib.md5(image_data).hexdigest()[:16]
        cache_key = hashlib.md5(cache_str.encode('utf-8')).hexdigest()
        
        if cache_key in question_cache:
            logger.info("Используется кэшированный ответ")
            return question_cache[cache_key]
        
        headers = {
            "Authorization": f"Bearer {HF_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Обработка изображений
        if image_data:
            # Используем модель описания изображений
            model = IMAGE_MODEL
            response = requests.post(
                f"{HF_API_URL}/{model}",
                headers=headers,
                data=image_data,
                timeout=60
            )
            
            if response.status_code == 200:
                caption = response.json()[0]['generated_text']
                logger.info(f"Сгенерировано описание изображения: {caption}")
                
                # Формируем новый промпт с описанием изображения
                prompt = f"{prompt} Описание изображения: {caption}"
            else:
                logger.error(f"Ошибка HF Vision API: {response.status_code} - {response.text}")
                return None
        
        # Текстовый запрос
        model = TEXT_MODEL
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 512,
                "temperature": 0.7,
                "repetition_penalty": 1.2
            }
        }
        
        response = requests.post(
            f"{HF_API_URL}/{model}",
            headers=headers,
            json=payload,
            timeout=120
        )
        
        # Обработка ответа
        if response.status_code == 200:
            result = response.json()[0]['generated_text']
            
            # Убираем повторение промпта в ответе
            if prompt in result:
                result = result.replace(prompt, "").strip()
            
            # Сохраняем в кэш
            question_cache[cache_key] = result
            return result
        else:
            error_msg = f"Ошибка HF API: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return f"⚠️ Ошибка ИИ: {response.text[:100]}" if response.text else "⚠️ Ошибка ИИ"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к HF API: {str(e)}")
    except Exception as e:
        logger.error(f"Общая ошибка в ask_hf: {str(e)}")
    
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
            "📌 Просто задай вопрос или отправь фото с заданием!\n\n"
            "ℹ️ Используемые технологии: Hugging Face, Tesseract OCR"
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
        
        # Запрос к Hugging Face
        ai_response = ask_hf(question)
        
        if ai_response:
            # Форматируем ответ
            formatted_response = f"<b>🤖 Ответ ИИ:</b>\n\n{ai_response}"
            
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
            logger.info("Ответ от ИИ отправлен")
        else:
            bot.send_message(
                chat_id,
                "⚠️ Не удалось получить ответ. Проверьте настройки API или попробуйте позже.",
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
        
        # Запрос к Hugging Face Vision
        prompt = "Пользователь отправил фотографию с учебным заданием. Проанализируй изображение и дай развернутый ответ."
        ai_response = ask_hf(prompt, image_data=file_data)
        
        if ai_response:
            # Форматируем ответ
            formatted_response = (
                f"<b>📸 Анализ изображения:</b>\n\n"
                f"{ai_response}"
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
                        bot.set_webhook(
                            url=webhook_url,
                            max_connections=50,
                            allowed_updates=["message", "callback_query"]
                        )
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
