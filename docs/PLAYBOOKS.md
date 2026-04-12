# Playbooks de extension

Guias paso-a-paso para extender el sistema. Leer bajo demanda (no se carga en contexto por defecto).

## A) Como agregar una nueva alerta Discord

1. **Threshold y cooldown** en `alerts/discord_bot.py` (bloque de constantes, lineas ~22-51):
   ```python
   NEW_SIGNAL_THRESHOLD = -X
   COOLDOWN_NEW_SIGNAL = 24  # horas
   ```

2. **Deteccion** dentro de `check_and_alert()` en `alerts/discord_bot.py`:
   ```python
   if value is not None and value < NEW_SIGNAL_THRESHOLD:
       if not _already_alerted(session, "new_signal", COOLDOWN_NEW_SIGNAL):
           sent = send_discord_message(_format_embed(...))
           _log_alert(session, "new_signal", "orange", btc_price, eth_price, value, sent)
           triggered.append({"type": "new_signal", "severity": "orange", "sent": sent})
   ```

3. **Fuente de datos nueva** (si aplica) en `data/market_data.py`:
   - Funcion `fetch_new_metric()` usando `_get_with_retry()`
   - Retornar `None` (no `0.0`) si el dato no esta disponible
   - Llamar desde `check_and_alert()` y proteger con `if valor is not None`

4. **Test** en `tests/test_discord_bot.py`:
   - Patron: mockear `fetch_prices`, `send_discord_message`, `get_session` (con `_make_session_ctx`)
   - Test trigger + test no-trigger + test dedup (ver tests existentes como referencia)

5. **Requisito critico**: backtest IS/OOS con p<0.05 Mann-Whitney y bootstrap CI antes de produccion.
   Ver metodologia en `RESEARCH_ARCHIVE.md`. NO cambiar umbrales sin este proceso.

6. **Checklist**: `pytest` pasa + `python main.py check` sin errores

---

## B) Como anadir un script de research

- Carpeta: `research/` (activos) | `research/archive/` (descartados historicos)
- Split temporal obligatorio: primeros 70% IS, ultimos 30% OOS
- Tests estadisticos requeridos: p-valor Mann-Whitney U + bootstrap 95% CI (N=10.000)
- Metricas a reportar: delta vs baseline, win rate, N eventos, resultado OOS
- Umbral minimo "senal valida": p<0.05 en IS Y resultado positivo en OOS
- Hallazgos: `RESEARCH_ACTIVE.md` si pasan, `RESEARCH_ARCHIVE.md` si se descartan
- Fuentes disponibles sin API key: CoinGecko, OKX, CoinMetrics community, Stooq, FRED
- NO usar yfinance en research que pueda acabar importado por alerts/ o CI

---

## C) Como anadir un comando CLI

1. **Funcion** en `cli/commands_*.py` segun categoria (ops/portfolio/analysis/data):
   ```python
   def cmd_new_cmd(args: argparse.Namespace) -> None:
       ...
   ```

2. **Registro** en `main.py`, dict `commands`:
   ```python
   "new-cmd": cmd_new_cmd,
   ```

3. **Argparse**: anadir `subparsers.add_parser("new-cmd")` con sus argumentos en `main.py`

4. **yfinance**: si el comando es local-only, import lazy dentro de la funcion:
   ```python
   def cmd_new_cmd(args):
       from data.etf_prices import fetch_all_etf_prices_eur
       ...
   ```

5. **Test minimo**: mockear dependencias externas y verificar comportamiento (no implementacion)

---

## D) Como anadir una nueva fuente de datos

1. **Funcion** en `data/market_data.py`:
   ```python
   def fetch_new_metric() -> float | None:
       try:
           resp = _get_with_retry("https://api.example.com/data")
           return resp.json()["value"]
       except Exception as exc:
           logger.warning("fetch_new_metric failed: %s", exc)
           return None
   ```
   - Usar `_get_with_retry()` para todas las llamadas HTTP (3 intentos, backoff exponencial)
   - Retornar `None` (no `0.0`, no `raise`) si el dato no esta disponible
   - No importar yfinance a nivel modulo en este archivo

2. **Consumo** en `alerts/discord_bot.py` o `alerts/digest.py`:
   - Llamar al inicio de `check_and_alert()` junto al resto de `fetch_*`
   - Proteger siempre: `if new_metric is not None and new_metric < THRESHOLD`
