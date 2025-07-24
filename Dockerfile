FROM python:3.11-slim-bullseye

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
ENV PYTHONUNBUFFERED=1

# Установка рабочей директории
WORKDIR /app

# Копирование зависимостей и установка
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Команда запуска
CMD ["python", "bot.py"]
