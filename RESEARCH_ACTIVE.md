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

## Investigacion pendiente (baja prioridad)

- **Ajuste DCA-out**: si BTC supera ATH $124k con claridad, reconsiderar nivel de inicio ($80k)
- **CDD real**: requiere datos de pago (CoinMetrics free no lo tiene)
- **Tickers ETF UCITS**: SPY/SOXX/O/URA son proxies USD. TR usa ETFs europeos (ej. SXR8.DE)
- **Verificar ETH stakeado TR**: confirmar si venta es inmediata o requiere unstaking
