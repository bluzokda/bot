FROM python:3.12-slim-bullseye

# Установка Tesseract и языков
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Настройка переменных окружения
ENV PYTESSERACT_TESSERACT_CMD=/usr/bin/tesseract
ENV TELEGRAM_BOT_TOKEN="7452800190:AAGGWsVqA92kf6n3BJJ9ODpEyghKA_2T7Do"
ARG HF_TOKEN
ENV HF_APT_TOKEN=$HF_TOKEN

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "gunicorn --workers 1 --timeout 600 --bind 0.0.0.0:$PORT bot:app"]
