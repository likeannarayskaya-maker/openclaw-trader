FROM python:3.13-slim

WORKDIR /app

# Устанавливаем git (нужен для tinkoff-investments)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Ставим tinkoff-investments отдельно с --no-deps (у них сломана зависимость)
RUN pip install --no-cache-dir --no-deps git+https://github.com/Tinkoff/invest-python.git

# Ставим остальные зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Запуск
CMD ["python", "ai_trader_v3.py"]
