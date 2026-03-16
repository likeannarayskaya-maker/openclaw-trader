FROM python:3.13-slim

WORKDIR /app

# Устанавливаем git (нужен для tinkoff-investments)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Копируем и ставим зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Запуск
CMD ["python", "ai_trader_v3.py"]
