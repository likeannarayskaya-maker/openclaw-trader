"""Узнать ID реального брокерского счёта."""
import os
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TINKOFF_TRADE_TOKEN")
if not TOKEN:
    print("❌ Добавь TINKOFF_TRADE_TOKEN в .env!")
    exit(1)

from tinkoff.invest import Client

with Client(TOKEN) as client:
    accounts = client.users.get_accounts()
    print("Твои брокерские счета:\n")
    for acc in accounts.accounts:
        print(f"  ID: {acc.id}")
        print(f"  Тип: {acc.type}")
        print(f"  Статус: {acc.status}")
        print(f"  Открыт: {acc.opened_date}")
        print()
    print("Скопируй ID нужного счёта и добавь в .env:")
    print("TINKOFF_ACCOUNT_ID=сюда_id")
