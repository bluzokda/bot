import os
import telebot
import requests
import logging
import pytesseract
from PIL import Image, ImageEnhance, ImageOps
import io
from flask import Flask, request
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import threading
import re
import time
import math
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

bot = telebot.TeleBot(BOT_TOKEN)
logger.info("Бот инициализирован")

# Проверка доступности Tesseract
try:
    tesseract_version = pytesseract.get_tesseract_version()
    logger.info(f"Tesseract version: {tesseract_version}")
except Exception as e:
    logger.error(f"Tesseract check failed: {str(e)}")
    raise

# Хранение истории
user_history = {}
image_executor = ThreadPoolExecutor(max_workers=2)

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📷 Отправить фото'), KeyboardButton('📚 История'))
    markup.add(KeyboardButton('ℹ️ Помощь'))
    return markup

def ask_deepseek(prompt, is_image=False):
    """Запрашивает ответ у DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        return None
        
    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "Ты полезный учебный помощник. Отвечай точно и информативно. Форматируй ответы с использованием HTML."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        # Для изображений используем другую модель
        if is_image:
            payload["model"] = "deepseek-vision"
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        response.raise_for_status()
        data = response.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
            
    except Exception as e:
        logger.error(f"DeepSeek API error: {str(e)}")
    
    return None

def process_image(image_data):
    """Оптимизированное распознавание текста на изображении"""
    try:
        image = Image.open(io.BytesIO(image_data))
        image = image.copy()
        
        # Конвертация в градации серого
        if image.mode != 'L':
            image = image.convert('L')
        
        # Умеренное улучшение контраста
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.8)
        
        # Масштабирование только для мелких изображений
        if min(image.size) < 500:
            scale_factor = max(1000 / min(image.size), 1.8)
            new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
            image = image.resize(new_size, Image.LANCZOS)
        
        # Распознаем текст с оптимизированными параметрами
        custom_config = r'--oem 1 --psm 6 -l rus+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text).strip()
        
        logger.info(f"Распознано символов: {len(text)}")
        return text if len(text) > 5 else None
    except Exception as e:
        logger.error(f"Ошибка OCR: {str(e)}")
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
                user_history[chat_id] = []
            user_history[chat_id].append({
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
                "⚠️ Не удалось получить ответ. Попробуйте еще раз.",
                reply_markup=create_menu()
            )
            
    except Exception as e:
        logger.error(f"Ошибка в process_text_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())

def process_image_async(file_data):
    """Асинхронная обработка изображения"""
    try:
        start_time = time.time()
        text = process_image(file_data)
        elapsed_time = time.time() - start_time
        logger.info(f"OCR занял {elapsed_time:.2f} секунд")
        return text
    except Exception as e:
        logger.error(f"Ошибка в process_image_async: {str(e)}")
        return None

def handle_photo_result(future, message):
    """Обработка результата распознавания"""
    try:
        chat_id = message.chat.id
        text = future.result()
        
        if not text:
            bot.send_message(
                chat_id, 
                "❌ Не удалось распознать текст на фото. Попробуйте другое изображение.",
                reply_markup=create_menu()
            )
            return
        
        # Отправляем запрос в DeepSeek с распознанным текстом
        bot.send_message(chat_id, "🤖 Анализирую содержание...")
        prompt = f"Пользователь отправил фотографию с текстом. Проанализируй содержание и дай развернутый ответ:\n\n{text}"
        ai_response = ask_deepseek(prompt, is_image=True)
        
        if ai_response:
            # Форматируем ответ
            formatted_response = (
                f"<b>📸 Анализ изображения:</b>\n\n"
                f"<b>Распознанный текст:</b>\n<code>{text[:500]}{'...' if len(text) > 500 else ''}</code>\n\n"
                f"<b>🤖 Ответ от DeepSeek:</b>\n{ai_response}"
            )
            
            # Сохраняем в историю
            if chat_id not in user_history:
                user_history[chat_id] = []
            user_history[chat_id].append({
                "question": f"Фото: {text[:50]}...",
                "response": formatted_response
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
        
        bot.send_message(chat_id, "🖼️ Обрабатываю изображение...")
        
        # Отправляем в отдельный поток
        future = image_executor.submit(process_image_async, file_data)
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
            
            response += f"<b>{i}. Вопрос:</b> {question}\n"
            response += "─" * 20 + "\n\n"
        
        bot.send_message(
            chat_id,
            response,
            parse_mode='HTML',
            reply_markup=create_menu()
        )
        
        # Отправляем последний ответ отдельно для удобства
        last_item = history[-1]
        bot.send_message(
            chat_id,
            f"<b>Последний ответ:</b>\n\n{last_item['response']}",
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
                        logger.info(f"Информация о вебхуке: {webhook_info}")
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
