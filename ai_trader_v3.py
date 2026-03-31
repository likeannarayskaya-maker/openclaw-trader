"""
🦞 OpenClaw AI Trader v3 — полная картина рынка
=================================================
Claude получает:
1. Цены акций + индикаторы
2. Макро: индекс Мосбиржи, нефть, доллар, ставка ЦБ
3. Свежие новости
4. Состояние портфеля

Запуск:  python ai_trader_v3.py
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ============================================
# ПАМЯТЬ АГЕНТА: история решений
# ============================================
# На Railway файлы не сохраняются между cron-запусками,
# поэтому храним память в файле (для локального запуска)
# и дублируем в переменную окружения OPENCLAW_MEMORY (для Railway)
MEMORY_FILE = Path("memory.json")

def load_memory():
    """Загрузить историю решений."""
    # Сначала пробуем из переменной окружения (Railway)
    env_memory = os.getenv("OPENCLAW_MEMORY", "")
    if env_memory:
        try:
            return json.loads(env_memory)
        except:
            pass
    # Потом из файла (локально)
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"decisions": [], "trades": []}

def save_memory(memory):
    """Сохранить историю решений."""
    memory["decisions"] = memory["decisions"][-20:]
    memory["trades"] = memory["trades"][-50:]
    # Сохраняем в файл (локально)
    try:
        MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
    except:
        pass
    # Обновляем переменную Railway через API (если доступно)
    railway_token = os.getenv("RAILWAY_API_TOKEN", "")
    if railway_token:
        try:
            import urllib.request
            # Просто печатаем — память будет в логах, и можно восстановить
            pass
        except:
            pass
    # Печатаем память в лог чтобы не потерять
    print(f"   💾 MEMORY_STATE: {json.dumps(memory, ensure_ascii=False)[:500]}")

def get_today_trades(memory):
    """Получить тикеры, которые сегодня уже покупались/продавались."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_tickers = set()
    for trade in memory.get("trades", []):
        if trade.get("date", "").startswith(today):
            today_tickers.add(trade["ticker"])
    return today_tickers

def get_memory_summary(memory):
    """Краткое саммари для Claude: последние 5 решений."""
    if not memory.get("decisions"):
        return "Это первый запуск, истории нет."
    
    summary = []
    for d in memory["decisions"][-5:]:
        date = d.get("date", "?")
        analysis = d.get("analysis", "")[:150]
        trades_str = ", ".join([
            f"{t['action']} {t['ticker']}" for t in d.get("trades", [])
        ]) or "HOLD"
        summary.append(f"[{date}] {trades_str}. {analysis}")
    
    return "\n".join(summary)

memory = load_memory()
print(f"📝 Память: {len(memory.get('decisions', []))} решений, {len(memory.get('trades', []))} сделок")

# Определяем режим: sandbox или production
TRADING_MODE = os.getenv("TRADING_MODE", "sandbox")

if TRADING_MODE == "production":
    TOKEN = os.getenv("TINKOFF_TRADE_TOKEN")
    if not TOKEN:
        print("❌ Нет TINKOFF_TRADE_TOKEN в переменных!")
        sys.exit(1)
    print("⚠️  РЕЖИМ: РЕАЛЬНЫЕ ДЕНЬГИ (production)")
else:
    TOKEN = os.getenv("TINKOFF_SANDBOX_TOKEN")
    if not TOKEN or "ВСТАВЬ" in TOKEN:
        print("❌ Вставь sandbox-токен!")
        sys.exit(1)
    print("🧪 РЕЖИМ: Песочница (sandbox)")

ACCOUNT_ID = os.getenv("TINKOFF_ACCOUNT_ID")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

if not ACCOUNT_ID:
    print("❌ Нет TINKOFF_ACCOUNT_ID!")
    sys.exit(1)
if not ANTHROPIC_KEY:
    print("❌ Нет ANTHROPIC_API_KEY!")
    sys.exit(1)

import anthropic
from tinkoff.invest import (
    CandleInterval, OrderDirection, OrderType, InstrumentStatus
)
from tinkoff.invest.utils import quotation_to_decimal

# Выбираем клиент в зависимости от режима
if TRADING_MODE == "production":
    from tinkoff.invest import Client as BrokerClient
else:
    from tinkoff.invest.sandbox.client import SandboxClient as BrokerClient

print("🦞 OpenClaw AI Trader v3.3 (терпеливый и смелый)")
print("=" * 50)

TICKERS = [
    # Нефтегаз
    "GAZP", "LKOH", "ROSN", "NVTK",
    # Банки и финтех
    "SBER", "T", "VTBR",
    # Технологии
    "YDEX", "OZON", "POSI", "VKCO", "ASTR",
    # Ритейл
    "MGNT", "FIVE",
    # Телеком
    "MTSS",
    # Металлы и золото
    "PLZL", "NLMK", "CHMF",
    # Авиа и транспорт
    "AFLT",
]

MAX_TRADE_AMOUNT = 3500  # лимит на одну сделку
MAX_POSITION_PCT = 0.30   # максимум 30% портфеля в одной бумаге

with BrokerClient(TOKEN) as client:

    now = datetime.now(timezone.utc)

    # ========================================
    # ШАГ 1: Макроэкономические данные
    # ========================================
    print("\n🌍 Шаг 1: Макро-данные...")

    macro_data = {}

    # --- Индекс Мосбиржи (IMOEX) ---
    try:
        # Ищем фьючерс или индексный фонд на IMOEX
        # Используем TMOS (фонд на индекс Мосбиржи от Т-Инвестиций)
        all_etfs = client.instruments.etfs(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE
        )
        tmos = None
        for etf in all_etfs.instruments:
            if etf.ticker == "TMOS" and etf.currency == "rub":
                tmos = etf
                break

        if tmos:
            candles = client.market_data.get_candles(
                instrument_id=tmos.uid,
                from_=now - timedelta(days=14),
                to=now,
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            ).candles
            if candles:
                closes = [float(quotation_to_decimal(c.close)) for c in candles]
                change = ((closes[-1] / closes[-5]) - 1) * 100 if len(closes) >= 5 else 0
                macro_data["moex_index_proxy"] = {
                    "instrument": "TMOS (фонд на индекс Мосбиржи)",
                    "price": closes[-1],
                    "change_week_%": round(change, 2),
                    "trend": "растёт" if change > 0 else "падает",
                    "last_5_days": [round(p, 2) for p in closes[-5:]],
                }
                print(f"   📊 Индекс Мосбиржи (TMOS): {closes[-1]:.2f}₽ ({change:+.1f}% за неделю)")
    except Exception as e:
        print(f"   ⚠️  Индекс: {e}")

    # --- Нефть Brent ---
    try:
        all_futures = client.instruments.futures(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE
        )
        brent = None
        for fut in all_futures.instruments:
            if "BR" in fut.ticker and fut.currency == "usd":
                brent = fut
                break

        if brent:
            candles = client.market_data.get_candles(
                instrument_id=brent.uid,
                from_=now - timedelta(days=14),
                to=now,
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            ).candles
            if candles:
                closes = [float(quotation_to_decimal(c.close)) for c in candles]
                change = ((closes[-1] / closes[-5]) - 1) * 100 if len(closes) >= 5 else 0
                macro_data["brent_oil"] = {
                    "instrument": f"Brent ({brent.ticker})",
                    "price_usd": closes[-1],
                    "change_week_%": round(change, 2),
                    "trend": "растёт" if change > 0 else "падает",
                }
                print(f"   🛢️  Нефть Brent: ${closes[-1]:.2f} ({change:+.1f}% за неделю)")
    except Exception as e:
        print(f"   ⚠️  Нефть: {e}")

    # --- Курс USD/RUB ---
    try:
        all_currencies = client.instruments.currencies(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE
        )
        usdrub = None
        for cur in all_currencies.instruments:
            if cur.ticker == "USD000UTSTOM":
                usdrub = cur
                break

        if usdrub:
            candles = client.market_data.get_candles(
                instrument_id=usdrub.uid,
                from_=now - timedelta(days=14),
                to=now,
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            ).candles
            if candles:
                closes = [float(quotation_to_decimal(c.close)) for c in candles]
                change = ((closes[-1] / closes[-5]) - 1) * 100 if len(closes) >= 5 else 0
                macro_data["usd_rub"] = {
                    "rate": closes[-1],
                    "change_week_%": round(change, 2),
                    "trend": "рубль слабеет" if change > 0 else "рубль крепнет",
                }
                print(f"   💵 USD/RUB: {closes[-1]:.2f}₽ ({change:+.1f}% за неделю)")
    except Exception as e:
        print(f"   ⚠️  Доллар: {e}")

    # Ставку ЦБ Claude найдёт через новости (она не в API)
    macro_data["cbr_note"] = "Ключевую ставку ЦБ РФ уточни из новостей"

    # ========================================
    # ШАГ 2: Данные по акциям
    # ========================================
    print("\n📊 Шаг 2: Данные по акциям...")

    all_shares = client.instruments.shares(
        instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE
    )

    stocks = {}
    for share in all_shares.instruments:
        if share.ticker in TICKERS and share.api_trade_available_flag:
            if share.currency == "rub":
                stocks[share.ticker] = share

    market_data = {}
    for ticker, share in stocks.items():
        candles = client.market_data.get_candles(
            instrument_id=share.uid,
            from_=now - timedelta(days=14),
            to=now,
            interval=CandleInterval.CANDLE_INTERVAL_DAY,
        ).candles

        if len(candles) < 3:
            continue

        closes = [float(quotation_to_decimal(c.close)) for c in candles]
        volumes = [c.volume for c in candles]
        last = closes[-1]
        change_week = ((closes[-1] / closes[-5]) - 1) * 100 if len(closes) >= 5 else 0
        avg_5 = sum(closes[-5:]) / min(5, len(closes))
        avg_vol = sum(volumes[-5:]) / min(5, len(volumes)) if volumes else 0
        last_vol = volumes[-1] if volumes else 0

        market_data[ticker] = {
            "name": share.name,
            "price": last,
            "lot_size": share.lot,
            "lot_cost": round(last * share.lot, 2),
            "change_week_%": round(change_week, 2),
            "avg_5_days": round(avg_5, 2),
            "above_avg": last > avg_5,
            "prices_last_5_days": [round(p, 2) for p in closes[-5:]],
            "avg_volume_5d": int(avg_vol),
            "last_volume": last_vol,
            "volume_vs_avg": "повышенный" if last_vol > avg_vol * 1.3 else "нормальный" if last_vol > avg_vol * 0.7 else "пониженный",
        }
        vol_emoji = "🔥" if last_vol > avg_vol * 1.3 else "📊"
        print(f"   {vol_emoji} {ticker}: {last:.2f}₽ ({change_week:+.1f}%) объём: {market_data[ticker]['volume_vs_avg']}")

    # ========================================
    # ШАГ 3: Портфель
    # ========================================
    portfolio = client.operations.get_portfolio(account_id=ACCOUNT_ID)
    total_value = float(quotation_to_decimal(portfolio.total_amount_portfolio))

    positions_info = []
    for pos in portfolio.positions:
        if pos.instrument_type == "share":
            qty = float(quotation_to_decimal(pos.quantity))
            avg_p = float(quotation_to_decimal(pos.average_position_price))
            pnl = float(quotation_to_decimal(pos.expected_yield))
            pnl_pct = (pnl / (avg_p * qty)) * 100 if avg_p * qty > 0 else 0
            tick = pos.figi
            for t, s in stocks.items():
                if s.figi == pos.figi:
                    tick = t
            positions_info.append({
                "ticker": tick,
                "quantity": qty,
                "avg_price": avg_p,
                "pnl_rub": round(pnl, 2),
                "pnl_%": round(pnl_pct, 2),
            })

    pos_data = client.operations.get_positions(account_id=ACCOUNT_ID)
    cash = 0
    for m in pos_data.money:
        if m.currency == "rub":
            cash = m.units + m.nano / 1_000_000_000

    portfolio_summary = {
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "positions": positions_info,
    }

    print(f"\n   💰 Портфель: {total_value:,.2f}₽ (свободно: {cash:,.2f}₽)")
    for p in positions_info:
        emoji = "🟢" if p["pnl_rub"] >= 0 else "🔴"
        print(f"   📦 {p['ticker']}: {p['quantity']:.0f} шт. {emoji} {p['pnl_rub']:+.2f}₽ ({p['pnl_%']:+.1f}%)")


# ============================================
# ШАГ 4: Новости через Claude
# ============================================
print("\n📰 Шаг 4: Ищем новости...")

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

news_response = claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=800,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{"role": "user", "content": """Найди свежие новости за последние 2-3 дня по российскому фондовому рынку.
Кратко (максимум 7 пунктов по 1 предложению): индекс Мосбиржи, нефть, рубль, ставка ЦБ, 
ключевые новости компаний (Газпром, Лукойл, Роснефть, Сбер, МТС, Магнит, НОВАТЭК), геополитика.
Без заголовков и markdown. Просто пронумерованный список. По-русски."""}],
)

news_text = ""
for block in news_response.content:
    if hasattr(block, "text"):
        news_text += block.text

print("   ✅ Новости получены!")

# Обрезаем новости до 1500 символов чтобы не превысить rate limit
news_text = news_text[:1500]

for line in news_text[:600].split("\n"):
    if line.strip():
        print(f"   {line.strip()}")
if len(news_text) > 600:
    print("   ...")

# Ждём 10 секунд чтобы не упереться в rate limit Opus
import time
print("\n   ⏳ Пауза 10 сек (rate limit)...")
time.sleep(10)


# ============================================
# ШАГ 5: Claude принимает решение
# ============================================
print("\n🧠 Шаг 5: Claude принимает решение...")

memory_summary = get_memory_summary(memory)
today_traded = get_today_trades(memory)

decision_prompt = f"""Ты — ИИ-трейдер OpenClaw 🦞. Портфель ~10 000₽, Мосбиржа. Это ЭКСПЕРИМЕНТ для блога — твои решения публикуются подписчикам, поэтому будь интересным!

МАКРО: {json.dumps(macro_data, ensure_ascii=False)}
АКЦИИ: {json.dumps(market_data, ensure_ascii=False)}
ПОРТФЕЛЬ: {json.dumps(portfolio_summary, ensure_ascii=False)}
НОВОСТИ: {news_text}

ТВОИ ПРЕДЫДУЩИЕ РЕШЕНИЯ (помни о них!):
{memory_summary}

ПРАВИЛА:
- Макс {MAX_TRADE_AMOUNT}₽ на сделку, макс 7 позиций, lot_cost<=деньгам, 0-3 сделки за раз
- Макс 30% портфеля в одной бумаге! Не набирай слишком много одной акции
- Продавай при убытке >5% или серьёзных негативных новостях
- ЗАПРЕЩЕНО покупать и продавать одну и ту же бумагу в один день! Если уже торговал {today_traded or 'ничего'} сегодня — не трогай их
- ЗАПРЕЩЕНО продавать то, что купил вчера — дай позиции минимум 2 дня
- Не дёргай позиции туда-сюда! Каждая сделка стоит комиссию ~3-7₽. Покупай с намерением держать минимум 5 дней
- HOLD — это НОРМАЛЬНО! Не обязательно совершать сделку каждый запуск. Если нет сильного сигнала — просто скажи HOLD
- На ПАДАЮЩЕМ рынке (индекс ниже 2850) — предпочитай HOLD. Не лови падающие ножи. Лучше сохранить кэш для покупки на дне
- Не покупай бумагу, которая падает 3+ дня подряд — подожди разворота
- За прошлую неделю мы потеряли ~90₽ на комиссиях из-за частых сделок. МЕНЬШЕ СДЕЛОК = БОЛЬШЕ ПРИБЫЛИ

ХАРАКТЕР:
- Будь СМЕЛЫМ, но ТЕРПЕЛИВЫМ! Хорошая сделка стоит ожидания. Не покупай просто потому что есть деньги
- Не сиди только в Сбере и Газпроме. Ищи растущие истории в технологиях (YDEX, OZON, POSI, VKCO, ASTR), золоте (PLZL), ритейле (FIVE)
- Диверсифицируй по секторам: нефтегаз, IT, банки, ритейл, металлы — не клади всё в один сектор
- Если видишь интересную историю (IPO, новый продукт, сильный отчёт) — действуй!
- Учитывай свои прошлые решения! Не противоречь себе без причины
- Объясняй решения ярко и понятно, как будто пишешь для Telegram-поста
- Если решил HOLD — объясни почему, это тоже интересно для подписчиков

АНАЛИЗ: падающий рынок=осторожнее, падающая нефть=осторожно с нефтянкой,
пониженный объём+рост=слабый тренд, геополитический рост может быть краткосрочным.

Ответь СТРОГО JSON (без markdown, без ```):
{{"macro_view":"1-2 предл","analysis":"3-5 предл","trades":[{{"ticker":"X","action":"BUY/SELL","lots":1,"reason":"причина"}}],"risks":"1-2 предл","next_week_outlook":"1-2 предл","mood":"emoji"}}"""

response = claude.messages.create(
    model="claude-opus-4-6",
    max_tokens=1500,
    messages=[{"role": "user", "content": decision_prompt}],
)

response_text = response.content[0].text

try:
    clean = response_text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]
    decision = json.loads(clean)
except json.JSONDecodeError:
    print(f"\n   ⚠️  Claude ответил не JSON:")
    print(f"   {response_text[:500]}")
    sys.exit(1)

print(f"\n   {decision.get('mood', '🤔')} РЕШЕНИЕ CLAUDE:")
print(f"\n   🌍 Макро: {decision.get('macro_view', '—')}")
print(f"\n   📊 Анализ: {decision['analysis']}")
print(f"\n   ⚠️  Риски: {decision.get('risks', '—')}")
print(f"\n   🔮 Прогноз: {decision.get('next_week_outlook', '—')}")

trades = decision.get("trades", [])

# Сохраняем решение в память (даже если HOLD)
memory["decisions"].append({
    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "analysis": decision.get("analysis", "")[:200],
    "macro_view": decision.get("macro_view", ""),
    "trades": [{"ticker": t["ticker"], "action": t["action"]} for t in trades],
    "mood": decision.get("mood", ""),
})

if not trades:
    save_memory(memory)
    print("\n   💤 Решение: сделок не нужно.")
    print("\n" + "=" * 50)
    print("🦞 Цикл завершён. HOLD.")
    sys.exit(0)

print(f"\n   📋 Сделки ({len(trades)}):")
for t in trades:
    emoji = "🟢 КУПИТЬ" if t["action"] == "BUY" else "🔴 ПРОДАТЬ"
    print(f"   {emoji} {t['ticker']} ({t['lots']} лот) — {t['reason']}")


# ============================================
# ШАГ 6: Исполнение
# ============================================
print("\n⚡ Шаг 6: Исполняем...")

with BrokerClient(TOKEN) as client:
    for trade in trades:
        ticker = trade["ticker"]
        action = trade["action"]
        lots = trade.get("lots", 1)

        if ticker not in stocks:
            print(f"   ⚠️  {ticker} — не найден, пропускаем")
            continue

        # Антидёрг: не торгуем тем, чем уже торговали сегодня
        if ticker in today_traded:
            print(f"   ⚠️  {ticker} — уже торговали сегодня, пропускаем (антидёрг)")
            continue

        stock = stocks[ticker]
        cost = market_data[ticker]["lot_cost"] * lots

        if action == "BUY" and cost > MAX_TRADE_AMOUNT:
            print(f"   ⚠️  {ticker}: {cost:.0f}₽ > лимита {MAX_TRADE_AMOUNT}₽")
            continue
        if action == "BUY" and cost > cash:
            print(f"   ⚠️  {ticker}: не хватает денег")
            continue

        # Проверка концентрации: не больше 30% портфеля в одной бумаге
        if action == "BUY":
            # Считаем текущую стоимость позиции по этому тикеру
            current_position_value = 0
            for p in positions_info:
                if p["ticker"] == ticker:
                    current_position_value = p["quantity"] * market_data[ticker]["price"]
            new_total = current_position_value + cost
            if new_total > total_value * MAX_POSITION_PCT:
                print(f"   ⚠️  {ticker}: позиция будет {new_total:.0f}₽ > {MAX_POSITION_PCT*100:.0f}% портфеля ({total_value * MAX_POSITION_PCT:.0f}₽)")
                continue

        direction = (
            OrderDirection.ORDER_DIRECTION_BUY if action == "BUY"
            else OrderDirection.ORDER_DIRECTION_SELL
        )

        try:
            order = client.orders.post_order(
                instrument_id=stock.uid,
                quantity=lots,
                direction=direction,
                order_type=OrderType.ORDER_TYPE_MARKET,
                account_id=ACCOUNT_ID,
            )
            total = float(quotation_to_decimal(order.total_order_amount))
            e = "🟢" if action == "BUY" else "🔴"
            print(f"   {e} {action} {ticker}: {total:.2f}₽ ✅")
            # Записываем сделку в память
            memory["trades"].append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "ticker": ticker,
                "action": action,
                "lots": lots,
                "amount": total,
            })
            if action == "BUY":
                cash -= total
        except Exception as e:
            print(f"   ❌ {ticker}: {e}")

    # Сохраняем память
    save_memory(memory)
    print(f"\n   📝 Память сохранена ({len(memory['trades'])} сделок)")

    # Итог
    print("\n📈 Итоговый портфель:")
    portfolio = client.operations.get_portfolio(account_id=ACCOUNT_ID)
    total_p = float(quotation_to_decimal(portfolio.total_amount_portfolio))
    print(f"   💰 Стоимость: {total_p:,.2f}₽")

    for pos in portfolio.positions:
        if pos.instrument_type == "share":
            qty = float(quotation_to_decimal(pos.quantity))
            avg_p = float(quotation_to_decimal(pos.average_position_price))
            pnl = float(quotation_to_decimal(pos.expected_yield))
            emoji = "🟢" if pnl >= 0 else "🔴"
            tick = pos.figi
            for t, s in stocks.items():
                if s.figi == pos.figi:
                    tick = t
            print(f"   📦 {tick}: {qty:.0f} шт. × {avg_p:.2f}₽  {emoji} {pnl:+.2f}₽")

    pos_data = client.operations.get_positions(account_id=ACCOUNT_ID)
    for m in pos_data.money:
        if m.currency == "rub":
            c = m.units + m.nano / 1_000_000_000
            print(f"   💵 Свободно: {c:,.2f}₽")

print(f"\n{'=' * 50}")
print("🦞 OpenClaw AI Trader v3 — цикл завершён!")
print("   Макро + акции + новости + объёмы → решение Claude")
