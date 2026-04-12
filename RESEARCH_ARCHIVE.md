# CryptoTrader - Research descartado

Senales probadas que NO mejoran el retorno vs hold DCA o que fallan validacion OOS.
Para research activo ver `RESEARCH_ACTIVE.md`.

No se carga automaticamente en Claude -- leer solo cuando se investiga o re-evalua una hipotesis ya probada.

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
| ETH/BTC percentil 10 | p>0.70 en todos los horizontes, OOS negativo | eth_btc_ratio_research |
| DXY_5d <= -2% (buy BTC 7d)   | N_OOS=4 insuficiente, solo 6 eventos en 11 anos (DTWEXBGS) | dxy_btc_correlation_research |
| DXY_10d <= -1.5% (buy BTC 14d) | p_IS=0.488, delta ~0 a 3/7/14d, edge a 30d dominado por drift | dxy_btc_correlation_research |
| Stablecoin share spike +2pp vs rolling 30d (sell BTC 7d) | p_IS=0.639 a 7d, delta 7d=+0.17% (signo opuesto), N_OOS=5 < 10 | stablecoin_dominance_research |
| BTC basis 3m anualizado > +10%/yr (sell BTC 14d)  | Contango alto predice retornos MAYORES, no caidas. N=132, delta14d=-2.5%, p=0.87 | term_structure_research |
| BTC basis 3m anualizado < 0%/yr (buy BTC 14d)     | Backwardation predice continuacion bajista, no rebote. N=79, delta14d=-4.3%, p=0.998 | term_structure_research |

---

## Research 2: Profit parcial por precio absoluto (2026-04)

### BTC
- Vender 33% a $100k: +409% vs +341% hold puro (+68pp) -- MEJOR
- Vender 25% a $100k + 25% a $200k: +393%
- Vender a $20k-$30k: catastrofico (BTC siguio subiendo)
- **SUSTITUIDO por DCA-out sistematico (Research 3)**

### ETH
- Vender 33% a $3k: +374% vs +305% hold puro (+69pp) -- MEJOR
- $5k y $10k: nunca alcanzados (ATH ~$4865)
- **SUSTITUIDO por DCA-out sistematico**

---

## Research 5: Simulacion plan completo 2020-2026 (2026-04)

Script: `research/archive/full_plan_simulation_2020.py`

Simula: BTC 8€/sem + ETH 2€/sem + crash buys + MVRV buys + DCA-out + staking ETH 4%.

Con cooldown MVRV 7 dias (correcto):
- Total invertido: 6.120 EUR | Portfolio final: 33.328 EUR | Retorno: +445% | CAGR: ~31%/ano
- Solo Sparplan base: 3.270 EUR -> 7.917 EUR (+142%)
- DCA-out: 6 ventas BTC (1.920 EUR) + 2 ventas ETH (1.738 EUR cash)

Hallazgo: cooldown 24h dispararia 128 eventos (12.8k EUR comprometidos, no factible) vs 7d dispara 26 eventos (2.6k EUR, alineado con estrategia).

**Veredicto:** validacion operativa. Confirma que el plan completo funciona; no introduce nueva senal.

---

## Research 7: BTC MVRV como senal de compra (2026-04)

Script: `research/archive/btc_mvrv_research.py`

Hipotesis: BTC MVRV < 1.0 = zona de capitulacion = senal de compra. Analogia con la senal ETH MVRV validada.

Datos: CoinMetrics community API, BTC CapMVRVCur + PriceUSD, 2010-2026 (5,746 dias).

| Threshold | N  | 30d media | Delta | p-valor | WR 30d |
|-----------|----|-----------|-------|---------|---------|
| MVRV < 0.8 | 11 | +9.9%  | **-4.3pp** | 0.522 | 73% |
| MVRV < 1.0 | 13 | -1.8%  | **-17.2pp** | 0.174 | 31% |

OOS 2021-2026 (N=4 para MVRV < 1.0, todos en 2022):
- 30d media = -8.1%, delta = -10.4pp, WR = **0%**

**Por que falla:**
- BTC MVRV < 1.0 se alcanza durante mercados bajistas prolongados, no son suelos instantaneos
- El 73% WR de MVRV < 0.8 es una ilusion: episodios de 2011-2015 con +1000% anual
- Diferencia clave vs ETH MVRV: ETH tiene realizaciones mas frecuentes, fondos V-shaped. BTC lateraliza/cae meses.

**DESCARTADO. Alerta `btc_mvrv_critical` eliminada de produccion.**

---

## Research 9: BTC NUPL como senal de venta (2026-04)

Script: `research/archive/research_nupl.py`

Hipotesis: NUPL = 1 - 1/MVRV. Willy Woo define NUPL > 0.75 = "Euforia/Greed" = techo. Testeado como senal de venta.

Datos: derivado de MVRV cacheado, 2010-2026. Split IS: 2011-2022 / OOS: 2022-2026.

| Threshold | N (IS) | 30d | Delta | p-val | WR | N (OOS) |
|-----------|--------|-----|-------|-------|----|---------|
| NUPL > 0.75 | 9 | +108.4% | **+91.9pp** | 0.018* | 78% | 0 |
| NUPL > 0.60 | 20 | +41.8% | +33.2pp | 0.416 | 60% | 4 |
| NUPL < 0.00 | 9 | +1.0% | -19.5pp | 0.396 | 44% | OOS WR=0% |

**NUPL alto es senal de MOMENTUM, no de techo.** Mismo patron que MVRV alto, RSI>85, F&G extremo.

**DESCARTADO en ambas direcciones** (venta y compra). Los niveles DCA-out siguen siendo el enfoque correcto.

---

## Research 10: ETH/BTC ratio como senal de entrada en ETH (2026-04)

Script: `research/eth_btc_ratio_research.py`
Cache: `data/research_cache/eth_btc_ratio_results.txt`

Hipotesis: ETH/BTC al percentil 10 de 180d rolling = ETH infravalorado = outperformance 7-30d.

| Horizonte | N   | Delta  | p-val  | WR  | IS/OOS  | Veredicto |
|-----------|-----|--------|--------|-----|---------|-----------|
| 7d        | 134 | -0.2pp | 0.7302 | 43% | -0.1 / +0.0% | DISCARD |
| 14d       | 134 | -0.7pp | 0.6973 | 42% | -0.1 / -0.2% | DISCARD |
| 30d       | 132 | -1.2pp | 0.6612 | 42% | +2.7 / -1.4% | DISCARD |

**DISCARD.** p >> 0.70 en todos los horizontes. Delta negativo. OOS negativo a 14d y 30d. La infravaloracion relativa no predice outperformance a corto plazo.

---

## Research R4: DXY lead/lag como senal de compra BTC (2026-04)

Script: `research/dxy_btc_correlation_research.py`
Cache: `data/research_cache/dxy_btc_correlation_results.txt` + `dxy_daily.csv`

Hipotesis: caidas bruscas del Broad Dollar Index (FRED DTWEXBGS) anticipan subidas de BTC con lag 3-14d. Fuente FRED CSV publico sin API key.

Metodologia: split 70/30 IS/OOS (<2022 / >=2022), Mann-Whitney U p<0.05, bootstrap 95% CI (N=10.000), cooldown 7d entre senales, horizontes 3/7/14/30d. Regla PASS: p_IS<0.05 AND OOS>0 AND N_OOS>=10.

Dos parametrizaciones testeadas (sin cherry-picking):

| Senal | Regla | N | N_IS | N_OOS | delta (primary H) | p_IS | OOS mean | Veredicto |
|-------|-------|---|------|-------|-------------------|------|----------|-----------|
| A | DXY_5d <= -2%, H=7d   |  6 |  2 |  4 | +2.8% | -     | +1.2% | DISCARD (N_OOS=4 < 10) |
| B | DXY_10d <= -1.5%, H=14d | 57 | 31 | 26 | +0.1% | 0.488 | +3.3% | DISCARD (p_IS=0.488) |

Observaciones:
- DTWEXBGS (broad goods+services) es mucho menos volatil que el DXY futures clasico: -2% en 5d solo ocurre 6 veces en 11 anos, insuficiente para OOS.
- Con el umbral menos restrictivo (B, -1.5% en 10d) hay 57 eventos pero el delta es casi cero a 3/7/14d y solo aparece a 30d (+2.9%, p=0.124). El 30d esta dominado por drift alcista de BTC, no por la senal DXY.
- La correlacion negativa DXY/BTC existe de forma contemporanea, pero no hay edge direccional utilizable con lag 1-14d bajo esta metodologia.
- FRED funciono en primera llamada (no hizo falta fallback a Stooq dx.f).

**DISCARD.** No implementar alerta. La relacion macro USD/BTC es informativa pero no aporta edge estadistico robusto al sistema existente (BTC crash 24h, S&P500 crash, DCA-out).

---

## Research 12: Stablecoin mcap share spike como senal bajista de BTC (2026-04)

Script: `research/stablecoin_dominance_research.py`
Cache: `data/research_cache/stablecoin_dominance_results.txt` + `stablecoin_dominance.csv`

Hipotesis: cuando el ratio (stablecoin mcap) / (crypto mcap) sube bruscamente >2pp respecto a su media rolling 30d, retail esta rotando a cash defensivo y BTC cae en los 3-14d siguientes.

Fuentes (sin API key):
- Stablecoins: DefiLlama `/stablecoincharts/all` (publico). 3.057 filas historicas.
- Denominador: BTC + ETH mcap via CoinMetrics community `CapMrktCurUSD`. CoinGecko `/global/market_cap_chart` (el denominador "ideal") es PRO-only desde 2024 -- HTTP 401 en free tier. BTC+ETH es ~60-75% del crypto mcap total durante todo el periodo y captura la misma rotacion defensiva.

Metodologia: split 70/30 IS/OOS, rolling window 30d, cooldown 7d entre senales, horizontes 3/7/14/30d, Mann-Whitney U alternative='less', bootstrap 95% CI (N=10.000). Umbral PASS: p_IS<0.05 AND delta_OOS<0 AND N_OOS>=10 en horizonte primario 7d. Parametrizacion fijada al inicio (+2pp) sin ajuste posterior.

Dataset: 2018-01-30 -> 2026-04-11, 2.994 dias. Ratio actual 18.19% (rolling30d 19.01%). 30 signals post-cooldown.

| H    | N  | N_IS | N_OOS | delta (sig-base) | p_IS  | WR_down | IS_delta | OOS_delta | Veredicto |
|------|----|------|-------|------------------|-------|---------|----------|-----------|-----------|
| 3d   | 30 | 25   | 5     | -1.11%           | 0.389 | 50.0%   | -1.12%   | -1.05%    | DISCARD   |
| 7d   | 30 | 25   | 5     | +0.17%           | 0.639 | 40.0%   | +0.42%   | -1.20%    | DISCARD   |
| 14d  | 30 | 25   | 5     | +1.12%           | 0.687 | 46.7%   | +1.77%   | -2.51%    | DISCARD   |
| 30d  | 30 | 25   | 5     | -1.68%           | 0.347 | 50.0%   | -1.71%   | -2.22%    | DISCARD   |

**Por que falla:**
- **p_IS nunca significativo** (minimo 0.347 a 30d). El signo de IS_delta incluso se invierte: positivo (+0.42% a 7d, +1.77% a 14d) cuando la hipotesis predice negativo.
- **N_OOS = 5** en todos los horizontes. El periodo 2023-10 -> 2026-04 solo produjo 5 dias con spike >2pp: la estabilidad reciente del mercado de stablecoins (maduracion USDC/USDT) reduce la varianza del ratio.
- El OOS_delta es consistentemente negativo (-1.20% a 7d, -2.51% a 14d, -2.22% a 30d) pero sin significancia IS no es discriminable de ruido, y con N_OOS=5 el bootstrap CI95 de 7d abarca [-2.25%, +4.36%] (cruza cero).
- El spike en share de stablecoins parece ser un indicador **coincidente** (el denominador BTC+ETH se contrae cuando BTC cae, inflando mecanicamente el ratio) mas que un indicador **leading**. No anticipa, registra.

**DISCARD.** No implementar alerta. El edge postulado no existe IS y la muestra OOS es insuficiente para sostener una senal derivada.

---

## Research R5: Term structure futuros BTC (basis 3m) (2026-04)

Script: `research/term_structure_research.py`
Cache: `data/research_cache/btc_term_structure.csv` + `term_structure_results.txt`

Hipotesis:
- Contango extremo (basis 3m anualizado > +10%/ano) = apalancamiento caliente -> BTC corrige en 7-21 dias.
- Backwardation (basis < 0%) = capitulacion (vendedores forzados) -> BTC rebota en 7-21 dias.

Fuentes (sin API key):
- Spot: yfinance BTC-USD daily (local-only, misma fuente que eth_btc_ratio_research).
- Futuros quarterly: Deribit `/public/get_tradingview_chart_data` con contratos `BTC-{DDMMMYY}` (ultimo viernes de Mar/Jun/Sep/Dec). 26 contratos recolectados (dic-2019 -> mar-2026). Padding post-expiry descartado filtrando `volume>0`.
- Basis anualizado = (future / spot - 1) * 365/DTE, eligiendo para cada dia el contrato con DTE mas cercano a 90d dentro de [60, 120] dias.

Metodologia: split IS <2024-03 / OOS >=2024-03 (~70/30 sobre 1.399 dias con basis disponible), cooldown 7d, horizontes 7/14/21/30d, Mann-Whitney U (alternative="less" para SHORT, "greater" para LONG), bootstrap 95% CI (N=10.000). Regla PASS: p_IS<0.05 AND delta>0.02 AND OOS_edge>0 AND N_OOS>=10.

Basis stats (2020-06 -> 2026-04): min=-32.7%, max=+69.3%, mean=+7.7%, p95=+24.0%, p05=-4.3%.

### Variante A -- SHORT: basis_ann > +10%/yr (contango alto)

N=132 (IS=79, OOS=53).

| H    | N   | Sig mean | Base mean | Delta edge | p-val (less) | WR<0 | IS edge | OOS edge |
|------|-----|----------|-----------|------------|--------------|------|---------|----------|
| 7d   | 131 | +4.2%    | +1.5%     | -2.7%      | 0.9914       | 39%  | -5.8%   | -1.7%    |
| 14d  | 131 | +5.9%    | +3.4%     | -2.5%      | 0.8725       | 42%  | -8.3%   | -2.2%    |
| 21d  | 131 | +8.0%    | +5.3%     | -2.7%      | 0.7400       | 44%  | -11.5%  | -2.7%    |
| 30d  | 130 | +9.8%    | +8.0%     | -1.8%      | 0.6515       | 42%  | -14.0%  | -3.3%    |

**Signo opuesto a la hipotesis.** Cuando el contango supera +10%/yr, el retorno esperado de BTC a 7-30d es SUPERIOR al baseline en todos los horizontes. El contango alto es un proxy de "momentum alcista" (apetito por apalancamiento largo durante tendencias fuertes), no una senal de correccion inminente.

### Variante B -- LONG: basis_ann < 0%/yr (backwardation)

N=79 (IS=62, OOS=17).

| H    | N  | Sig mean | Base mean | Delta | p-val (greater) | WR>0 | IS mean | OOS mean |
|------|----|----------|-----------|-------|-----------------|------|---------|----------|
| 7d   | 79 | -1.7%    | +1.9%     | -3.6% | 0.9999          | 37%  | -1.7%   | -1.8%    |
| 14d  | 78 | -0.5%    | +3.8%     | -4.3% | 0.9983          | 37%  | +0.0%   | -2.4%    |
| 21d  | 78 | +1.7%    | +5.8%     | -4.1% | 0.9858          | 37%  | +3.0%   | -3.1%    |
| 30d  | 78 | +5.7%    | +8.4%     | -2.7% | 0.9317          | 42%  | +7.9%   | -2.8%    |

**Signo opuesto a la hipotesis.** La backwardation no precede rebotes: los dias con basis 3m anualizado negativo tienen retornos de BTC a 7-14d PEORES que el baseline. En lenguaje sencillo, cuando los futuros cotizan por debajo del spot (capitulacion/deleverage), el deleverage continua unos dias mas antes de estabilizarse. Funciona como indicador de momentum bajista, no como contrarian.

**Por que ambas variantes fallan:**
- Term structure de crypto se comporta como un **momentum indicator**, no como un mean-reverter. En tendencias fuertes (alcista o bajista) el basis refleja el stress en las posiciones apalancadas, y esa tendencia tiende a persistir 1-3 semanas antes de estabilizarse.
- Esto es consistente con los hallazgos previos del repo: MVRV alto, NUPL alto, RSI>85, F&G>80 tampoco son senales de correccion -- son proxies de momentum. Term structure se suma a la lista.
- La asimetria entre signals SHORT (N=132) y LONG (N=79) refleja que la distribucion del basis esta sesgada al contango (mean +7.7%, p05 solo -4.3%). Backwardation es un evento raro, concentrado en 2022 (crashes Luna/FTX) y 2024-2025 (algunos flush-outs), que no se generaliza.
- N_OOS OK en ambos casos (52 y 16) pero el signo del edge ya esta en contra desde IS, por lo que ningun ajuste de umbral salvaria la senal.

**DISCARD.** No implementar alerta en ninguna direccion. El basis 3m puede seguir siendo util como **indicador de stress contextual** en el digest semanal (informativo, no accionable) pero no como trigger de compra/venta automatica. No tocar thresholds de produccion (btc_crash, sp500_crash, dca_out) -- ninguna interaccion con term structure justifica cambios.

