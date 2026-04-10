# CryptoTrader Advisor - Project Context

## Estado actual: COMPLETADO Y EN PRODUCCION

Repositorio: https://github.com/lurio84/CryptoTrader
Stack: Python 3.12 (NO usar 3.14, incompatible con dependencias), FastAPI, pandas, SQLite

## Estrategia de inversion (validada con datos reales 2020-2026)

Total: 140 EUR/mes via Sparplans en Trade Republic (0 fees):
- S&P 500: 16 EUR/semana (64 EUR/mes)
- MSCI Global Semiconductors: 4 EUR/semana (16 EUR/mes)
- Realty Income: 4 EUR/semana (16 EUR/mes)
- Uranium: 1 EUR/semana (4 EUR/mes)
- BTC: 8 EUR/semana (32 EUR/mes) - Sparplan
- ETH: 2 EUR/semana (8 EUR/mes) - Sparplan + staking activado

Alertas de compra extra manual (1 EUR fee en TR, 2-5 veces/ano):
- BTC crash >15% en 24h -> compra extra 100-150 EUR BTC
- BTC funding rate < -0.01% -> compra extra 100 EUR BTC
- ETH MVRV < 0.8 -> compra extra 100 EUR ETH

## Hallazgos clave del research

- DCA en BTC: +16.5% anualizado | DCA en ETH: +14.2% anualizado
- Crash buying: +9.3% rebote a 7d, 77% win rate (BTC)
- Funding negativo: +23% a 30d, 88% win rate (mejor senal)
- ETH MVRV < 0.8: +34% a 30d, 89% win rate
- ETH MVRV 0.8-1.0: zona amarilla, buenos resultados historicos a 30d
- Fear & Greed Index: NO funciona como predictor (extreme fear da PEOR retorno que baseline)
- Indicadores tecnicos (SMA/RSI/BB): ninguno supera buy & hold
- NO vender despues de rallies (momentum continua, +10.8% tras +30% rally)

## Decisiones importantes tomadas

- Discord unico canal de alertas (Telegram eliminado)
- Precios via CoinGecko (Binance bloquea IPs de GitHub)
- Funding rate via OKX API (Binance y Bybit bloquean IPs de GitHub)
- ETH MVRV via CoinMetrics community API
- DB de alertas cacheada en GitHub Actions (deduplicacion funciona entre runs)
- NO usar saveback 2% de TR para pagar con crypto (vender crypto es mala idea segun datos)
- NO usar F&G como senal de compra (validado que no funciona)
- Staking ETH activado (gratis, sin lock-up en TR)

## Sistema en produccion

GitHub Actions ejecuta check cada 4h automaticamente (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
Secret DISCORD_WEBHOOK_URL configurado en el repo de GitHub.
No requiere ordenador encendido.

## Setup desde cero

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[all]"
.venv/Scripts/python main.py check       # Quick check
.venv/Scripts/python main.py dashboard   # Web dashboard localhost:8000
```

## Comandos utiles

```bash
python main.py check                  # Check rapido de senales
python main.py check --notify         # Check + enviar Discord si hay alerta
python main.py dashboard              # Dashboard web
python main.py collect --symbols BTC/USDT ETH/USDT --since 2020-01-01
python main.py sentiment --since 2020-01-01
```

## Fuentes de datos (todas publicas, sin API key)

- Precios BTC/ETH: CoinGecko API
- Funding rate BTC: OKX API (Binance y Bybit bloquean IPs de GitHub)
- ETH MVRV: CoinMetrics community API
- Fear & Greed: alternative.me API

## Convenciones

- Conventional commits (hay hook configurado): feat:, fix:, etc.
- Tests: pytest, 41 tests actualmente
- NO usar caracteres unicode especiales en Python (Windows cp1252)
