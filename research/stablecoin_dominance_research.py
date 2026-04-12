"""stablecoin_dominance_research.py
==================================
Research 12: Stablecoin mcap share spike as a BTC bearish leading indicator.

Hipotesis
---------
Cuando el ratio (stablecoin mcap) / (crypto mcap) sube bruscamente >2 puntos
porcentuales respecto a su media rolling 30d, BTC cae en los siguientes
3-14 dias (retail rotando a cash defensivo anticipa correccion).

Fuentes (sin API key)
---------------------
- Stablecoins:  DefiLlama /stablecoincharts/all  (publico, sin key)
- BTC/ETH mcap: CoinMetrics community API       (publico, sin key)

Nota: CoinGecko /global/market_cap_chart (total crypto mcap) es PRO-only
desde 2024 (HTTP 401 en free tier). Como alternativa libre usamos
BTC + ETH mcap como denominador, que representa ~60-75% del total crypto
cap durante todo el periodo analizado y captura la misma rotacion
defensiva que motiva la hipotesis original.

Metodologia
-----------
- Split temporal 70% IS / 30% OOS
- Signal: delta_pp = ratio - rolling_30d_mean > 2pp, cooldown 7d
- Horizontes forward BTC: 3d, 7d, 14d, 30d
- Mann-Whitney U (alternative='less', hipotesis: signal_ret < baseline_ret)
- Bootstrap 95% CI (N=10.000) para mean signal return
- Umbral validacion (horizonte primario 7d):
    p_IS < 0.05  AND  delta_OOS < 0  AND  N_OOS >= 10
- NO p-hacking: umbral +2pp fijado al inicio. No se reajusta.

Run
---
    python research/stablecoin_dominance_research.py

Output
------
Tabla horizontes + veredicto VALIDADA/DESCARTADA con razonamiento.
Cache CSV en data/research_cache/stablecoin_dominance.csv
Resultados en data/research_cache/stablecoin_dominance_results.txt
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
CM_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"

FETCH_START = "2018-01-01"
FETCH_END   = "2026-04-12"

IS_SPLIT_FRAC = 0.70

ROLLING_WINDOW_D    = 30
SIGNAL_THRESHOLD_PP = 2.0   # +2 percentage points above rolling mean
COOLDOWN_D          = 7

HORIZONS_D       = [3, 7, 14, 30]
PRIMARY_HORIZON  = 7
N_BOOTSTRAP      = 10_000
MIN_N_OOS        = 10
MIN_N_STATS      = 3

CACHE_DIR    = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE   = CACHE_DIR / "stablecoin_dominance.csv"
RESULTS_FILE = CACHE_DIR / "stablecoin_dominance_results.txt"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_stablecoin_mcap() -> pd.Series:
    print("  [download] DefiLlama /stablecoincharts/all ...")
    r = requests.get(STABLECOIN_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    rows: dict[pd.Timestamp, float] = {}
    for d in data:
        ts = int(d["date"])
        val = d.get("totalCirculatingUSD", {}).get("peggedUSD")
        if val is None:
            continue
        day = pd.Timestamp(datetime.fromtimestamp(ts, tz=timezone.utc).date())
        rows[day] = float(val)
    s = pd.Series(rows, name="stablecoin_mcap_usd").sort_index()
    return s


def fetch_cm_metric(asset: str, metric: str) -> pd.Series:
    print(f"  [download] CoinMetrics {asset}/{metric} ...")
    params = {
        "assets": asset,
        "metrics": metric,
        "frequency": "1d",
        "start_time": FETCH_START,
        "end_time": FETCH_END,
        "page_size": 10_000,
    }
    out: dict[pd.Timestamp, float] = {}
    url = CM_URL
    cur_params: dict | None = params
    while True:
        r = requests.get(url, params=cur_params, timeout=60)
        r.raise_for_status()
        body = r.json()
        for row in body.get("data", []):
            t = pd.Timestamp(row["time"][:10])
            v = row.get(metric)
            if v is None:
                continue
            out[t] = float(v)
        next_url = body.get("next_page_url")
        if not next_url:
            break
        url = next_url
        cur_params = None
    return pd.Series(out, name=f"{asset}_{metric}").sort_index()


def build_dataset() -> pd.DataFrame:
    if CACHE_FILE.exists():
        print(f"  [cache] Loading {CACHE_FILE}")
        df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        return df

    stablecoin = fetch_stablecoin_mcap()
    btc_mcap   = fetch_cm_metric("btc", "CapMrktCurUSD")
    eth_mcap   = fetch_cm_metric("eth", "CapMrktCurUSD")
    btc_price  = fetch_cm_metric("btc", "PriceUSD")

    df = pd.DataFrame({
        "stablecoin_mcap": stablecoin,
        "btc_mcap":        btc_mcap,
        "eth_mcap":        eth_mcap,
        "btc_price":       btc_price,
    })
    df = df.dropna()
    df = df[(df.index >= FETCH_START) & (df.index < FETCH_END)]
    df.to_csv(CACHE_FILE)
    print(f"  [cache] Saved {len(df)} rows -> {CACHE_FILE}")
    return df


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

def compute_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["denom_mcap"] = df["btc_mcap"] + df["eth_mcap"]
    df["ratio"]      = df["stablecoin_mcap"] / df["denom_mcap"] * 100  # percent
    df["rolling_30d"] = (
        df["ratio"]
        .rolling(ROLLING_WINDOW_D, min_periods=ROLLING_WINDOW_D)
        .mean()
    )
    df["delta_pp"]    = df["ratio"] - df["rolling_30d"]
    return df


def build_signal_dates(df: pd.DataFrame) -> pd.DatetimeIndex:
    candidates = df.index[df["delta_pp"] > SIGNAL_THRESHOLD_PP]
    signals: list[pd.Timestamp] = []
    last: pd.Timestamp | None = None
    for d in sorted(candidates):
        if last is not None and (d - last).days < COOLDOWN_D:
            continue
        signals.append(d)
        last = d
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def forward_return(prices: pd.Series, signal_date, horizon_days: int) -> float | None:
    try:
        idx = prices.index.get_loc(signal_date)
    except KeyError:
        return None
    target_idx = idx + horizon_days
    if target_idx >= len(prices):
        return None
    entry = prices.iloc[idx]
    exit_ = prices.iloc[target_idx]
    if entry == 0:
        return None
    return float((exit_ - entry) / entry)


def bootstrap_mean_ci(arr: np.ndarray) -> tuple[float, float]:
    if len(arr) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(arr), size=(N_BOOTSTRAP, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _clean(lst: list[float | None]) -> list[float]:
    return [r for r in lst if r is not None]


def analyse(
    prices: pd.Series,
    signal_dates: pd.DatetimeIndex,
    non_signal_dates: pd.Index,
    is_end: pd.Timestamp,
    horizon: int,
) -> dict:
    sig_fwd  = _clean([forward_return(prices, d, horizon) for d in signal_dates])
    base_fwd = _clean([forward_return(prices, d, horizon) for d in non_signal_dates])

    is_fwd   = _clean([forward_return(prices, d, horizon) for d in signal_dates     if d < is_end])
    oos_fwd  = _clean([forward_return(prices, d, horizon) for d in signal_dates     if d >= is_end])
    is_base  = _clean([forward_return(prices, d, horizon) for d in non_signal_dates if d < is_end])
    oos_base = _clean([forward_return(prices, d, horizon) for d in non_signal_dates if d >= is_end])

    mean_ret  = float(np.mean(sig_fwd))  if sig_fwd  else float("nan")
    base_mean = float(np.mean(base_fwd)) if base_fwd else float("nan")
    delta     = mean_ret - base_mean if not (np.isnan(mean_ret) or np.isnan(base_mean)) else float("nan")

    wr_down = float(np.mean([r < 0 for r in sig_fwd])) if sig_fwd else float("nan")
    ci_lo, ci_hi = bootstrap_mean_ci(np.array(sig_fwd)) if sig_fwd else (float("nan"), float("nan"))

    p_less = float("nan")
    if len(is_fwd) >= MIN_N_STATS and len(is_base) >= MIN_N_STATS:
        _, p_less = stats.mannwhitneyu(is_fwd, is_base, alternative="less")

    is_mean       = float(np.mean(is_fwd))   if is_fwd   else float("nan")
    is_base_mean  = float(np.mean(is_base))  if is_base  else float("nan")
    oos_mean      = float(np.mean(oos_fwd))  if oos_fwd  else float("nan")
    oos_base_mean = float(np.mean(oos_base)) if oos_base else float("nan")

    is_delta  = is_mean  - is_base_mean  if not (np.isnan(is_mean)  or np.isnan(is_base_mean))  else float("nan")
    oos_delta = oos_mean - oos_base_mean if not (np.isnan(oos_mean) or np.isnan(oos_base_mean)) else float("nan")

    return {
        "n":          len(sig_fwd),
        "n_is":       len(is_fwd),
        "n_oos":      len(oos_fwd),
        "delta":      delta,
        "wr_down":    wr_down,
        "ci_lo":      ci_lo,
        "ci_hi":      ci_hi,
        "p_less":     p_less,
        "is_delta":   is_delta,
        "oos_delta":  oos_delta,
    }


def make_verdict(results: dict[int, dict]) -> tuple[str, list[str]]:
    r = results[PRIMARY_HORIZON]
    p_is       = r["p_less"]
    delta_oos  = r["oos_delta"]
    n_oos      = r["n_oos"]

    fails: list[str] = []
    if np.isnan(p_is) or p_is >= 0.05:
        fails.append(
            f"p_IS={'nan' if np.isnan(p_is) else f'{p_is:.3f}'} >= 0.05 "
            f"(no significativo a horizonte {PRIMARY_HORIZON}d)"
        )
    if np.isnan(delta_oos) or delta_oos >= 0:
        delta_str = "nan" if np.isnan(delta_oos) else f"{delta_oos*100:+.2f}pp"
        fails.append(f"delta_OOS={delta_str} no es negativo (no predice caida OOS)")
    if n_oos < MIN_N_OOS:
        fails.append(f"N_OOS={n_oos} < {MIN_N_OOS} (muestra OOS insuficiente)")

    if not fails:
        return "VALIDADA", []
    return "DESCARTADA", fails


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("STABLECOIN DOMINANCE SPIKE RESEARCH (Research 12)")
    print("=" * 70)
    print(f"  Periodo:        {FETCH_START} - {FETCH_END}")
    print(f"  Stablecoins:    DefiLlama /stablecoincharts/all")
    print(f"  Denominador:    BTC + ETH mcap (CoinMetrics community)")
    print(f"  Signal:         delta = ratio - rolling_{ROLLING_WINDOW_D}d > {SIGNAL_THRESHOLD_PP}pp")
    print(f"  Cooldown:       {COOLDOWN_D}d  |  Horizontes: {HORIZONS_D}d")
    print(f"  Split IS/OOS:   {IS_SPLIT_FRAC:.0%} temporal  |  Primario: {PRIMARY_HORIZON}d")
    print(f"  Bootstrap:      N={N_BOOTSTRAP:,}  |  MW-U alternative='less'")
    print()

    try:
        df = build_dataset()
    except requests.RequestException as e:
        print(f"\nERROR de red: {e}", file=sys.stderr)
        print("Research DESCARTADO -- no se pueden obtener datos publicos sin API key.")
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"\nERROR de datos: {e}", file=sys.stderr)
        print("Research DESCARTADO -- formato de respuesta inesperado.")
        sys.exit(1)

    if len(df) < 365:
        print(f"ERROR: dataset demasiado corto ({len(df)} dias).")
        print("Research DESCARTADO -- muestra insuficiente.")
        sys.exit(1)

    df = compute_signal(df)
    df_ready = df.dropna(subset=["delta_pp", "btc_price"])
    prices   = df_ready["btc_price"]

    signal_dates = build_signal_dates(df_ready)
    non_signal   = df_ready.index.difference(signal_dates)

    n_days     = len(df_ready)
    is_end_idx = int(n_days * IS_SPLIT_FRAC)
    is_end     = df_ready.index[is_end_idx]

    print(f"  Dataset valido: {n_days} dias  ({df_ready.index[0].date()} -> {df_ready.index[-1].date()})")
    print(f"  Ratio actual:   {df_ready['ratio'].iloc[-1]:.2f}%   "
          f"(rolling30d={df_ready['rolling_30d'].iloc[-1]:.2f}%)")
    print(f"  IS:  {df_ready.index[0].date()} -> {is_end.date()}")
    print(f"  OOS: {is_end.date()} -> {df_ready.index[-1].date()}")
    print(f"  Signals post-cooldown: {len(signal_dates)}")
    print()

    results_by_h: dict[int, dict] = {}
    for h in HORIZONS_D:
        results_by_h[h] = analyse(prices, signal_dates, non_signal, is_end, h)

    # -----------------------------------------------------------------------
    # Output table
    # -----------------------------------------------------------------------

    lines: list[str] = []
    lines.append("STABLECOIN DOMINANCE SPIKE (Research 12)")
    lines.append("=" * 70)
    lines.append(f"Periodo: {df_ready.index[0].date()} -> {df_ready.index[-1].date()}   N_dias={n_days}")
    lines.append(f"IS_end = {is_end.date()}   Signals = {len(signal_dates)}")
    lines.append(
        f"Ratio actual = {df_ready['ratio'].iloc[-1]:.2f}%  "
        f"(rolling{ROLLING_WINDOW_D}d = {df_ready['rolling_30d'].iloc[-1]:.2f}%)"
    )
    lines.append("")

    header = (f"  {'H':>3}  {'N':>4}  {'N_IS':>4}  {'N_OOS':>5}  "
              f"{'delta':>8}  {'p_IS':>6}  {'WR_dn':>7}  "
              f"{'IS_d':>8}  {'OOS_d':>8}  {'CI95_lo':>8}  {'CI95_hi':>8}")
    sep = "  " + "-" * 95
    lines.append(header)
    lines.append(sep)
    print(header)
    print(sep)

    def fp(v: float, decimals: int = 2) -> str:
        return f"{v*100:+.{decimals}f}%" if not np.isnan(v) else "   -   "

    def fpv(v: float) -> str:
        return f"{v:.3f}" if not np.isnan(v) else "  -  "

    for h in HORIZONS_D:
        r = results_by_h[h]
        line = (f"  {h:>3}  {r['n']:>4}  {r['n_is']:>4}  {r['n_oos']:>5}  "
                f"{fp(r['delta']):>8}  {fpv(r['p_less']):>6}  {fp(r['wr_down']):>7}  "
                f"{fp(r['is_delta']):>8}  {fp(r['oos_delta']):>8}  "
                f"{fp(r['ci_lo']):>8}  {fp(r['ci_hi']):>8}")
        print(line)
        lines.append(line)

    print()
    lines.append("")

    # -----------------------------------------------------------------------
    # Verdict
    # -----------------------------------------------------------------------

    verdict, fails = make_verdict(results_by_h)
    r_primary = results_by_h[PRIMARY_HORIZON]

    lines.append("VEREDICTO")
    lines.append("=========")
    print("VEREDICTO")
    print("=========")

    if verdict == "VALIDADA":
        msg = (
            f"  VALIDADA (horizonte {PRIMARY_HORIZON}d): "
            f"p_IS={r_primary['p_less']:.3f}, "
            f"delta_OOS={r_primary['oos_delta']*100:+.2f}pp, "
            f"N_OOS={r_primary['n_oos']}"
        )
        print(msg)
        lines.append(msg)
        lines.append("  ACCION: considerar promocion a alerta Discord (requiere aprobacion explicita).")
    else:
        print(f"  DESCARTADA (horizonte {PRIMARY_HORIZON}d):")
        lines.append(f"  DESCARTADA (horizonte {PRIMARY_HORIZON}d):")
        for f in fails:
            print(f"    - {f}")
            lines.append(f"    - {f}")
        lines.append("")
        lines.append("  RAZONAMIENTO:")
        if r_primary["n"] == 0:
            lines.append("    Ningun dia cumplio el umbral +2pp con cooldown 7d. El ratio stablecoin")
            lines.append("    apenas se desvia de su rolling 30d en mas de 2pp: la hipotesis requiere")
            lines.append("    un movimiento mas brusco del normalmente observado.")
        else:
            if not np.isnan(r_primary["delta"]) and r_primary["delta"] > 0:
                lines.append("    Tras un spike de stablecoin share, BTC no cae en promedio:")
                lines.append(f"    delta (signal - baseline) 7d = {r_primary['delta']*100:+.2f}pp.")
                lines.append("    Los spikes ocurren justo DESPUES de caidas fuertes de BTC (cuando el")
                lines.append("    denominador se contrae), no ANTES -- es senal coincidente, no leading.")
            elif not np.isnan(r_primary["is_delta"]) and r_primary["is_delta"] >= 0:
                lines.append("    La senal no muestra edge bearish en muestra: IS delta no-negativo.")
            elif not np.isnan(r_primary["oos_delta"]) and r_primary["oos_delta"] >= 0:
                lines.append("    La senal funcionaba IS pero se invierte OOS -- posible overfitting")
                lines.append("    o regime change (la estructura del mercado de stablecoins cambio).")
            if r_primary["n_oos"] < MIN_N_OOS:
                lines.append(f"    Ademas N_OOS={r_primary['n_oos']} < {MIN_N_OOS}, muestra insuficiente.")
        lines.append("")
        lines.append("  ACCION: NO implementar. Archivar en RESEARCH_ARCHIVE.md.")

    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Resultados guardados en {RESULTS_FILE}")


if __name__ == "__main__":
    main()
