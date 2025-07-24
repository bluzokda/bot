import os
import telebot
import requests
import logging
from flask import Flask, request
import threading
import time
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен!")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

bot = telebot.TeleBot(BOT_TOKEN)
logger.info("Бот инициализирован")

# Хранение истории
user_history = {}

def create_menu():
    """Создает клавиатуру с основными кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton('📝 Задать вопрос'))
    markup.add(KeyboardButton('📚 История'))
    return markup

def query_deepseek_api(prompt):
    """Отправляет запрос в DeepSeek API"""
    try:
        url = "https://chat.deepseek.com/api/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY')}"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error(f"Ошибка запроса к DeepSeek API: {e}")
        return None

def save_history(user_id, question, response):
    """Сохраняет историю запросов пользователя"""
    if user_id not in user_history:
        user_history[user_id] = []
    # Ограничиваем историю 5 последними запросами
    if len(user_history[user_id]) >= 5:
        user_history[user_id].pop(0)
    user_history[user_id].append({
        "question": question,
        "response": response
    })

@bot.message_handler(commands=['start'])
def send_welcome(message):
    response = (
        "👋 Привет! Я твой ИИ-помощник.\n"
        "Я умею отвечать на любые вопросы с помощью искусственного интеллекта.\n\n"
        "Нажми '📝 Задать вопрос' или просто отправь мне сообщение!"
    )
    bot.send_message(message.chat.id, response, reply_markup=create_menu())

@bot.message_handler(func=lambda message: message.text == '📝 Задать вопрос')
def handle_ask_question(message):
    msg = bot.send_message(message.chat.id, "📝 Введите ваш вопрос:", reply_markup=None)
    bot.register_next_step_handler(msg, process_text_question)

def process_text_question(message):
    try:
        chat_id = message.chat.id
        question = message.text
        logger.info(f"Обработка текстового вопроса от {chat_id}: {question}")

        if len(question) < 3:
            bot.send_message(chat_id, "❌ Вопрос слишком короткий. Пожалуйста, уточните запрос.", reply_markup=create_menu())
            return

        # Уведомляем пользователя, что бот думает
        bot.send_chat_action(chat_id, 'typing')
        status_msg = bot.send_message(chat_id, "⏳ Думаю...")

        # Получаем ответ от DeepSeek
        answer = query_deepseek_api(question)
        
        # Обновляем сообщение со статусом
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"✅ Ответ получен!"
        )
        
        # Формируем и отправляем ответ
        response_text = f"<b>Вопрос:</b> {question}\n\n<b>Ответ:</b> {answer or 'Извините, не удалось получить ответ от ИИ.'}"
        bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode='HTML',
            reply_markup=create_menu()
        )
        
        # Сохраняем в историю
        save_history(chat_id, question, answer)
        logger.info("Ответ на текстовый вопрос отправлен")

    except Exception as e:
        logger.error(f"Ошибка в process_text_question: {str(e)}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке запроса.", reply_markup=create_menu())

@app.route('/')
def home():
    return "🤖 Telegram AI Bot активен! Используйте /start в Telegram"

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
        logger.error(f"Ошибка в webhook: {e}")
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
                    logger.error(f"Ошибка доступа к боту: {e}")
                    return
                bot.remove_webhook()
                logger.info("Старый вебхук удален")
                
                def set_webhook_background():
                    time.sleep(3)
                    try:
                        bot.set_webhook(url=webhook_url)
                        logger.info(f"Вебхук установлен: {webhook_url}")
                        webhook_info = bot.get_webhook_info()
                        logger.info(f"Информация о вебхуке: {webhook_info}")
                    except Exception as e:
                        logger.error(f"Ошибка установки вебхука: {e}")
                
                thread = threading.Thread(target=set_webhook_background)
                thread.daemon = True
                thread.start()
                return
            else:
                logger.warning("RENDER_EXTERNAL_URL не найден!")
        bot.remove_webhook()
        logger.info("Вебхук удален, используется polling")
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {e}")

# Установка вебхука
configure_webhook()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск Flask приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
