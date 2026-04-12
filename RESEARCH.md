# CryptoTrader - Hallazgos de Research

Archivo de referencia para resultados de backtesting y decisiones tomadas.
No se carga automaticamente en Claude -- leer solo cuando se trabaja en research/backtesting.

## Senales de compra validadas (datos 2018-2026)

| Senal | Resultado | Confianza | N eventos |
|-------|-----------|-----------|-----------|
| BTC crash >15% en 24h | +10.6% a 7d vs baseline +0.8% | BAJA (N=4) | 4 |
| ETH MVRV < 0.8 | +10.1% a 30d, 61% win rate vs baseline +4.2% | MEDIA-ALTA | 535 dias |
| ETH MVRV 0.8-1.0 | +6.3% a 30d, 54% win rate vs baseline | MEDIA | 535 dias |
| Funding negativo < -0.01% | +23% a 30d, 88% win rate | NO VALIDABLE | sin datos historicos |
| DCA-out sistematico | +388% vs hold +273% post-impuestos (+115pp) | MEDIA | 1 ciclo |
| Rebalanceo anual | CAGR 14.7% vs 12.5%, Calmar 0.39 vs 0.23 | ALTA | N=9 |

## Senales de venta/pausa DESCARTADAS

Todas estas senales se probaron y DESTRUYEN o NO MEJORAN el retorno vs hold DCA:

| Senal | Resultado | Script |
|-------|-----------|--------|
| ETH MVRV > 3.0 (pausa DCA) | Nunca ocurre desde 2017. ETH bull 2021 fue ~2.0. | exit_strategy_research |
| BTC MVRV como venta | Alto predice retornos MAYORES (momentum continua) | exit_signals_research3 |
| ETH MVRV como venta | Mismo patron: MVRV>=1.5 da +30.4% vs baseline +12.9% | exit_strategy_research |
| MA ratio (precio/200d MA) como venta | Ratio alto = retornos MAYORES. Vender al 2x: -78 a -121pp | exit_signals_research2 |
| Gain-from-low >=500% como trigger | Informativo (90d=-12% vs +14.3% baseline) pero activa demasiado pronto | exit_signals_research2 |
| NVT ratio proxy | No generaliza fuera de muestra 2022-2026 | exit_signals_research3 |
| Weekly RSI >= 85 | Overbought extremo = momentum continua (+14.8% a 30d sobre baseline) | exit_signals_research3 |
| Halving timing mecanico | N=2 ciclos, no estadisticamente significativo | exit_signals_research3 |
| Fear & Greed extremo | Extreme fear da PEOR retorno que baseline | exit_signals_research2 |
| SMA/RSI/Bollinger Bands | Ninguno supera buy & hold | engine.py backtests |
| BTC MVRV < 1.0 como compra | delta=-17.2pp a 30d, WR=31%, OOS delta=-10.4pp (WR=0%). DESCARTADO. | btc_mvrv_research |
| BTC MVRV < 0.8 como compra | delta=-4.3pp a 30d, WR=73% (ilusion), N=11. DESCARTADO. | btc_mvrv_research |

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

## Research 2: Profit parcial por precio absoluto (2026-04)

### BTC
- Vender 33% a $100k: +409% vs +341% hold puro (+68pp) -- MEJOR
- Vender 25% a $100k + 25% a $200k: +393%
- Vender a $20k-$30k: catastrofico (BTC siguio subiendo)
- **SUSTITUIDO por DCA-out sistematico**

### ETH
- Vender 33% a $3k: +374% vs +305% hold puro (+69pp) -- MEJOR
- $5k y $10k: nunca alcanzados (ATH ~$4865)
- **SUSTITUIDO por DCA-out sistematico**

## Research 3 (Analisis 2): DCA-out sistematico BTC (2026-04)

Script: `research/exit_signals_research3.py`

Filosofia: no predecir el techo, reducir exposicion gradualmente conforme sube.

- Regla: vender 3% por cada $20k por encima de $80k
- Sin impuestos: "3% per $10k above $80k" da +483% vs hold +341% (+142pp, 29 ventas)
- Con impuestos IRPF (FIFO, brackets 2024, EUR/USD=1.10):
  - +388% vs hold +273% (+115pp despues de impuestos)
  - Hold paga 2.125 EUR; estrategia paga 2.959 EUR pero gana +115pp
- Break-even: DCA-out gana si BTC termina ciclo por debajo de ~$108k
- BTC historicamente corrige 70-80% desde ATH

## Research 4: Impacto fiscal IRPF espana (2026-04)

Script: `research/exit_signals_research4.py`

- Modelo: FIFO cost basis, brackets 2024 (19%/21%/23%/27%/28%)
- EUR/USD = 1.10 (promedio 2018-2026). Sin correccion se sobreestimaba el impuesto ~10%.
- Tax drag DCA-out vs no-tax: -85.8pp
- Tax drag hold vs no-tax: -61.7pp
- Impuestos favorecen al hold en timing, pero DCA-out captura suficiente ganancia extra
- Estado cartera final (2026-04-01): Hold tiene 0.2233 BTC; DCA-out tiene 0.0942 BTC + 11.132 EUR cash
- Riesgo overfitting: DCA-out gana si BTC <$108k al final del ciclo. Hold gana si BTC >$108k permanentemente.

## Research 5: Simulacion plan completo 2020-2026 (2026-04)

Script: `research/full_plan_simulation_2020.py`

Simula: BTC 8€/sem + ETH 2€/sem + crash buys + MVRV buys + DCA-out + staking ETH 4%.
EUR/USD fijo 1.10. Periodo: 2020-01-01 a 2026-04-01.

Con cooldown MVRV 7 dias (correcto):
- Total invertido: 6.120 EUR | Portfolio final: 33.328 EUR | Retorno: +445% | CAGR: ~31%/ano
- Solo Sparplan base (sin alertas): 3.270 EUR -> 7.917 EUR (+142%)
- DCA-out: 6 ventas BTC (1.920 EUR) + 2 ventas ETH (1.738 EUR cash)

Hallazgo critico sobre cooldown MVRV:
- Cooldown 24h: 128 eventos, 12.800 EUR comprometidos (no planeado, requeria 9k EUR liquidos)
- Cooldown 7d: 26 eventos, 2.600 EUR comprometidos (alineado con "2-5 compras extra/ano")

Tabla sensibilidad staking ETH (3%/4%/5% APY): ver script para numeros completos.

## Research 6: S&P 500 crash research (2026-04)

Script: `research/sp500_crash_research.py`

- Datos: yfinance ^GSPC semanal 2000-2026 (N=1370 semanas)
- Threshold -5% (N=31): p=0.025 a 4w (+3.2%), p=0.004 a 13w (+5.6%). Edge CONSISTENTE.
- Threshold -7% (N=13): p=0.003 a 4w (+6.1%), p=0.012 a 13w (+9.5%). Edge CONSISTENTE.
- Threshold -10% (N=5): p-values no significativos. N insuficiente.
- Veredicto: RECOMENDADO estadisticamente para -5% y -7%
- **NO implementado todavia como alerta Discord** (N=13, confianza baja, similar a crash BTC)
- Bug corregido: alineacion fechas S&P (cierre viernes) vs BTC (cierre domingo) -- normalizar a lunes ISO

## Research 7: BTC MVRV como senal de compra (2026-04)

Script: `research/btc_mvrv_research.py`

Hipotesis: BTC MVRV < 1.0 (precio por debajo del coste medio de todos los holders) = zona de capitulacion = senal de compra. Analogia con la senal ETH MVRV validada.

Datos: CoinMetrics community API, BTC CapMVRVCur + PriceUSD, 2010-2026 (5,746 dias).

| Threshold | N eventos | 30d media | 30d baseline | Delta | p-valor | WR 30d |
|-----------|-----------|-----------|--------------|-------|---------|---------|
| MVRV < 0.8 | 11 | +9.9% | +14.2% | **-4.3pp** | 0.522 | 73% |
| MVRV < 1.0 | 13 | -1.8% | +15.4% | **-17.2pp** | 0.174 | 31% |

OOS 2021-2026 (N=4 para MVRV < 1.0, todos en 2022):
- 30d media = -8.1%, delta = -10.4pp, WR = **0%** (BTC siguio cayendo 30 dias despues en todos los casos)

**Por que falla:**
- BTC MVRV < 1.0 se alcanza durante mercados bajistas prolongados (2018, 2022), no son suelos instantaneos
- Los 4 eventos OOS (todos 2022) ocurrieron durante la caida post-LUNA/FTX: cada entrada fue peor en 30d
- El 73% win rate de MVRV < 0.8 es una ilusion: son episodios de 2011-2015 cuando BTC crecia +1000% y cualquier compra habria ganado
- La zona "sostenida" (todos los dias debajo del umbral) muestra +18.5% a 30d con p=0.000, pero es autocorrelacion: esos dias INCLUYEN la recuperacion inicial, lo cual no captura la senal de entrada
- **Diferencia clave vs ETH MVRV:** ETH tiene realizaciones mas frecuentes (holders mas activos), sus fondos son V-shaped. BTC en capitulacion tiende a lateralizar/caer meses.

**Conclusion: DESCARTADO. Alerta `btc_mvrv_critical` eliminada de produccion.**
BTC MVRV sigue siendo informativo en el digest semanal (nivel actual), pero NO como senal de compra.

## Research 8: BTC crash threshold sensitivity (2026-04)

Script: `research/btc_crash_sensitivity.py`

Hipotesis: el threshold de produccion -15% en 24h puede no ser optimo. N=4 eventos historicos es muy bajo para confiar en ese valor exacto.

Datos: yfinance BTC-USD daily 2015-2026 (4,108 dias). Split: exploracion <2021 / validacion >=2021.
Bootstrap 95% CI (N=10,000). Mann-Whitney U test.

Resultados tabla completa (seleccion de filas relevantes):

| Threshold | N  | WR 7d  | Ret 7d | Delta 7d | p-val 7d | Ret 30d | Delta 30d | OOS 7d | Verdict |
|-----------|----|---------|---------|-----------|-----------|---------|-----------|---------|---------| 
| -6%  | 162 | +55.6% | +1.8% | +0.4pp | 0.382 | +7.6%  | +1.1pp | +0.4%  | ORANGE |
| -10% |  44 | +54.5% | +2.2% | +0.9pp | 0.415 | +8.8%  | +2.3pp | -0.7%  | ORANGE |
| -11% |  28 | +60.7% | +3.7% | +2.3pp | 0.121 | +10.5% | +4.0pp | +0.0%  | ORANGE |
| -13% |  18 | +72.2% | +4.6% | +3.2pp | 0.056 | +14.6% | +8.1pp | -1.3%  | ORANGE |
| **-14%** | **13** | **+76.9%** | **+8.5%** | **+7.1pp** | **0.020** | **+17.1%** | **+10.6pp** | **+0.7%** | **RED** |
| -15% |   9 | +66.7% | +9.5% | +8.1pp | 0.071 | +21.7% | +15.2pp | -8.4%  | DISCARD (OOS negativo) |
| -16% |   5 | +80.0% | +13.3% | +12.0pp | 0.021 | +30.5% | +24.0pp | n/a   | ORANGE |

El algoritmo de seleccion eligio -16% (delta mas alto con N>=5), pero ese threshold no tiene datos OOS.

**Hallazgos clave:**
- -14% es el UNICO threshold que pasa el filtro RED completo: p<0.05 en 7d Y 30d, N>=5 (N=13), OOS positivo (+0.7%)
- -15% actual tiene OOS negativo (-8.4%) preocupante, pero N=4 eventos en OOS genera alta varianza
- La diferencia -14% vs -15% es 1pp, dentro del ruido estadistico dado el bajo N
- A umbrales mas extremos (>=-20%) N cae a 1-2: region no estadisticamente viable
- El edge aumenta monotonamente con el threshold mas extremo, pero N cae igual de rapido

**Conclusion: MANTENER -15% en produccion.**
- -14% seria la alternativa con mejor soporte estadistico (el unico RED)
- La diferencia de 1pp es negligible dado el N bajo; no justifica un cambio
- Si en el proximo ciclo se producen 2-3 eventos nuevos, re-evaluar con mas datos

Accion: BTC_CRASH_THRESHOLD = -15 SIN CAMBIOS.

## Research 9: BTC NUPL como senal de venta (2026-04)

Script: `research/research_nupl.py`

Hipotesis: NUPL (Net Unrealized Profit/Loss) = 1 - 1/MVRV mide que fraccion del market cap de BTC
representa ganancia no realizada. Willy Woo define NUPL > 0.75 como zona de "Euforia/Greed" y
techo de ciclo. Testeado como senal de venta/reduccion de DCA-out.

Nota: NUPL se deriva del MVRV ya cacheado (btc_mvrv_daily.csv). Sin API adicional.

Datos: CoinMetrics BTC CapMVRVCur + PriceUSD, 2010-2026. Split IS: 2011-2022 / OOS: 2022-2026.

| Threshold | N (IS) | 30d media | Delta vs baseline | p-val | WR | N (OOS) |
|-----------|--------|-----------|-------------------|-------|----|---------|
| NUPL > 0.75 | 9 | +108.4% | **+91.9pp** | 0.018* | 78% | 0 |
| NUPL > 0.60 | 20 | +41.8% | **+33.2pp** | 0.416 | 60% | 4 |
| NUPL < 0.00 | 9 | +1.0% | **-19.5pp** | 0.396 | 44% | 4 (OOS WR=0%) |
| NUPL < 0.25 | 17 | +11.9% | **-11.7pp** | 0.520 | 71% (IS) / 20% (OOS) | 6 |

**Hallazgo principal: NUPL alto es senal de MOMENTUM, no de techo.**
- NUPL > 0.75: p=0.018, +108% a 30d. Cuando el mercado esta en maxima euforia, BTC sigue subiendo.
- Mismo patron que MVRV alto, RSI > 85 semanal, Fear & Greed extremo: todos predicen continuacion.
- La narrativa de Willy Woo ("NUPL > 0.75 = vender") no se sostiene estadisticamente.
- 0 eventos OOS (2022-2026): BTC no ha alcanzado NUPL > 0.75 en este ciclo.

**NUPL bajo confirma btc_mvrv_research:** NUPL < 0.0 = MVRV < 1.0. OOS WR=0%, consistente con research7.

**Conclusion: DESCARTADO en ambas direcciones.**
- Como senal de VENTA: NUPL alto predice retornos mayores. Usar es perder upside.
- Como senal de COMPRA: mismo resultado que MVRV < 1.0, ya descartado.
- Los niveles de precio del DCA-out ($80k, $100k...) siguen siendo el enfoque correcto.
- Los analiticos on-chain de valoracion NO sirven como senales de salida en BTC.

## Investigacion pendiente (baja prioridad)

- **Alerta S&P 500 crash**: IMPLEMENTADA a -7% (Research 6, N=13, p=0.003 a 4w). Threshold cambiado de -5% a -7% por mejor edge estadistico. Cooldown 7d.
- **Ajuste DCA-out**: si BTC supera ATH $124k con claridad, reconsiderar nivel de inicio ($80k).
- **CDD real**: requiere datos de pago (CoinMetrics free no lo tiene).
- **Tickers ETF UCITS**: SPY/SOXX/O/URA son proxies USD. TR usa ETFs europeos (ej. SXR8.DE).
- **Verificar ETH stakeado TR**: confirmar si venta es inmediata o requiere unstaking.
- **Monte Carlo con inflacion**: anadir flag `--inflation 0.025`.
