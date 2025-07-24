# Используем официальный образ Python
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

# Рабочая директория
WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .

# Установка Python-зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Команда запуска (используем polling, как в bot.py)
CMD ["python", "bot.py"]
