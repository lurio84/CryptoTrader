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
- Crash buying: re-validado 2026-04: +10.6% a 7d vs baseline +0.8% (N=4 eventos, muestra pequena)
- Funding negativo: +23% a 30d, 88% win rate (no re-validable, sin datos historicos gratuitos)
- ETH MVRV < 0.8: re-validado 2026-04: +10.1% a 30d, 61% win rate vs baseline +4.2% (CONFIRMADO aunque menor que documentado originalmente por diferencia de periodo de analisis)
- ETH MVRV 0.8-1.0: re-validado 2026-04: +6.3% a 30d, 54% win rate vs baseline (CONFIRMADO)
- Fear & Greed Index: NO funciona como predictor (extreme fear da PEOR retorno que baseline)
- Indicadores tecnicos (SMA/RSI/BB): ninguno supera buy & hold
- NO vender despues de rallies (momentum continua, +10.8% tras +30% rally)
- ETH MVRV > 3.0 como senal de venta: DESCARTADO. No ha ocurrido desde 2017. En el bull run 2021 (ETH $4831) el MVRV fue solo ~2.0. Pausar DCA en zonas altas mejora 0.3%/yr (estadisticamente insignificante)

## Hallazgos sobre estrategias de salida/rebalanceo (research 2026-04)

Script: `backtesting/exit_strategy_research.py` (datos reales 2018-2026)

### Analisis 1: Rebalanceo por porcentaje de cartera
- Rebalanceo ANUAL es la mejor estrategia: +209% vs +164% sin rebalanceo (CAGR 14.7% vs 12.5%)
- Ademas mejora el drawdown maximo: -37.8% vs -55.5%
- Calmar ratio: 0.39 vs 0.23 (70% mejor riesgo/retorno ajustado)
- Mecanismo: vender crypto cuando supera su % objetivo fuerza ventas cerca de tops y reinversion en activos mas baratos
- Derivacion sin rebalanceo al final del periodo: BTC deriva de 22.9% objetivo a 38.1% (+15pp)
- Coste: 9 EUR en fees a lo largo de 8 anos (9 rebalanceos x 1 EUR flat en TR, totalmente justificado)
- IMPLEMENTAR: rebalanceo anual cuando BTC o ETH supera target en >10% (threshold optimo)

### Analisis 2: Profit parcial BTC por precio absoluto
- Vender 33% a $100k: +409% vs +341% hold puro (+68pp diferencia) - MEJOR resultado
- Vender 25% a $100k + 25% a $200k: +393% - tambien bueno
- Vender a niveles bajos ($20k-$30k) fue catastrofico: hasta -115% vs hold (BTC siguio subiendo)
- El $100k fue nivel real: BTC llego a $124.8k (pico) en este ciclo (2024-2025)
- Si BTC sigue a $200k+, las ventas a $100k pareceran menos buenas en perspectiva historica
- ALERTA ACTIVA: bot Discord envia alerta orange cuando BTC >= $100k (dedup 30 dias)

### Analisis 3: BTC MVRV como senal de venta/pausa
- BTC MVRV SI llega a extremos (5.88 en 2013, 4.72 en 2017, 3.96 en 2021, 2.78 en 2024)
- TENDENCIA A LA BAJA en cada ciclo (igual que ETH MVRV - ciclos maduran)
- En periodo 2018-2026: MVRV nunca supero 4.0 (solo 0 semanas de pausa posibles)
- Solo 3 semanas a MVRV >= 3.5, 14 semanas a MVRV >= 3.0
- Pausa DCA cuando MVRV >= 4.0: sin efecto (nunca ocurrio desde 2018)
- MVRV como predictor de retornos negativos: NO funciona (dias con MVRV alto tienen retornos MAYORES que baseline porque son tendencias alcistas)
- CONCLUSION: BTC MVRV como senal de venta tambien DESCARTADO para ciclos modernos
- Nota: datos 2010 de MVRV son ruido (precio $0, irrelevantes para analisis de inversion)

### Analisis 0 (re-validacion): Confirmacion de senales de compra existentes (2026-04)
- BTC crash <= -15%: re-validado con N=4 eventos. +10.6% a 7d vs baseline +0.8% (CONFIRMADO)
  Win rate 50% (vs documentado 77%) - muestra demasiado pequena para estadistica fiable de win rate
- ETH MVRV < 0.8: re-validado N=535 dias. +10.1% a 30d, 61% win rate vs baseline +4.2% (CONFIRMADO)
  Los valores originales (+34%, 89%) probablemente corresponden a un periodo diferente (2015-2020)
  El efecto positivo es real pero mas moderado en ciclos modernos 2018-2026
- ETH MVRV 0.8-1.0: +6.3% a 30d, 54% win rate vs baseline +4.2% (CONFIRMADO)
- Funding negativo: no re-validable (sin datos historicos en API publica gratuita)

### Analisis 4: Profit parcial ETH por precio absoluto (2026-04)
- Vender 33% a $3k: +374% vs +305% hold puro (+69pp diferencia) - MEJOR resultado
- Vender 25% a $3k: +357% (+52pp vs hold) - tambien significativo
- $3k fue nivel real: ETH llego a $3,431 en mayo 2021 (primera vez)
- $5k y $10k: no alcanzados nunca (ATH ~$4865) - son niveles forward-looking
- ALERTA ACTIVA: bot Discord envia alerta orange cuando ETH >= $3k (dedup 30 dias)

### Analisis 5: ETH MVRV como senal de venta/pausa (2026-04)
- ETH MVRV picos por ciclo: ~5.06 (2016, precio $6), ~2.30 (2021, $3887), ~1.59 (2024, $4073)
- TENDENCIA A LA BAJA mas pronunciada que BTC (ciclos maduran mas rapido)
- MVRV alto predice retornos MAYORES, no menores (igual que BTC MVRV)
  MVRV >= 1.5: +30.4% a 30d vs baseline +12.9% (retornos superiores, no inferiores)
- Pausar DCA cuando MVRV alto: HURTS performance en todos los thresholds
- CONCLUSION: ETH MVRV como senal de venta DESCARTADO. Misma conclusion que BTC MVRV.
- Nota: datos 2015-2016 son ruido (ETH precio $1-6, mercado inmaduro)

## Decisiones importantes tomadas

- Discord unico canal de alertas (Telegram eliminado)
- Precios via CoinGecko (Binance bloquea IPs de GitHub)
- Funding rate via OKX API (Binance y Bybit bloquean IPs de GitHub)
- ETH MVRV via CoinMetrics community API
- DB de alertas cacheada en GitHub Actions (deduplicacion funciona entre runs)
- NO usar saveback 2% de TR para pagar con crypto (vender crypto es mala idea segun datos)
- NO usar F&G como senal de compra (validado que no funciona)
- Staking ETH activado (gratis, sin lock-up en TR)
- NO implementar senal de venta por MVRV alto (irrelevante en ciclos modernos, validado 2015-2026 para BTC y ETH)
- Rebalanceo anual de cartera: VALIDADO como util (implementar manualmente 1x/ano, no requiere automatizacion)
- Profit parcial BTC a $100k: ALERTA ACTIVA en Discord (orange, dedup 30d) -- validado +68pp vs hold
- Profit parcial ETH a $3k: ALERTA ACTIVA en Discord (orange, dedup 30d) -- validado +69pp vs hold
- ETH MVRV alto como venta: DESCARTADO (Analysis 5: retornos son MAYORES con MVRV alto, no menores)
- Senales de compra re-validadas con datos 2018-2026: todas confirmadas, win rates algo menores que documentados originalmente (ciclos modernos mas eficientes)

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
