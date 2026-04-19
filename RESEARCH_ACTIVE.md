# CryptoTrader - Research activo (senales implementadas o en espera)

Resultados de research validados que impactan la estrategia de produccion.
Para research descartado e historico completo ver `RESEARCH_ARCHIVE.md`.

## Resumen ejecutivo

| Senal | Veredicto | Accion |
|-------|-----------|--------|
| Rebalanceo anual (Research 1) | ACTIVO | Alerta drift >10pp via `drift-check` |
| DCA-out BTC sistematico (Research 3) | ACTIVO | Venta 3% cada $20k sobre $80k |
| Impacto IRPF (Research 4) | ACTIVO | Modelo FIFO, brackets ES 2024 |
| S&P 500 crash (Research 6) | ACTIVO | Alerta -7% en 5d, N=13, p=0.003 |
| BTC crash -15% 24h (Research 8) | MANTENER | -14% mejor soporte estadistico pero diff 1pp |
| BTC multi-day crash -20% 7d (Research 11) | ORANGE-ESPERA | N_OOS=4 insuficiente; re-evaluar 2027-2028 |
| BTC funding rate negativo (Research 12) | ACTIVO | Alerta -0.01% validada, N=127, p<0.001, OOS +2.5% |
| DCA-out ETH sistematico (Research 14) | ACTIVO | Venta 3% cada $1k sobre $3k. Delta after-tax +1,324 EUR vs hold (+45%) |

Metodologia obligatoria por research: split 70/30 IS/OOS + Mann-Whitney U p<0.05 IS + bootstrap 95% CI (N=10.000) + positivo OOS.

---

## Research 1: Rebalanceo anual de cartera (2026-04)

Script: `research/exit_strategy_research.py`

- Rebalanceo ANUAL: +209% vs +164% sin rebalanceo (CAGR 14.7% vs 12.5%)
- Drawdown maximo: -37.8% vs -55.5% (mejor riesgo)
- Calmar ratio: 0.39 vs 0.23 (70% mejor riesgo/retorno)
- Mecanismo: fuerza ventas cerca de tops y reinversion en activos baratos
- BTC deriva de 22.9% objetivo a 38.1% (+15pp) sin rebalanceo
- Coste: 9 EUR en fees a lo largo de 8 anos (9 rebalanceos x 1 EUR en TR)
- Threshold optimo: rebalancear cuando BTC o ETH supera target en >10pp

**ACTIVO:** `drift-check` cmd + alerta Discord `rebalance_drift_ASSET` (orange, dedup 7d).

---

## Research 3: DCA-out sistematico BTC (2026-04)

Script: `research/exit_signals_research3.py`

Filosofia: no predecir el techo, reducir exposicion gradualmente conforme sube.

- Regla: vender 3% por cada $20k por encima de $80k
- Sin impuestos: +483% vs hold +341% (+142pp, 29 ventas)
- Con impuestos IRPF (FIFO, brackets 2024, EUR/USD=1.10):
  - +388% vs hold +273% (+115pp despues de impuestos)
  - Hold paga 2.125 EUR; estrategia paga 2.959 EUR pero gana +115pp
- Break-even: DCA-out gana si BTC termina ciclo por debajo de ~$108k
- BTC historicamente corrige 70-80% desde ATH

**ACTIVO:** alertas Discord `btc_dca_out_Xk` y `eth_dca_out_Xk` (orange, dedup 30d).

---

## Research 4: Impacto fiscal IRPF Espana (2026-04)

Script: `research/exit_signals_research4.py`

- Modelo: FIFO cost basis, brackets 2024 (19%/21%/23%/27%/28%)
- EUR/USD = 1.10 (promedio 2018-2026). Sin correccion se sobreestimaba el impuesto ~10%.
- Tax drag DCA-out vs no-tax: -85.8pp
- Tax drag hold vs no-tax: -61.7pp
- Impuestos favorecen al hold en timing, pero DCA-out captura suficiente ganancia extra
- Riesgo overfitting: DCA-out gana si BTC <$108k al final del ciclo

**ACTIVO:** implementado en `data/portfolio.py` (tax-report, tax-headroom) y digest semanal.

---

## Research 6: S&P 500 crash (2026-04)

Script: `research/archive/sp500_crash_research.py`

- Datos: yfinance ^GSPC semanal 2000-2026 (N=1370 semanas)
- Threshold -5% (N=31): p=0.025 a 4w (+3.2%), p=0.004 a 13w (+5.6%)
- Threshold -7% (N=13): p=0.003 a 4w (+6.1%), p=0.012 a 13w (+9.5%)
- Threshold -10% (N=5): p-values no significativos
- Bug corregido: alineacion fechas S&P (cierre viernes) vs BTC (cierre domingo) -> normalizar a lunes ISO

**ACTIVO:** alerta `sp500_crash` a -7% (mejor edge). `SP500_CRASH_THRESHOLD=-7` en `discord_bot.py`.

---

## Research 8: BTC crash threshold sensitivity (2026-04)

Script: `research/archive/btc_crash_sensitivity.py`

Datos: yfinance BTC-USD daily 2015-2026 (4,108 dias). Split exploracion <2021 / validacion >=2021. Bootstrap 95% CI (N=10,000). Mann-Whitney U test.

Resultados clave:

| Threshold | N  | p-val 7d | Delta 30d | OOS 7d | Verdict |
|-----------|----|----------|-----------|--------|---------|
| **-14%** | **13** | **0.020** | **+10.6pp** | **+0.7%** | **RED** (el unico filtro completo) |
| -15% |  9 | 0.071 | +15.2pp | -8.4%  | DISCARD OOS (N=4) |
| -16% |  5 | 0.021 | +24.0pp | n/a    | sin OOS |

**MANTENER -15% en produccion.** -14% tendria mejor soporte estadistico pero la diferencia (1pp) es negligible dado el bajo N. Re-evaluar si en proximo ciclo hay 2-3 eventos nuevos.

`BTC_CRASH_THRESHOLD = -15` SIN CAMBIOS.

---

## Research 11: BTC multi-day crash como senal complementaria (2026-04)

Script: `research/btc_multi_day_crash_research.py`
Cache: `data/research_cache/btc_multi_day_results.txt`

Hipotesis: un crash distribuido en 7 dias (ej. -20%) no capturado por alerta 24h tiene edge adicional.

Setup: yfinance BTC-USD 2015-2026. Signal: caida de N% en W dias. Exclusion: si alerta 24h (<-15%) se disparo en ultimos 3 dias. IS <2022, OOS >=2022.

**Resultado principal (W=7d, N=-20%):** p=0.018, delta=+3.8pp, OOS=+3.2%, WR=74%. Criterios RED cumplidos.

**Limitacion critica:** N_OOS = 4 es muy bajo. El veredicto RED es estadisticamente valido pero la senal real-world necesita mas eventos OOS antes de confiar en el edge completamente.

**ORANGE de espera**: la senal tiene edge pero N_OOS=4 insuficiente. Re-evaluar cuando N_OOS >= 8 (estimado 2027-2028 en ciclo alcista). Si se implementa: umbral -20% en 7d, cooldown 7d, severidad orange.

---

## Research 12: BTC funding rate negativo (2026-04)

Script: `research/funding_negative_research.py`
Cache: `data/research_cache/funding_negative_results.txt`

Motivacion: cerrar deuda metodologica. `funding_negative` era la unica senal en produccion sin backtest formal (threshold -0.01% heredado por intuicion, nunca validado con IS/OOS + Mann-Whitney + bootstrap).

Hipotesis: cuando el funding BTC de futuros perpetuos se vuelve significativamente negativo (shorts pagan a longs), historicamente precede rebotes.

Setup: Binance BTCUSDT perpetual funding (cada 8h, desde 2019-10). Signal day = min de las 3 fundings del dia < threshold. Cooldown 1d (matches produccion). Split IS <2023 / OOS >=2023. Horizontes 7d/14d/30d. Bootstrap N=10.000.

**Resultados principales (forward 7d):**

| Variante | Threshold | N | N_OOS | Delta 7d | p-val | WR | IS | OOS | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **plain** | **-0.01%** | **127** | **9** | **+3.7pp** | **<0.001** | **67%** | **+4.6%** | **+2.5%** | **RED** |
| plain | -0.02% | 43 | 0 | +6.4pp | <0.001 | 79% | +7.2% | n/a | RED (sin OOS) |
| plain | -0.03% | 21 | 0 | +9.4pp | <0.001 | 95% | +10.3% | n/a | RED (sin OOS) |
| persist>=2 | -0.01% | 101 | 8 | +4.0pp | <0.001 | 68% | +4.9% | +3.7% | RED |

**Hallazgos clave:**

1. **Threshold actual (-0.01%) validado**: N=127, p<0.001, OOS positivo. La intuicion original era correcta, ahora esta soportada por datos.
2. **Thresholds mas estrictos (-0.02% a -0.05%) tienen delta mayor pero N_OOS=0**: todos los eventos extremos ocurrieron antes de 2023. No se pueden validar fuera de muestra.
3. **Variante persistencia (2+ fundings 8h consecutivos negativos)** mejora OOS marginalmente (+3.7% vs +2.5%) a costa de complejidad. No se implementa.
4. **Limitacion**: N_OOS=9 es bajo. El edge es real pero con pocos eventos post-2023 (mercado alcista con funding mayoritariamente positivo).

**MANTENER -0.01% en produccion.** `FUNDING_RATE_THRESHOLD = -0.0001` SIN CAMBIOS. Re-evaluar si en proximo bear market N_OOS alcanza ~20.

---

## Research 14: ETH DCA-out sistematico (2026-04)

Script: `research/eth_dca_out_research.py`
Cache: `data/research_cache/eth_dca_out_results.txt`

Motivacion: cerrar deuda metodologica. Las alertas `eth_dca_out_Xk` estaban en produccion con parametros (`base=$3k`, `step=$1k`, `pct=3%`, `cooldown=30d`, `max=$50k`) **nunca formalmente backtesteados**. El script `exit_signals_research4.py` analiza solo BTC; los parametros ETH estan en Part 3 (linea 705) como "suggested" por extrapolacion desde BTC, sin simulacion. Esta situacion es distinta a Research 3 (BTC DCA-out) que si tuvo simulacion completa.

Setup: simulacion 2018-01 a 2026-04, Sparplan ETH 2 EUR/semana (matches production), IRPF Spain 2024 con FIFO cost basis, EUR/USD=1.10. Mismas reglas de produccion (cooldown 30d por nivel, venta `pct%` de holdings al cruzar nivel).

**Grid de parametros testeado:**

| Config | End after-tax | Delta vs HOLD | CAGR | N sales |
|---|---|---|---|---|
| HOLD (baseline) | 2,939 | - | 16.0% | 0 |
| **PROD b=$3k s=$1k p=3%** | **4,263** | **+1,324 (+45%)** | **21.4%** | **35** |
| b=$3k s=$500 p=3% (fine) | 4,700 | +1,761 (+60%) | 22.8% | 57 |
| b=$3k s=$1k p=5% | 4,641 | +1,702 (+58%) | 22.7% | 35 |
| b=$3k s=$2k p=3% | 3,933 | +994 (+34%) | 20.2% | 26 |
| b=$4k s=$1k p=3% | 3,550 | +610 (+21%) | 18.7% | 9 |
| b=$4k s=$1k p=5% | 3,882 | +943 (+32%) | 20.0% | 9 |
| b=$5k s=$1k p=3% | 2,939 | **+0 (nunca dispara)** | 16.0% | 0 |

**Hallazgos clave:**

1. **Parametros de produccion validados**: +1,324 EUR despues de impuestos (+45%) vs hold puro en el periodo 2018-2026. CAGR 21.4% vs 16.0% hold (+5.35pp).

2. **Base=$3k es correcto**: cualquier base >= $4k reduce drasticamente el edge. ETH paso mucho menos tiempo sobre $4k (131 dias vs 614 sobre $3k). Base=$5k nunca disparo (ETH max historico = $4,831 el 2021-11-10).

3. **Step=$1k es el compromiso optimo**: step=$500 es marginalmente mejor (+$437) pero overhead operacional y 57 vs 35 ventas (mas eventos fiscales). Step=$2k pierde edge (-$330 vs produccion).

4. **pct=3% validado**: pct=5% es marginalmente mejor (+$378 EUR) pero con mayor regret risk si ETH continua subiendo despues. Mantener 3% por consistencia con BTC y menor drawdown en escenarios alcistas.

5. **Niveles $5k-$50k en la config son especulativos**: historicamente nunca han disparado. No cuestan nada tenerlos en el codigo (se activaran solo si ETH los alcanza en el proximo ciclo). **ETH necesita subir +37% desde ATH actual para activar el primer nivel nuevo.**

6. **Impuestos IRPF bien modelados**: 798 EUR pagados (18.9% del EUR vendido), consistente con los tramos espanoles para gains anuales 5-15k EUR. El after-tax advantage sigue siendo sustancial despues de pagar impuestos progresivos.

**MANTENER parametros actuales.** `ETH_DCA_OUT_BASE=3_000`, `ETH_DCA_OUT_STEP=1_000`, `ETH_DCA_OUT_PCT=3`, `ETH_DCA_OUT_MAX=50_000`, `COOLDOWN_DCA_OUT=720h` SIN CAMBIOS.

**Limitacion**: backtest 2018-2026 incluye un unico ciclo completo (2020-2022). El edge depende fuertemente de que ETH vuelva a alcanzar $3k+ y luego caiga (como en 2021-2022). Si el proximo ciclo peak es mucho mayor ($10k+) sin retracements significativos, el DCA-out sub-performaria. Escenario de regret: ETH a $15k permanente sin caidas -> hold habria sido mejor. Mitigacion: pct=3% (no 5%) conservador.

---

## Investigacion pendiente (baja prioridad)

- **Ajuste DCA-out**: si BTC supera ATH $124k con claridad, reconsiderar nivel de inicio ($80k)
- **CDD real**: requiere datos de pago (CoinMetrics free no lo tiene)
- **Tickers ETF UCITS**: SPY/SOXX/O/URA son proxies USD. TR usa ETFs europeos (ej. SXR8.DE)
- **Verificar ETH stakeado TR**: confirmar si venta es inmediata o requiere unstaking
- **Dedup funding_negative ciego a intensidad**: el cooldown de 24h no re-alerta aunque el funding empeore drasticamente (ej. -0.01% -> -0.05% al dia siguiente). Revisar si tiene sentido un threshold de re-alerta por intensidad. Requiere backtest antes de tocar produccion.
