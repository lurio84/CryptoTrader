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

## Auditoria de codigo (2026-04)

| Bug | Archivo | Impacto |
|-----|---------|---------|
| Sharpe ratio usaba sqrt(8760) siempre (hourly) | backtesting/metrics.py + engine.py | Ninguno (estrategias tecnicas descartadas) |
| Cooldown crash-buy comparaba indice entero con horas | backtesting/crash_dca_engine.py | Ninguno (crypto data continua) |
| Valor final sin exit slippage | backtesting/dca_engine.py | Ninguno (simetrico) |
| Ganancias USD aplicadas a tramos IRPF en EUR sin conversion | research/exit_signals_research4.py | SI: taxes 2.350->2.125 EUR (hold), 3.266->2.959 EUR (DCA-out) |
| BTC comprado y vendido el mismo dia en DCA-out | research3.py + research4.py | <7 EUR, negligible |
| Liquidacion final sin comision 1 EUR TR | research/exit_signals_research4.py | 1 EUR, negligible |
| DetachedInstanceError en send_weekly_digest() | alerts/discord_bot.py | Bug produccion, CI fallaba |
| Dead code _format_status_embed() + claves *_raw en dashboard | alerts/discord_bot.py + dashboard/app.py | Ninguno |

Todos los 60 tests pasan. Conclusiones estrategicas no cambian.

## Investigacion pendiente (baja prioridad)

- **Alerta S&P 500 crash**: validada (Research 6, -7% threshold). Evaluar implementacion (N=13, confianza baja).
- **Ajuste DCA-out**: si BTC supera ATH $124k con claridad, reconsiderar nivel de inicio ($80k).
- **CDD real**: requiere datos de pago (CoinMetrics free no lo tiene).
- **Portfolio import CSV**: anadir comando `portfolio import mi_trades.csv`.
- **Tickers ETF UCITS**: SPY/SOXX/O/URA son proxies USD. TR usa ETFs europeos (ej. SXR8.DE).
- **Verificar ETH stakeado TR**: confirmar si venta es inmediata o requiere unstaking.
- **Monte Carlo con inflacion**: anadir flag `--inflation 0.025`.
