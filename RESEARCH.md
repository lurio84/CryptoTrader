# CryptoTrader - Research (indice)

Documentacion dividida para minimizar contexto cargado en Claude:

- **`RESEARCH_ACTIVE.md`** -- senales validadas y en produccion (Research 1, 3, 4, 6, 8, 11, 12, 14).
  Leer cuando: se trabaja en alertas, backtest en activo, ajustes de thresholds.

- **`RESEARCH_ARCHIVE.md`** -- senales descartadas con datos completos (Research 2, 5, 7, 9, 10, 13).
  Leer solo cuando: se propone una hipotesis para verificar si ya se probo.

Metodologia: split 70/30 IS/OOS + Mann-Whitney U p<0.05 IS + bootstrap CI 95% (N=10.000) + positivo OOS.
Ninguno se carga automaticamente en el contexto de Claude.

## Contexto multiple-testing (informativo)

Se han evaluado ~20 hipotesis candidatas. El gate de produccion es IS+OOS+positive,
no una correccion formal de multiple comparisons. Para hacer explicita la severidad,
`analysis/multiple_testing.py` expone:

- `bonferroni_alpha(n, alpha=0.05)`: umbral FWER conservador (alpha/n).
- `bh_fdr_passes(pvals, alpha=0.05)`: procedimiento Benjamini-Hochberg (menos
  conservador, controla FDR en vez de FWER).
- `print_multiple_testing_note(n, observed_p_values, alpha)`: imprime un bloque
  informativo al final de un research script.

Es informativo, no un gate. Permite leer un p=0.020 (BTC crash, N=13) en contexto:
con n=20 hipotesis, Bonferroni exigiria p<0.0025; BH-FDR es mas flexible. Usar
para futuros research scripts; los actuales (funding_negative, btc_multi_day_crash,
exit_signals_research3) ya estan validados y no se retocan.
