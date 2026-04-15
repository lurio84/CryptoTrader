# CryptoTrader - Research (indice)

Documentacion dividida para minimizar contexto cargado en Claude:

- **`RESEARCH_ACTIVE.md`** -- senales validadas y en produccion (Research 1, 3, 4, 6, 8, 11, 12, 14).
  Leer cuando: se trabaja en alertas, backtest en activo, ajustes de thresholds.

- **`RESEARCH_ARCHIVE.md`** -- senales descartadas con datos completos (Research 2, 5, 7, 9, 10, 13).
  Leer solo cuando: se propone una hipotesis para verificar si ya se probo.

Metodologia: split 70/30 IS/OOS + Mann-Whitney U p<0.05 IS + bootstrap CI 95% (N=10.000) + positivo OOS.
Ninguno se carga automaticamente en el contexto de Claude.
