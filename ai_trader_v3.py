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

from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TINKOFF_SANDBOX_TOKEN")
ACCOUNT_ID = os.getenv("TINKOFF_ACCOUNT_ID")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

if not TOKEN or "ВСТАВЬ" in TOKEN:
    print("❌ Вставь sandbox-токен в .env!")
    sys.exit(1)
if not ACCOUNT_ID:
    print("❌ Нет TINKOFF_ACCOUNT_ID в .env!")
    sys.exit(1)
if not ANTHROPIC_KEY:
    print("❌ Нет ANTHROPIC_API_KEY в .env!")
    sys.exit(1)

import anthropic
from tinkoff.invest import (
    CandleInterval, OrderDirection, OrderType, InstrumentStatus
)
from tinkoff.invest.sandbox.client import SandboxClient
from tinkoff.invest.utils import quotation_to_decimal

print("🦞 OpenClaw AI Trader v3 (полная картина)")
print("=" * 50)

TICKERS = ["GAZP", "LKOH", "ROSN", "MTSS", "MGNT", "SBER", "T", "NVTK"]

with SandboxClient(TOKEN) as client:

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

decision_prompt = f"""Ты — ИИ-трейдер OpenClaw 🦞. Портфель ~10 000₽, Мосбиржа.

МАКРО: {json.dumps(macro_data, ensure_ascii=False)}
АКЦИИ: {json.dumps(market_data, ensure_ascii=False)}
ПОРТФЕЛЬ: {json.dumps(portfolio_summary, ensure_ascii=False)}
НОВОСТИ: {news_text}

ПРАВИЛА: макс 2000₽ на сделку, макс 5 позиций, lot_cost<=деньгам, 0-3 сделки.
Продавай при убытке >3% или негативных новостях.
Учитывай: падающий рынок=не покупать, падающая нефть=осторожно с GAZP/LKOH/ROSN/NVTK,
пониженный объём+рост=слабый тренд, геополитический рост может быть краткосрочным, ставка ЦБ>15%=депозиты конкурируют.

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
if not trades:
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

with SandboxClient(TOKEN) as client:
    for trade in trades:
        ticker = trade["ticker"]
        action = trade["action"]
        lots = trade.get("lots", 1)

        if ticker not in stocks:
            print(f"   ⚠️  {ticker} — не найден, пропускаем")
            continue

        stock = stocks[ticker]
        cost = market_data[ticker]["lot_cost"] * lots

        if action == "BUY" and cost > 2000:
            print(f"   ⚠️  {ticker}: {cost:.0f}₽ > лимита 2000₽")
            continue
        if action == "BUY" and cost > cash:
            print(f"   ⚠️  {ticker}: не хватает денег")
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
            if action == "BUY":
                cash -= total
        except Exception as e:
            print(f"   ❌ {ticker}: {e}")

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
