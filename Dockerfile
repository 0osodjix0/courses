# Используйте официальный образ Python как базовый
FROM python:3.10-slim

# Установите рабочую директорию
WORKDIR /app

# Скопируйте requirements.txt и установите зависимости
COPY requirements.txt .
RUN pip install -r requirements.txt

# Укажите команду для запуска приложения
CMD ["python", "xcoursestbot.py"]
