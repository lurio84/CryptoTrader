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
