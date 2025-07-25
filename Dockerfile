# Используем официальный образ Python
FROM python:3.11-slim-bullseye

# Установка Tesseract и языков
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Настройка переменных окружения
ENV PYTESSERACT_TESSERACT_CMD=/usr/bin/tesseract
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Создаем пользователя приложения
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Рабочая директория
WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .

# Установка Python-зависимостей
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY --chown=appuser:appuser . .

# Переключаемся на непривилегированного пользователя
USER appuser

# Открываем порт
EXPOSE 10000

# Команда запуска
CMD ["python", "bot.py"]
