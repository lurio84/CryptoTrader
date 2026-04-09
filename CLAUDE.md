# CryptoTrader Advisor - Project Context

## Estado actual: COMPLETADO

Repositorio: https://github.com/lurio84/CryptoTrader
Stack: Python 3.12 (NO usar 3.14, incompatible con dependencias), FastAPI, ccxt, pandas, SQLite

## Estrategia de inversion (validada con datos reales 2020-2026)

Total: 140 EUR/mes via Sparplans en Trade Republic (0 fees):
- S&P 500: 16 EUR/semana (64 EUR/mes) - invertido: 253 EUR
- MSCI Global Semiconductors: 4 EUR/semana (16 EUR/mes) - invertido: 46 EUR
- Realty Income: 4 EUR/semana (16 EUR/mes) - invertido: 43 EUR
- Uranium: 1 EUR/semana (4 EUR/mes) - invertido: 10 EUR
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
- Fear & Greed Index: NO funciona como predictor (extreme fear da PEOR retorno que baseline)
- Indicadores tecnicos (SMA/RSI/BB): ninguno supera buy & hold
- NO vender despues de rallies (momentum continua, +10.8% tras +30% rally)

## Decisiones importantes tomadas

- Discord como canal de alertas (primary), Telegram como fallback
- NO usar saveback 2% de TR para pagar con crypto (vender crypto es mala idea segun datos)
- NO usar F&G como senal de compra (validado que no funciona)
- Staking ETH activado (gratis, sin lock-up en TR)
- Dashboard carga instantaneamente (datos via AJAX, auto-refresh 60s)

## Pendiente

- Configurar Discord webhook en .env y como secret en GitHub repo
- Una vez configurado, GitHub Actions enviara alertas cada 4h automaticamente

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
python main.py check --notify         # Check + enviar Discord/Telegram
python main.py dashboard              # Dashboard web
python main.py collect --symbols BTC/USDT ETH/USDT --since 2020-01-01  # Descargar datos
python main.py sentiment --since 2020-01-01  # Descargar sentiment
```

## Convenciones

- Conventional commits (hay hook configurado): feat:, fix:, etc.
- Tests: pytest, 41 tests actualmente
- NO usar caracteres unicode especiales en Python (Windows cp1252)
