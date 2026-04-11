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

Script: `research/exit_strategy_research.py` (datos reales 2018-2026)

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
- SUSTITUIDO por DCA-out sistematico (ver seccion research3/research4)

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
- SUSTITUIDO por DCA-out sistematico (ver seccion research3/research4)

### Analisis 5: ETH MVRV como senal de venta/pausa (2026-04)
- ETH MVRV picos por ciclo: ~5.06 (2016, precio $6), ~2.30 (2021, $3887), ~1.59 (2024, $4073)
- TENDENCIA A LA BAJA mas pronunciada que BTC (ciclos maduran mas rapido)
- MVRV alto predice retornos MAYORES, no menores (igual que BTC MVRV)
  MVRV >= 1.5: +30.4% a 30d vs baseline +12.9% (retornos superiores, no inferiores)
- Pausar DCA cuando MVRV alto: HURTS performance en todos los thresholds
- CONCLUSION: ETH MVRV como senal de venta DESCARTADO. Misma conclusion que BTC MVRV.
- Nota: datos 2015-2016 son ruido (ETH precio $1-6, mercado inmaduro)

### Analisis adicional: Senales relativas con N>10 (exit_signals_research2.py, 2026-04)

Script: `research/exit_signals_research2.py` (datos reales 2018-2026)
Motivacion: buscar senales de venta con mas eventos historicos que N=1 (precio absoluto)

#### Analisis A: BTC precio / 200-day MA ratio (bins por nivel de sobrecalentamiento)
- Bin 1.5-2.0x (N=24 eventos): 30d=+12.6% -- MAYOR que baseline +3.7% (momentum continua)
- Bin 2.0-2.5x (N=10 eventos): 30d=+7.7% -- MAYOR que baseline (igual patron que MVRV)
- Bin >=2.5x (N=3 eventos): insuficiente N para validar
- CONCLUSION: MA ratio como senal de venta DESCARTADO. Mismo patron que MVRV: bull markets
  con ratio alto predicen retornos MAYORES, no menores. El momentum continua.

#### Analisis B: BTC % ganancia desde minimo de 365 dias
- Bin 300-500% (N=18 eventos): 30d=+3.8% vs baseline +3.7% -- sin efecto predictivo
- Bin >=500% (N=19 eventos): 30d=-1.7%, 90d=-12.0% vs baseline +14.3% -- CONFIRMADO
  Esta es la senal relativa mas fuerte encontrada: cuando BTC sube >500% desde su minimo
  anual, el retorno a 90 dias es -12% vs +14.3% baseline (-26pp de diferencia)
  Nota: la senal se activa tarde en el ciclo (ej. Noviembre 2020 con BTC en $24k) pero
  BTC continuo subiendo hasta $64k en Abril 2021. Por eso no sirve como trigger de venta.
  Util como INDICADOR INFORMATIVO de que estamos en zona de riesgo elevado.

#### Analisis C: Simulacion DCA + venta con MA ratio como trigger
- Vender 20% cuando ratio > 2.0x: -78pp vs hold (PEOR)
- Vender 25% cuando ratio > 2.0x: -96pp vs hold (PEOR)
- Vender 33% cuando ratio > 2.0x: -121pp vs hold (MUCHO PEOR)
- Vender cuando ratio > 3.0x: nunca ocurrio (N=0), identico a hold
- CONCLUSION DEFINITIVA: vender usando MA ratio como trigger DESTRUYE retornos.
  El mercado sube mas despues de que el ratio llega a 2x. La venta deja fuera de
  la continuacion del bull run. NO implementar como mecanismo de venta automatica.

#### Analisis D: Senal combinada (MA ratio + gain-from-low)
- ratio>2.0 AND gain>300% (N=9): 30d=+9.1% -- MAYOR que baseline (no es senal de venta)
- ratio>2.5 AND gain>300% (N=3): insuficiente N
- CONCLUSION: combinacion tampoco funciona como senal de venta.

#### Conclusion general del research de senales relativas
- NO existe ninguna senal relativa mecanica (con N>10) que mejore el hold DCA en retorno total
- El gain-from-low >=500% es informativo (90d retorno es -12% vs +14.3% baseline) pero
  se activa demasiado pronto en el ciclo para ser un trigger de venta fiable
- La estrategia validada sigue siendo: DCA + rebalanceo anual + profit-taking a milestones

## Research 3: On-chain + DCA-out sistematico + rigor estadistico (2026-04)

Script: `research/exit_signals_research3.py`
Mejoras metodologicas: bootstrap CI 95%, Mann-Whitney U test, split exploracion/validacion (2018-2022 / 2022-2026), nota de multiple comparisons.

### Analisis 1: NVT ratio proxy (CapMrktCurUSD / TxTfrCnt / PriceUSD)
- NVTAdj no disponible en tier gratuito CoinMetrics, se usa proxy propio
- Rango en 2018-2026: 14.5 - 37.5, mediana 23.5
- Bin extreme NVT (>= p90, ~30): 30d mean = -4.0%, delta = -7.7pp vs baseline, p=0.000
- PERO: todos los eventos extreme NVT ocurrieron en 2018-2022 (N=302 dias)
  En validacion 2022-2026: N=0 eventos. La senal NO generaliza fuera de muestra.
- CONCLUSION: NVT DESCARTADO como senal de venta. Probable artefacto del periodo 2018-2022.

### Analisis 2: DCA-out sistematico -- MEJOR RESULTADO DE LOS 3 SCRIPTS
- Filosofia: no predecir el techo, reducir exposicion gradualmente conforme sube
- Regla implementada: vender 3% de holdings por cada $20k por encima de $80k (BTC)
- Backtest sin impuestos (2018-2026, BTC $13k -> $68k, ATH $124k):
  - "3% per $20k above $80k": +416% vs hold +341% (+75pp, 11 ventas)
  - "5% per $20k above $80k": +454% vs hold (+113pp)
  - "3% per $10k above $80k": +483% vs hold (+142pp, 29 ventas)
- Backtest CON impuestos IRPF espana (FIFO cost basis):
  - "3% per $10k above $80k": +388% vs hold +273% (+115pp DESPUES de impuestos)
  - Hold pago 2.350 EUR impuestos; estrategia pago 3.266 EUR pero aun asi gana +115pp
- Break-even: DCA-out gana si BTC termina el ciclo por debajo de ~$108k
  Si BTC sube a $200k+ y se queda ahi permanentemente, hold puro gana
  Historicamente BTC siempre ha corregido un 70-80% desde ATH
- IMPLEMENTADO: alertas Discord activas (ver seccion de alertas activas)

### Analisis 3: Weekly RSI como senal de venta
- RSI semanal >= 85 (N=12 eventos en 2018-2026, 20 semanas)
- 30d mean = +14.8% (+11.1pp SOBRE baseline). Mismo patron que MVRV y MA ratio.
- En validacion 2022-2026: RSI>=85 da +1.9% a 30d (neutral, no negative)
- CONCLUSION: Weekly RSI DESCARTADO. Overbought extremo en crypto = momentum continua.

### Analisis 4: Halving cycle timing
- Picos historicos: 17 meses post-halving 2016, 18 meses post-2020, 18 meses post-2024
- Fase mas debil: meses 18-24 post-halving: 30d = -7.2% (unica fase con retorno negativo)
- Simulacion (vender 25% al mes 12, pausar DCA meses 12-18): -0.2pp a -11pp vs hold
- CONCLUSION: Halving timing INFORMATIVO para planificar, no mecanico. N=2 ciclos en datos.
  Proximo ciclo de riesgo: abril-octubre 2026 (12-18 meses post-halving abril 2024)

### Analisis 5: Direcciones activas + CDD proxy
- Divergencia activas (precio +50%, activas -20%): N=0 eventos en 2018-2026
- CDD proxy (SplyCur changes, no CDD real): spike >= p90 da 30d=-0.8pp delta=-4.6pp (N=29)
- CONCLUSION: Datos insuficientes o metrica proxy demasiado debil. CDD real requiere datos de pago.

## Research 5: Simulacion plan completo 2020-2026 (2026-04)

Script: `research/full_plan_simulation_2020.py`
Simula el plan real completo: BTC 8€/sem + ETH 2€/sem + crash buys + MVRV buys + DCA-out + staking ETH 4%.
EUR/USD fijo 1.10 (media 2020-2026). Periodo: 2020-01-01 a 2026-04-01.

### Resultado con cooldown MVRV correcto (7 dias)
- Total invertido: 6.120 EUR | Portfolio final: 33.328 EUR | Retorno: +445% | CAGR: ~31%/ano
- Desglose inversion: BTC Sparplan 2.616€ + ETH Sparplan 654€ + BTC crash 250€ (2 eventos) + ETH MVRV 2.600€ (26 eventos)
- DCA-out generado: 6 ventas BTC (1.920 EUR cash) + 2 ventas ETH (1.738 EUR cash)
- Solo Sparplan base (sin alertas): 3.270 EUR → 7.917 EUR (+142%)

### Hallazgo critico: el cooldown de MVRV importa muchisimo
- Cooldown 24h (antes): 128 eventos, 12.800 EUR comprometidos, portfolio 161k EUR (pero no planeado)
- Cooldown 7d (actual): 26 eventos, 2.600 EUR comprometidos, portfolio 33k EUR (controlado y real)
- El retorno masivo del cooldown 24h no refleja mejor senal sino MAS capital desplegado
  a precios historicamente bajos (ETH a $130 en 2020 = 0.84 ETH por cada 100€)
- Con cooldown 24h durante bear markets extendidos se necesitaban hasta 9.000 EUR liquidos disponibles

## Research 4: Validacion pre-implementacion DCA-out (2026-04)

Script: `research/exit_signals_research4.py`

### Parte 1: Impacto fiscal IRPF espana
- Modelo: FIFO cost basis, brackets 2024 (19%/21%/23%/27%/28%)
- Nota metodologica: ganancias calculadas en USD convertidas a EUR con factor EUR/USD=1.10
  (promedio 2018-2026). Sin conversion, el impuesto se sobreestima ~10%.
- Hold puro paga 2.125 EUR impuestos en venta final (18.1% efectivo de 11.759 EUR ganancia)
- DCA-out "3% per $10k above $80k": paga 2.959 EUR en impuestos (distribuidos 2024-2026)
  pero aun asi gana +117pp vs hold despues de impuestos (+396.9% vs +279.4%)
- Tax drag del DCA-out vs no-tax: -85.8pp (paga impuestos antes y en mayor cantidad)
- Tax drag del hold vs no-tax: -61.7pp
- CONCLUSION: impuestos favorecen al hold en terminos de timing y cantidad, pero el
  DCA-out captura suficiente ganancia extra para compensar con margen amplio.

### Parte 2: Analisis de overfitting por precio final
- El backtest termina con BTC a $68k (abajo desde ATH $124k). DCA-out brilla en este escenario.
- Si BTC termina el ciclo en $108k: empate entre DCA-out y hold
- Si BTC termina por encima de $108k permanentemente: hold gana
- Estado de cartera al final del periodo (2026-04-01) con "3% per $10k above $80k":
  Hold tiene 0.2233 BTC + 0 EUR cash
  DCA-out tiene 0.0942 BTC + 11.132 EUR cash (60% menos BTC, pero 11k EUR asegurados)
- CONCLUSION: overfitting es real pero bounded. El riesgo es "BTC sube a $300k y no baja".
  Historicamente improbable, pero posible en ciclos futuros.

## Research 6: S&P 500 crash research (2026-04)

Script: `research/sp500_crash_research.py`
Periodo: S&P 500 semanal 2000-2026 (N=1370 semanas), BTC semanal 2014-2026 (N=603 semanas).
Metodologia: bootstrap CI 10.000 iter, Mann-Whitney U, split exploracion 2000-2012 / validacion 2012-2026.
Thresholds testados: -5%, -7%, -10%, -15% (retorno semanal S&P).

### Resultados principales

- Threshold -5% (N=31 eventos): p=0.025 a 4w (delta +3.2%), p=0.004 a 13w (delta +5.6%)
  Edge CONSISTENTE en ambos splits: expl 13w +5.2% vs validacion 13w +10.2% (se fortalece)
- Threshold -7% (N=13 eventos): p=0.003 a 4w (delta +6.1%), p=0.012 a 13w (delta +9.5%)
  Edge CONSISTENTE: expl 13w +7.0% vs validacion 13w +17.9% (se fortalece en validacion)
- Threshold -10% (N=5): p-values no significativos (0.069 a 4w). N insuficiente.
- Threshold -15% (N=1): N=1, sin estadistica posible.
- VEREDICTO: RECOMENDADO (estadisticamente valido para -5% y -7%)

### Senal compuesta (S&P crash + BTC crash misma semana)
- Con threshold S&P<=-7% y BTC<=-10%: N=2 eventos (insuficiente). Solo S&P (N=3): 4w +15.8% vs baseline +0.8%
- N demasiado pequeno para decision. Informativo: cuando S&P crashea fuerte sin contagio BTC, rebote robusto.
- NOTA tecnica: bug de alineacion de fechas encontrado y corregido (2026-04).
  S&P usa barras semanales con cierre viernes, BTC usa cierre domingo. Normalizar ambas a
  lunes ISO antes del inner join. Fix en `check_compound_signal()` de sp500_crash_research.py.

### Decision de implementacion
- Senal validada estadisticamente pero NO implementada como alerta Discord todavia.
- Si se implementa: threshold -7%, horizonte 4w-13w, compra extra 100 EUR BTC.
- Cuidado: solo 13 eventos historicos en 26 anos. Confianza BAJA por N pequeno (similar a crash buying BTC).

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
- Profit parcial BTC a $100k y ETH a $3k: SUSTITUIDOS por DCA-out sistematico (mas robusto, N alto)
- ETH MVRV alto como venta: DESCARTADO (Analysis 5: retornos son MAYORES con MVRV alto, no menores)
- Senales de compra re-validadas con datos 2018-2026: todas confirmadas, win rates algo menores que documentados originalmente (ciclos modernos mas eficientes)
- MA ratio como senal de venta: DESCARTADO (Analysis A 2026-04: retornos son MAYORES en zona sobrecalentada, igual patron que MVRV)
- Gain-from-low >=500% como senal de venta mecanica: DESCARTADO como trigger. Informativo: 90d retorno -12% vs +14.3% baseline, pero se activa demasiado pronto en el ciclo
- Venta cuando MA ratio > 2.0x: DESTRUYE retornos (-78pp a -121pp vs hold segun % vendido)
- NVT ratio como senal de venta: DESCARTADO (research3: no generaliza fuera de muestra 2022-2026)
- Weekly RSI como senal de venta: DESCARTADO (research3: mismo patron que MVRV, momentum continua)
- Halving timing como regla mecanica: DESCARTADO. Informativo para planificacion (N=2 ciclos)
- DCA-out sistematico BTC: ALERTA ACTIVA -- 3% cada $20k por encima de $80k, cooldown 30d
- DCA-out sistematico ETH: ALERTA ACTIVA -- 3% cada $1k por encima de $3k, cooldown 30d
- Precios en EUR incluidos en mensajes Discord (CoinGecko devuelve USD y EUR en misma llamada)
- ETH staking en TR: pendiente verificar si venta de ETH stakeado es inmediata o requiere unstaking
- Cooldown alertas MVRV cambiado de 24h a 7d (2026-04): con 24h el sistema comprometia 12.800 EUR
  en 128 eventos durante 6 anos al dispararse diariamente en bear markets prolongados. Con 7d:
  26 eventos / 2.600 EUR comprometidos -- alineado con la intencion de "2-5 compras extra/ano"

## Alertas activas en produccion (estado 2026-04)

| Alert type (DB) | Condicion | Accion | Severidad | Dedup |
|---|---|---|---|---|
| btc_crash | BTC cae >15% en 24h | Compra 100-150 EUR BTC | red | 6h |
| funding_negative | Funding rate < -0.01% | Compra 100 EUR BTC | orange | 24h |
| mvrv_critical | ETH MVRV < 0.8 | Compra 100 EUR ETH | red | 7d |
| mvrv_low | ETH MVRV 0.8-1.0 | Aumentar Sparplan ETH | yellow | 7d |
| btc_dca_out_Xk | BTC >= $80k, $100k, $120k... (+$20k) | Vender 3% BTC en TR | orange | 30d |
| eth_dca_out_Xk | ETH >= $3k, $4k, $5k... (+$1k) | Vender 3% ETH en TR | orange | 30d |

Nota: los mensajes Discord incluyen precio en EUR (CoinGecko devuelve usd+eur en misma llamada).

## Auditoria de codigo realizada (2026-04)

Se auditaron todos los scripts de backtesting y alertas. Bugs corregidos:

| Bug | Archivo | Impacto en numeros publicados |
|---|---|---|
| Sharpe ratio usaba sqrt(8760) siempre (hourly) | `backtesting/metrics.py` + `engine.py` | Ninguno (solo afecta estrategias tecnicas descartadas) |
| Cooldown de crash-buy comparaba indice entero con horas | `backtesting/crash_dca_engine.py` | Ninguno (crypto data es continua, sin gaps) |
| Valor final de portfolio sin exit slippage | `backtesting/dca_engine.py` + `crash_dca_engine.py` | Ninguno (simetrico en todas las estrategias) |
| Ganancias en USD aplicadas directamente a tramos IRPF en EUR | `research/exit_signals_research4.py` | **SI**: taxes 2.350→2.125 EUR (hold), 3.266→2.959 EUR (DCA-out). Ventaja DCA-out 115→117pp |
| BTC comprado y vendido el mismo dia en simulacion DCA-out | `research3.py` + `research4.py` | < 7 EUR sobre miles, negligible |
| Liquidacion final sin comision 1 EUR de TR | `research/exit_signals_research4.py` | 1 EUR, negligible |
| DetachedInstanceError en send_weekly_digest(): AlertLog leido fuera de sesion SQLAlchemy | `alerts/discord_bot.py` | Ninguno (bug de produccion, CI fallaba en digest --notify) |

Todos los 41 tests siguen pasando. Las conclusiones estrategicas no cambian.
Los numeros de research4 (IRPF) son los definitivos tras la correccion EUR/USD.

## Mejoras de interfaz y herramientas (2026-04)

### Fix dashboard precio
- `dashboard/app.py:_fetch_prices()` usaba ccxt/Binance (geo-bloqueado en GitHub Actions).
  Reemplazado por CoinGecko identico al resto del sistema (USD + EUR + 24h_change en una sola llamada).

### BTC MVRV informativo
- Nueva funcion `_fetch_btc_mvrv()` en `alerts/discord_bot.py` y `dashboard/app.py`.
- Visible en `python main.py check` y en el dashboard web (6a tarjeta de metricas).
- Solo informativo -- validado en research3 que BTC MVRV alto predice MAYORES retornos (no es senal de venta).
- Umbrales visuales: <1.0 verde, 1.0-2.0 gris, 2.0-3.0 amarillo, >3.0 naranja.

### Indicador de ciclo halving
- Calcula mes actual desde halving (abril 2024) y zona de riesgo (meses 18-24 post-halving).
- CORRECCION: CLAUDE.md anterior decia "zona de riesgo abril-octubre 2026 (meses 12-18)".
  Incorrecto: meses 12-18 = abril-octubre 2025 (ya paso). La zona correcta es MESES 18-24
  (octubre 2025 - abril 2026). Hoy abril 2026 = mes 23.7, al final de la zona de riesgo.
- Visible en `python main.py check` bajo "CICLO HALVING:" y en dashboard (barra de progreso).
- Implementado en: `main.py:_halving_cycle_info()`, `dashboard/app.py:_get_halving_cycle()`,
  `alerts/discord_bot.py:_halving_cycle_text()`.

### Digest semanal Discord
- Nueva funcion `send_weekly_digest()` en `alerts/discord_bot.py`.
- 4 secciones: precios BTC+ETH (USD+EUR), indicadores on-chain (ETH MVRV, BTC MVRV, funding),
  fase del ciclo halving, alertas de los ultimos 7 dias (desde AlertLog).
- Deduplicacion: cooldown 6 dias (alert_type="weekly_digest" en AlertLog).
- Nuevo comando: `python main.py digest [--notify]` (sin --notify: solo preview).
- GitHub Actions: nuevo trigger cron `0 9 * * 0` (domingos 09:00 UTC), step condicional en workflow.

### Portfolio tracker personal (FIFO + IRPF) -- expandido a 6 activos (2026-04)

- Nueva tabla `UserTrade` en `data/models.py` (se crea automaticamente con init_db).
  Campos: date, asset, asset_class (crypto|etf), side, units, price_eur, fee_eur, source, notes.
- Columna `asset_class` anadida via migracion idempotente en `data/database.py:_migrate_user_trade()`.
  Safe para DBs existentes: usa `PRAGMA table_info` antes de `ALTER TABLE`.
- Activos soportados: BTC, ETH (crypto, FIFO+IRPF completo) y SP500, SEMICONDUCTORS,
  REALTY_INCOME, URANIUM (etf, P&L simple con precios live via yfinance).
- Precios ETF en EUR via `data/etf_prices.py` (yfinance, import lazy, SOLO LOCAL).
  Tickers: SPY, SOXX, O, URA. NUNCA importar desde alerts/ ni CI.
- `portfolio show` muestra 3 secciones: [CRYPTO] con FIFO+IRPF, [ETF] con P&L simple,
  [TOTAL] con tabla de los 6 activos vs SPARPLAN_TARGETS y drift en pp.
- Logica FIFO y IRPF en `data/portfolio.py` (solo para activos crypto).
- Datos SOLO locales -- nunca en GitHub Actions ni en el repo publico.
- Backup: `python main.py portfolio export > mis_trades.csv` (incluye columna asset_class).

```
python main.py portfolio add-buy  --asset BTC --units 0.001 --price-eur 45000 --source sparplan [--date YYYY-MM-DD]
python main.py portfolio add-buy  --asset SP500 --units 1.5 --price-eur 480 --source sparplan
python main.py portfolio add-sell --asset BTC --units 0.0003 --price-eur 87000 --source dca_out
python main.py portfolio show      # 3 secciones: Crypto, ETF, Total con allocation table
python main.py portfolio history   # Lista todas las operaciones (crypto + ETF)
python main.py portfolio export    # CSV backup (redirigir a archivo)
```

### Rebalanceo anual -- expandido a 6 activos (2026-04)

- `cmd_rebalance()` acepta ahora los 6 activos por separado.
- BTC y ETH en UNIDADES (precio live de CoinGecko). ETFs en EUR directamente.
- Calcula drift de cada activo vs SPARPLAN_TARGETS. Threshold: 10pp.
- Research: rebalanceo anual mejora CAGR de 12.5% a 14.7% (datos 2018-2026).

```
python main.py rebalance --btc 0.05 --eth 0.5 --sp500 5000 --semis 1200 --realty 1200 --uranium 300
```

Constante global `SPARPLAN_TARGETS` en `main.py` (deriva de SPARPLAN_MONTHLY):
- BTC: 22.86%, ETH: 5.71%, SP500: 45.71%, SEMICONDUCTORS: 11.43%, REALTY_INCOME: 11.43%, URANIUM: 2.86%

### Monte Carlo retirement projection (nuevo, 2026-04)

- Nuevo modulo `analysis/monte_carlo.py`.
- Metodo: bootstrap resampling de retornos mensuales historicos (mismo patron que research3).
  Retorno mensual ponderado = suma(weight_i * R_i(t)) para preservar correlaciones.
  Vectorizado: (n_simulations, T) arrays, sin loop Python.
- Datos: yfinance para todos los activos (BTC-USD, ETH-USD, SPY, SOXX, O, URA).
  Inner join limita historia a ~2017-presente (ETH bottleneck).
  Cache en `data/research_cache/mc_XXX_monthly.csv`.
- Output: MonteCarloResult con p10/p25/p50/p75/p90 por ano + prob_reach_target.
- Nuevo comando `retirement-plan`:

```
python main.py retirement-plan                    # defaults: age=30, retire=65, target=1M EUR, monthly=140
python main.py retirement-plan --age 35 --retire-age 60 --target-eur 800000 --simulations 10000
```

### S&P 500 crash research (nuevo, 2026-04)

- Script standalone `research/sp500_crash_research.py`.
- Datos: yfinance ^GSPC semanal 2000-2026. Cache en `data/research_cache/gspc_weekly.csv`.
- Thresholds testados: -5%, -7%, -10%, -15% weekly return.
- Horizontes forward: 1w, 4w, 13w, 26w, 52w.
- Estadistica: bootstrap CI 95% + Mann-Whitney U. Split: 2000-2012 / 2012-2026.
- Bonus: senal compuesta S&P crash + BTC crash.
- Conclusion automatica: RECOMENDADO o NO IMPLEMENTAR segun p-values y consistencia.

```
python research/sp500_crash_research.py
```

### ETH Staking APY sensitivity (nuevo, 2026-04)

- `research/full_plan_simulation_2020.py:simulate()` acepta ahora `eth_staking_apr` (default 0.04).
- Al ejecutar `python research/full_plan_simulation_2020.py`, primero muestra tabla de
  sensibilidad 3%/4%/5% APY (portfolio EUR + multiplicador + CAGR) antes de los escenarios habituales.

## Investigacion pendiente (proxima sesion)

### Pendiente de baja prioridad
- **Alerta Discord S&P 500 crash**: senal validada (Research 6, -7% threshold). Evaluar si
  implementar como alerta extra (compra BTC cuando S&P cae >7% en una semana). N=13, confianza BAJA.
- **Ajuste parametros DCA-out para proximo ciclo**: cuando BTC supere ATH $124k con claridad,
  reconsiderar si el nivel de inicio ($80k) sigue siendo el optimo o conviene subirlo.
- **CDD real**: Coin Days Destroyed requiere datos de pago (no disponible en CoinMetrics free).
  Si se consigue acceso a datos historicos, podria ser senal de venta relevante.
- **Portfolio import CSV**: actualmente solo se pueden anadir trades manualmente uno a uno.
  Podria anadirse un comando `portfolio import mi_trades.csv` para restaurar desde backup.
- **Tickers ETF ajustados a TR**: los tickers actuales (SPY, SOXX, O, URA) son proxies USD.
  TR usa ETFs UCITS europeos (ej. SXR8.DE para S&P 500). Los precios son equivalentes pero
  si se quiere precio exacto en EUR de la posicion en TR, ajustar ETF_TICKERS en data/etf_prices.py.
- **Verificar ETH stakeado en TR**: pendiente confirmar si venta de ETH stakeado es inmediata.
- **Monte Carlo con inflacion ajustada**: actualmente sin ajuste por inflacion. Anadir flag
  `--inflation 0.025` para deflactar proyecciones a EUR reales de hoy.

### Confianza de las senales implementadas (resumen honesto)
- Rebalanceo anual: ALTA (N=9 independientes, efecto en Calmar consistente)
- ETH MVRV < 0.8 como compra: MEDIA-ALTA (N=535 dias, in-sample)
- BTC crash >15% como compra: BAJA (N=4, insuficiente estadisticamente)
- DCA-out sistematico: MEDIA (backtest in-sample, una sola instancia de ciclo alto)
- Senales descartadas: descarte MUY FIABLE (efectos nulos/negativos robustos en todos los scripts)

## Sistema en produccion

GitHub Actions ejecuta check cada 4h automaticamente (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
GitHub Actions envia digest semanal cada domingo a las 09:00 UTC.
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
python main.py check                  # Check rapido de senales (BTC/ETH/MVRV/funding/halving)
python main.py check --notify         # Check + enviar Discord si hay alerta
python main.py digest                 # Preview del digest semanal
python main.py digest --notify        # Enviar digest semanal a Discord (cooldown 6d)
python main.py dashboard              # Dashboard web localhost:8000

# Rebalanceo anual -- 6 activos (BTC/ETH en unidades, ETFs en EUR)
python main.py rebalance --btc 0.05 --eth 0.5 --sp500 5000 --semis 1200 --realty 1200 --uranium 300

# Portfolio tracker (datos solo locales, nunca en CI)
python main.py portfolio add-buy  --asset BTC --units 0.001 --price-eur 45000 --source sparplan
python main.py portfolio add-buy  --asset SP500 --units 1.5 --price-eur 480 --source sparplan
python main.py portfolio add-sell --asset BTC --units 0.0003 --price-eur 87000 --source dca_out
python main.py portfolio show         # P&L FIFO crypto + P&L ETF + tabla allocation 6 activos
python main.py portfolio history      # Lista de operaciones (crypto + ETF)
python main.py portfolio export       # CSV backup (redirigir a archivo)

# Proyeccion jubilacion Monte Carlo (requiere internet para yfinance)
python main.py retirement-plan                          # defaults: 30->65, 1M EUR, 140 EUR/mes
python main.py retirement-plan --age 35 --retire-age 60 --target-eur 800000

# Research S&P 500 crashes (script standalone, requiere internet)
python research/sp500_crash_research.py

# Simulacion plan completo (con tabla sensibilidad staking 3/4/5%)
python research/full_plan_simulation_2020.py

python main.py collect --symbols BTC/USDT ETH/USDT --since 2020-01-01
python main.py sentiment --since 2020-01-01
```

## Fuentes de datos (todas publicas, sin API key)

- Precios BTC/ETH: CoinGecko API (USD + EUR + 24h_change en una sola llamada)
- Funding rate BTC: OKX API (Binance y Bybit bloquean IPs de GitHub)
- ETH MVRV + BTC MVRV: CoinMetrics community API (assets=eth o assets=btc, mismo endpoint)
- Fear & Greed: alternative.me API
- Precios ETF (LOCAL): yfinance (SPY, SOXX, O, URA + EURUSD=X para conversion EUR)
  SOLO en comandos portfolio/rebalance/retirement-plan. NUNCA en alerts/ ni CI.

## Convenciones

- Conventional commits (hay hook configurado): feat:, fix:, etc.
- Tests: pytest, 41 tests actualmente
- NO usar caracteres unicode especiales en Python (Windows cp1252)
- Objetos SQLAlchemy se expiran al cerrar sesion (expire_on_commit=True por defecto).
  Convertir a dicts dentro del `with get_session()` antes de usar fuera del bloque.
  Ver pattern en `cmd_portfolio` de main.py (`_row_to_dict`).
- Migraciones de DB: usar `PRAGMA table_info` + `ALTER TABLE` en `init_db()`. Ver
  `data/database.py:_migrate_user_trade()` como patron de referencia (idempotente).
- yfinance es dependencia SOLO LOCAL (opcional `[all]`). Import lazy (dentro de funciones)
  para que los modulos funcionen sin yfinance en CI. NUNCA en alerts/ ni monitor.

## Estructura de archivos nuevos (2026-04)

```
analysis/
  __init__.py
  monte_carlo.py          -- Bootstrap MC retirement projection (yfinance)
data/
  etf_prices.py           -- Precios ETF en EUR via yfinance (local-only)
backtesting/
  sp500_crash_research.py -- Research crashes S&P 500 (standalone script)
```

## Protocolo de cierre de sesion (ejecutar siempre al terminar una tarea)

Al finalizar cualquier tarea que involucre cambios de codigo, research o decisiones:

1. **CLAUDE.md**: actualizar con nuevos hallazgos, decisiones tomadas, comandos nuevos,
   o secciones pendiente. Es la fuente de verdad del proyecto.
2. **Memoria**: actualizar `C:\Users\lucas\.claude\projects\...\memory\project_overview.md`
   con cambios relevantes (nuevas herramientas, research completado, estado del sistema).
3. **Commit**: conventional commit agrupando todos los cambios de la sesion.
4. **Push**: `git push` al repo remoto (GitHub Actions lo usa para CI).

Este protocolo aplica incluso si el usuario no lo pide explicitamente.
