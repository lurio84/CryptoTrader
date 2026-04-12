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

| Alert type (DB)        | Condicion                                  | Accion               | Severidad | Dedup |
|------------------------|--------------------------------------------|----------------------|-----------|-------|
| btc_crash              | BTC cae >15% en 24h                       | Compra 100-150 EUR   | red       | 6h    |
| funding_negative       | Funding rate < -0.01%                      | Compra 100 EUR BTC   | orange    | 24h   |
| mvrv_critical          | ETH MVRV < 0.8                            | Compra 100 EUR ETH   | red       | 7d    |
| mvrv_low               | ETH MVRV 0.8-1.0                          | Aumentar Sparplan ETH| yellow    | 7d    |
| sp500_crash            | S&P500 cae >7% en 5 dias (Stooq)          | Compra extra BTC+ETF | orange    | 7d    |
| btc_dca_out_Xk         | BTC >= $80k (+$20k steps)                 | Vender 3% BTC en TR  | orange    | 30d   |
| eth_dca_out_Xk         | ETH >= $3k (+$1k steps)                   | Vender 3% ETH en TR  | orange    | 30d   |
| dead_canary            | Sin heartbeat en >10h (check caido)       | Verificar GH Actions | red       | 6h    |
| rebalance_drift_ASSET  | Drift >10pp vs target (cmd drift-check)   | Rebalancear cartera  | orange    | 7d    |
| tax_headroom_low       | Margen IRPF < threshold (cmd local)       | Revisar antes DCA-out| yellow    | 7d    |
| heartbeat              | Registro tecnico al final de cada check   | (no Discord)         | green     | -     |

## Decisiones arquitectura activas

- Precios: CoinGecko (USD+EUR en una llamada). Funding: OKX. MVRV: CoinMetrics community.
- S&P500: Stooq.com (CSV publico, sin API key, funciona en GitHub Actions). NO usar yfinance en alerts/CI.
- Fear & Greed: NO usar como senal (validado que no funciona)
- MVRV alto (BTC o ETH): NO es senal de venta (momentum continua en ciclos modernos)
- BTC MVRV < 1.0: NO es senal de compra (backtest: delta=-17.2pp, OOS WR=0%). Solo informativo en digest.
- DCA-out activo: alertas Discord ya implementadas
- Rebalanceo: manual 1x/ano cuando BTC o ETH deriva >10pp del target. `drift-check` avisa automaticamente.
- Dead canary: heartbeat logueado en alert_log al final de cada check. Si gap >10h -> alerta red a Discord.
- yfinance: SOLO LOCAL (portfolio/rebalance/retirement-plan/drift-check). NUNCA en alerts/ ni CI.
- Digest incluye bloque "Portfolio actual" (crypto siempre, ETFs si yfinance disponible).
- Digest incluye linea "IRPF est.: X EUR (si vendieras hoy)" si hay ganancias no realizadas en BTC/ETH.
- Digest incluye "Margen IRPF: X EUR hasta siguiente tramo" si hay ganancias realizadas en el anno.
- Digest incluye "Staking ETH YYYY: +X EUR" si hay staking en el anno en curso.
- Digest incluye bloque "Asignacion vs targets": % actual de cada activo vs SPARPLAN_TARGETS con drift.
- Digest incluye bloque "Correlacion 30d": BTC/SP500, ETH/SP500, BTC/ETH (Pearson, retornos diarios).
- Digest guarda snapshot semanal en `user_portfolio_snapshot` (idempotente por semana ISO).
- Dashboard: endpoint `/api/alerts?days=30[&alert_type=X&severity=Y]` (excluye heartbeats por defecto), `/api/snapshots`, `/api/drift` (allocation vs targets en vivo), `/api/portfolio_pnl` (P&L por activo unrealized+realized).
- `tax-headroom --notify --threshold N`: envia Discord si margen IRPF < N EUR (LOCAL ONLY, dedup 7d).
- `drift-check` muestra "Para rebalancear: Compra/Vende X EUR de ASSET" para activos con drift >10pp.
- `user_trade.side`: valores validos: "buy", "sell", "dividend", "staking". Sin CHECK constraint en DB.
- `user_portfolio_snapshot`: tabla nueva (no tocar `portfolio_snapshots` que es infraestructura backtest).
- Ver `RESEARCH.md` para todos los hallazgos del research y senales descartadas

## Sistema en produccion

GitHub Actions: check cada 4h (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
Digest semanal: domingos 09:00 UTC. DB cleanup mensual: dia 1 de cada mes 03:00 UTC.
Secret DISCORD_WEBHOOK_URL en el repo.

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
python main.py drift-check [--notify]  # Drift cartera vs targets Sparplan (LOCAL, yfinance)
python main.py db-cleanup [--keep-days 90]  # Purgar alert_log viejos (default: conservar 90d)
python main.py dashboard               # Web dashboard localhost:8000

# Rebalanceo anual (BTC/ETH en unidades, ETFs en EUR)
python main.py rebalance --btc 0.05 --eth 0.5 --sp500 5000 --semis 1200 --realty 1200 --uranium 300

# Portfolio tracker (SOLO LOCAL, nunca en CI)
python main.py portfolio add-buy  --asset BTC --units 0.001 --price-eur 45000 --source sparplan
python main.py portfolio add-buy  --asset SP500 --units 1.5 --price-eur 480 --source sparplan
python main.py portfolio add-sell --asset BTC --units 0.0003 --price-eur 87000 --source dca_out
python main.py portfolio show / history / history-chart / export
python main.py portfolio import trades.csv [--dry-run]     # Importar trades desde CSV
python main.py portfolio tax-report [--year 2024] [--csv]  # Informe IRPF anual (plusvalias + rendimientos)
python main.py portfolio add-dividend --asset REALTY_INCOME --amount-eur 12.50 [--date 2024-03-15]
python main.py portfolio add-staking  --asset ETH --units 0.005 --price-eur 1800 [--date 2024-03-15]
python main.py tax-headroom [--year 2024]                  # Margen IRPF: realizadas vs tramo actual
python main.py tax-simulate --asset BTC --units 0.01 --price-eur 90000  # Simula venta hipotetica -> delta IRPF + net cash
python main.py what-if --asset BTC --price 150000          # Proyecta drift y DCA-out si BTC llega a $150k
python main.py health-check                                # Valida DB + APIs externas + heartbeat + webhook
python main.py explain-alert --id 42                       # Detalles de alerta historica (por id o --type)
python main.py tax-headroom --notify [--threshold 2000]    # Envia Discord si margen < threshold (LOCAL)

# Monte Carlo jubilacion
python main.py retirement-plan [--age 35 --retire-age 60 --target-eur 800000]
python main.py retirement-plan --inflation 0.025            # Con deflacion a EUR reales (2.5% inf/ano)

# Research (scripts standalone, requieren internet)
python research/sp500_crash_research.py
python research/full_plan_simulation_2020.py
python research/btc_crash_sensitivity.py   # Research 8: threshold sensitivity -5% a -30%

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
- Tests: pytest, 173 tests actualmente
- NO usar caracteres unicode especiales en Python (Windows cp1252)
- SQLAlchemy: convertir a dicts dentro del `with get_session()` antes de usar fuera del bloque.
  Patron de referencia: `_row_to_dict` en `cmd_portfolio` de `main.py`.
- Migraciones DB: `PRAGMA table_info` + `ALTER TABLE` en `init_db()`.
  Referencia: `data/database.py:_migrate_user_trade()` (idempotente).
- yfinance: import lazy (dentro de funciones) para que CI funcione sin ella.
- ccxt: import lazy (dentro de `__init__` de la clase) en `data/collector.py` y `data/sentiment.py`
- Retry API: `_get_with_retry()` en `data/market_data.py` (3 intentos, backoff exponencial 1s/2s)
- MVRV None-safe: `fetch_mvrv()` retorna `None` si la key no esta en la respuesta (no `0.0`)

## Estructura relevante

```
alerts/discord_bot.py     -- Logica alertas + Discord webhooks (constantes, dedup, sender)
alerts/digest.py          -- Digest semanal: send_weekly_digest() (importa de discord_bot, no al reves)
data/market_data.py       -- Capa centralizada de APIs externas (CoinGecko, OKX, CoinMetrics, Stooq)
data/portfolio.py         -- Logica FIFO e IRPF (solo crypto)
data/etf_prices.py        -- Precios ETF en EUR via yfinance (local-only)
analysis/monte_carlo.py   -- Proyeccion jubilacion Monte Carlo
dashboard/app.py          -- FastAPI + dashboard web (usa halving_cycle_info de cli/constants)
cli/constants.py          -- SPARPLAN_TARGETS, LAST_HALVING, DRIFT_THRESHOLD, IRPF_BRACKETS_2024, halving_cycle_info() (fuente de verdad)
cli/commands_decision.py  -- tax-simulate, what-if, health-check, explain-alert (decision-support local)
main.py                   -- CLI entry point (20 comandos)
research/                 -- Scripts standalone de research (excluidos de contexto Claude)
```

## Lo que NO hacer

- NO mover `strategies/` a `research/` -- es infraestructura de backtesting usada por
  `python main.py backtest` y cubierta por tests (257 LOC).
- NO buscar senales on-chain adicionales de salida para BTC/ETH -- patron consolidado:
  MVRV alto, NUPL>0.75, RSI>85, F&G>80 son momentum, no techos. Ver RESEARCH.md.
- NO usar yfinance en `alerts/`, `digest.py`, CI ni en modulos importados por check/digest.
- NO cambiar la cache key de GitHub Actions -- `run_id` + `restore-keys` es correcto e intencional.
- NO crear docstrings ni comentarios en logica obvia.
- NO agregar manejo de errores para escenarios que no pueden ocurrir.
- NO cambiar umbrales de produccion sin backtest IS/OOS completo y aprobacion explicita.

## DB Schema (resumen)

SQLite en `data/cryptotrader.db`. Tablas relevantes:

| Tabla | Columnas clave | Uso |
|---|---|---|
| `alert_log` | id, alert_type, severity, btc_price, eth_price, metric_value, notified, timestamp | Deduplicacion alertas |
| `user_trade` | id, asset, asset_class, units, price_eur, fee_eur, source, side, trade_date | Portfolio FIFO (side: buy/sell/dividend/staking) |
| `candle` | symbol, timestamp, open, high, low, close, volume | Datos OHLCV (backtest) |
| `user_portfolio_snapshot` | id, snapshot_date (ISO week "YYYY-Www"), data_json | Snapshots semanales portfolio personal |
| `portfolio_snapshots` | id, total_value_usdt, ... | Infraestructura backtest -- NO usar para portfolio personal |

Migracion de referencia: `data/database.py:_migrate_user_trade()` (idempotente, PRAGMA table_info).
ORM completo en `data/models.py`.

## Protocolo de cierre de sesion

Al terminar cualquier tarea con cambios de codigo, research o decisiones:
1. Actualizar `CLAUDE.md` si cambian convenciones, comandos o arquitectura activa
2. Actualizar `RESEARCH.md` si hay nuevos hallazgos de research
3. Actualizar memoria del proyecto en `.claude/projects/.../memory/project_overview.md`
4. Commit (conventional) + push

## Playbooks de extension

Guias paso-a-paso para (A) anadir alerta Discord, (B) script de research, (C) comando CLI,
(D) fuente de datos: ver `docs/PLAYBOOKS.md`. Se lee bajo demanda -- NO en contexto por defecto.
