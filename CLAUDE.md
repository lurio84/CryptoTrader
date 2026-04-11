# CryptoTrader Advisor - Project Context

## Estado: COMPLETADO Y EN PRODUCCION

Repo: https://github.com/lurio84/CryptoTrader
Stack: Python 3.12 (NO usar 3.14, incompatible con dependencias), FastAPI, pandas, SQLite

## Estrategia Sparplan (Trade Republic, 0 fees)

140 EUR/mes total:
- S&P 500: 16 EUR/semana (64/mes) | MSCI Semiconductors: 4 EUR/sem (16/mes)
- Realty Income: 4 EUR/sem (16/mes) | Uranium: 1 EUR/sem (4/mes)
- BTC: 8 EUR/semana (32/mes) | ETH: 2 EUR/semana (8/mes) + staking activado

`SPARPLAN_TARGETS` en `cli/constants.py`: BTC 22.86%, ETH 5.71%, SP500 45.71%, SEMIS 11.43%, REALTY 11.43%, URANIUM 2.86%

## Alertas activas en produccion

| Alert type (DB)  | Condicion                        | Accion               | Severidad | Dedup |
|------------------|----------------------------------|----------------------|-----------|-------|
| btc_crash        | BTC cae >15% en 24h             | Compra 100-150 EUR   | red       | 6h    |
| funding_negative | Funding rate < -0.01%            | Compra 100 EUR BTC   | orange    | 24h   |
| mvrv_critical    | ETH MVRV < 0.8                  | Compra 100 EUR ETH   | red       | 7d    |
| mvrv_low         | ETH MVRV 0.8-1.0                | Aumentar Sparplan ETH| yellow    | 7d    |
| sp500_crash      | S&P500 cae >5% en 5 dias (Stooq)| Compra extra BTC+ETF | orange    | 7d    |
| btc_dca_out_Xk   | BTC >= $80k (+$20k steps)       | Vender 3% BTC en TR  | orange    | 30d   |
| eth_dca_out_Xk   | ETH >= $3k (+$1k steps)         | Vender 3% ETH en TR  | orange    | 30d   |

## Decisiones arquitectura activas

- Precios: CoinGecko (USD+EUR en una llamada). Funding: OKX. MVRV: CoinMetrics community.
- S&P500: Stooq.com (CSV publico, sin API key, funciona en GitHub Actions). NO usar yfinance en alerts/CI.
- Fear & Greed: NO usar como senal (validado que no funciona)
- MVRV alto (BTC o ETH): NO es senal de venta (momentum continua en ciclos modernos)
- BTC MVRV < 1.0: NO es senal de compra (backtest: delta=-17.2pp, OOS WR=0%). Solo informativo en digest.
- DCA-out activo: alertas Discord ya implementadas
- Rebalanceo: manual 1x/ano cuando BTC o ETH deriva >10pp del target
- yfinance: SOLO LOCAL (portfolio/rebalance/retirement-plan). NUNCA en alerts/ ni CI.
- Ver `RESEARCH.md` para todos los hallazgos del research y senales descartadas

## Sistema en produccion

GitHub Actions: check cada 4h (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
Digest semanal: domingos 09:00 UTC. Secret DISCORD_WEBHOOK_URL en el repo.

## Setup

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[all]"
.venv/Scripts/python main.py check
```

## Comandos utiles

```bash
python main.py check [--notify]        # Check senales (BTC/ETH/MVRV/funding/halving)
python main.py digest [--notify]       # Digest semanal Discord (cooldown 6d)
python main.py dashboard               # Web dashboard localhost:8000

# Rebalanceo anual (BTC/ETH en unidades, ETFs en EUR)
python main.py rebalance --btc 0.05 --eth 0.5 --sp500 5000 --semis 1200 --realty 1200 --uranium 300

# Portfolio tracker (SOLO LOCAL, nunca en CI)
python main.py portfolio add-buy  --asset BTC --units 0.001 --price-eur 45000 --source sparplan
python main.py portfolio add-buy  --asset SP500 --units 1.5 --price-eur 480 --source sparplan
python main.py portfolio add-sell --asset BTC --units 0.0003 --price-eur 87000 --source dca_out
python main.py portfolio show / history / export

# Monte Carlo jubilacion
python main.py retirement-plan [--age 35 --retire-age 60 --target-eur 800000]

# Research (scripts standalone, requieren internet)
python research/sp500_crash_research.py
python research/full_plan_simulation_2020.py

python main.py collect --symbols BTC/USDT ETH/USDT --since 2020-01-01
```

## Fuentes de datos (todas publicas, sin API key)

- Precios BTC/ETH: CoinGecko API (USD + EUR + 24h_change en una sola llamada)
- Funding rate: OKX API (Binance y Bybit bloquean IPs de GitHub)
- ETH MVRV + BTC MVRV: CoinMetrics community API
- S&P500 5d change: Stooq.com (`fetch_sp500_change()` en `data/market_data.py`). Sin API key, CI-safe.
- Precios ETF (LOCAL): yfinance (SPY, SOXX, O, URA + EURUSD=X). NUNCA en alerts/ ni CI.

## Convenciones

- Conventional commits (hook configurado): feat:, fix:, docs:, etc.
- Tests: pytest, 65 tests actualmente
- NO usar caracteres unicode especiales en Python (Windows cp1252)
- SQLAlchemy: convertir a dicts dentro del `with get_session()` antes de usar fuera del bloque.
  Patron de referencia: `_row_to_dict` en `cmd_portfolio` de `main.py`.
- Migraciones DB: `PRAGMA table_info` + `ALTER TABLE` en `init_db()`.
  Referencia: `data/database.py:_migrate_user_trade()` (idempotente).
- yfinance: import lazy (dentro de funciones) para que CI funcione sin ella.

## Estructura relevante

```
alerts/discord_bot.py     -- Logica alertas + Discord webhooks + digest semanal
data/market_data.py       -- Capa centralizada de APIs externas (CoinGecko, OKX, CoinMetrics)
data/portfolio.py         -- Logica FIFO e IRPF (solo crypto)
data/etf_prices.py        -- Precios ETF en EUR via yfinance (local-only)
analysis/monte_carlo.py   -- Proyeccion jubilacion Monte Carlo
dashboard/app.py          -- FastAPI + dashboard web
main.py                   -- CLI entry point (14 comandos)
research/                 -- Scripts standalone de research (excluidos de contexto Claude)
```

## Protocolo de cierre de sesion

Al terminar cualquier tarea con cambios de codigo, research o decisiones:
1. Actualizar `CLAUDE.md` si cambian convenciones, comandos o arquitectura activa
2. Actualizar `RESEARCH.md` si hay nuevos hallazgos de research
3. Actualizar memoria del proyecto en `.claude/projects/.../memory/project_overview.md`
4. Commit (conventional) + push
