"""eth_btc_ratio_research.py
===========================
Research: ETH/BTC ratio como senal de entrada en ETH.

Hipotesis
---------
Cuando el ratio ETH/BTC (precio ETH expresado en BTC) cae al percentil 10
de una ventana rolling de 180 dias, ETH outperforma a BTC en los dias
siguientes. La senal captura momentos en que ETH esta infravalorado
relativamente a BTC (independientemente de la direccion del mercado).

Setup
-----
- Datos:      yfinance BTC-USD + ETH-USD daily, 2016-01-01 a 2026-04-01
- Ratio:      ETH_close_USD / BTC_close_USD (diario)
- Senal:      ratio[t] < percentil10 rolling 180d calculado en t-1
              (lag de 1 dia para evitar lookahead bias)
- Metrica:    outperformance ETH vs BTC = ETH_fwd_H - BTC_fwd_H
              Si > 0: ETH sube mas (o baja menos) que BTC
- Horizontes: 7d, 14d, 30d
- Baseline:   dias no-senal en el mismo periodo
- Stats:      bootstrap 95% CI (N=10.000), Mann-Whitney U test
- Split:      IS 2017-2022 / OOS 2023-2026 (aprox 70/30)

Run
---
    python research/eth_btc_ratio_research.py

Output
------
Tabla IS + OOS y CONCLUSION. Guarda resultado en
data/research_cache/eth_btc_ratio_results.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FETCH_START  = "2016-01-01"   # descarga desde aqui para calentar la ventana 180d
START_DATE   = "2017-01-01"   # inicio real del analisis (180d de warmup cubiertas)
END_DATE     = "2026-04-01"
SPLIT_DATE   = "2023-01-01"   # IS < SPLIT / OOS >= SPLIT (aprox 70/30)

ROLLING_WINDOW  = 180          # dias para el percentil rolling
SIGNAL_PCT      = 0.10         # percentil bajo el cual se dispara la senal
COOLDOWN_DAYS   = 7            # minimo dias entre senales (evitar clusters)
HORIZONS_D      = [7, 14, 30]

N_BOOTSTRAP     = 10_000
PVALUE_THRESH   = 0.05
MIN_N_RELIABLE  = 5

CACHE_DIR   = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE  = CACHE_DIR / "eth_btc_ratio_daily.csv"
RESULTS_FILE = CACHE_DIR / "eth_btc_ratio_results.txt"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load ETH-USD and BTC-USD daily closes from yfinance, cache to CSV."""
    if CACHE_FILE.exists():
        print(f"  [cache] Loading from {CACHE_FILE}")
        df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df

    print("  [download] Fetching BTC-USD and ETH-USD daily from yfinance...")
    import yfinance as yf

    btc = yf.Ticker("BTC-USD").history(start=FETCH_START, end=END_DATE, interval="1d")
    eth = yf.Ticker("ETH-USD").history(start=FETCH_START, end=END_DATE, interval="1d")

    if btc.empty or eth.empty:
        print("ERROR: yfinance returned empty data", file=sys.stderr)
        sys.exit(1)

    btc.index = pd.to_datetime(btc.index).tz_localize(None)
    eth.index = pd.to_datetime(eth.index).tz_localize(None)

    df = pd.DataFrame({
        "btc_close": btc["Close"],
        "eth_close": eth["Close"],
    }).dropna()

    df.to_csv(CACHE_FILE)
    print(f"  [cache] Saved to {CACHE_FILE} ({len(df)} rows)")
    return df


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signal_days(ratio: pd.Series, cooldown_days: int = COOLDOWN_DAYS) -> pd.DatetimeIndex:
    """
    Signal: ratio[t] < 10th-percentile of the ratio over the past ROLLING_WINDOW days.
    Percentile is shifted by 1 day to avoid lookahead bias.
    Cooldown applied to avoid signal clusters.
    """
    # Percentile computed on rolling window, shifted 1 day forward
    rolling_pct = ratio.rolling(ROLLING_WINDOW).quantile(SIGNAL_PCT).shift(1)
    signal_mask = ratio < rolling_pct

    candidates = ratio[signal_mask].index
    signals = []
    last_signal = None
    for date in sorted(candidates):
        if last_signal is None or (date - last_signal).days >= cooldown_days:
            signals.append(date)
            last_signal = date
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Statistics (same pattern as btc_crash_sensitivity.py)
# ---------------------------------------------------------------------------

def forward_outperformance(
    eth_prices: pd.Series,
    btc_prices: pd.Series,
    signal_date,
    horizon_days: int,
) -> float | None:
    """H-day forward return of ETH minus H-day forward return of BTC."""
    try:
        idx = eth_prices.index.get_loc(signal_date)
    except KeyError:
        return None
    target_idx = idx + horizon_days
    if target_idx >= len(eth_prices):
        return None
    eth_ret = (eth_prices.iloc[target_idx] - eth_prices.iloc[idx]) / eth_prices.iloc[idx]
    btc_ret = (btc_prices.iloc[target_idx] - btc_prices.iloc[idx]) / btc_prices.iloc[idx]
    return float(eth_ret - btc_ret)


def bootstrap_mean_ci(returns: np.ndarray, n: int = N_BOOTSTRAP, alpha: float = 0.05) -> tuple[float, float]:
    """Bootstrap 95% CI for the mean."""
    if len(returns) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(42)
    means = np.array([
        rng.choice(returns, size=len(returns), replace=True).mean()
        for _ in range(n)
    ])
    lo = float(np.percentile(means, alpha / 2 * 100))
    hi = float(np.percentile(means, (1 - alpha / 2) * 100))
    return lo, hi


def analyse_horizon(
    eth_prices: pd.Series,
    btc_prices: pd.Series,
    signal_dates: pd.DatetimeIndex,
    horizon_days: int,
    split_date: str,
) -> dict:
    """Full analysis for a given horizon."""
    fwd = [forward_outperformance(eth_prices, btc_prices, d, horizon_days) for d in signal_dates]
    fwd = [r for r in fwd if r is not None]

    signal_set = set(signal_dates)
    all_dates = [d for d in eth_prices.index if d not in signal_set]
    baseline_fwd = [forward_outperformance(eth_prices, btc_prices, d, horizon_days) for d in all_dates]
    baseline_fwd = [r for r in baseline_fwd if r is not None]

    split = pd.Timestamp(split_date)
    is_signal = [d for d in signal_dates if d < split]
    oos_signal = [d for d in signal_dates if d >= split]

    is_fwd = [forward_outperformance(eth_prices, btc_prices, d, horizon_days) for d in is_signal]
    is_fwd = [r for r in is_fwd if r is not None]
    oos_fwd = [forward_outperformance(eth_prices, btc_prices, d, horizon_days) for d in oos_signal]
    oos_fwd = [r for r in oos_fwd if r is not None]

    n_total = len(fwd)
    mean_ret = float(np.mean(fwd)) if fwd else float("nan")
    baseline_mean = float(np.mean(baseline_fwd)) if baseline_fwd else float("nan")
    delta = mean_ret - baseline_mean if not (np.isnan(mean_ret) or np.isnan(baseline_mean)) else float("nan")
    win_rate = float(np.mean([r > 0 for r in fwd])) if fwd else float("nan")

    ci_lo, ci_hi = bootstrap_mean_ci(np.array(fwd)) if fwd else (float("nan"), float("nan"))

    p_value = float("nan")
    if len(fwd) >= 3 and len(baseline_fwd) >= 3:
        _, p_value = stats.mannwhitneyu(fwd, baseline_fwd, alternative="greater")

    is_mean = float(np.mean(is_fwd)) if is_fwd else float("nan")
    oos_mean = float(np.mean(oos_fwd)) if oos_fwd else float("nan")

    return {
        "n_total": n_total,
        "n_is": len(is_fwd),
        "n_oos": len(oos_fwd),
        "mean_ret": mean_ret,
        "baseline_mean": baseline_mean,
        "delta": delta,
        "win_rate": win_rate,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_value": p_value,
        "is_mean": is_mean,
        "oos_mean": oos_mean,
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def verdict(results_by_horizon: dict[int, dict]) -> str:
    h7  = results_by_horizon.get(7, {})
    h30 = results_by_horizon.get(30, {})

    n = h7.get("n_total", 0)
    delta7  = h7.get("delta", float("nan"))
    delta30 = h30.get("delta", float("nan"))
    p7  = h7.get("p_value", float("nan"))
    oos7  = h7.get("oos_mean", float("nan"))
    oos30 = h30.get("oos_mean", float("nan"))

    if n < 3:
        return "DISCARD (N<3)"
    if np.isnan(delta7) or np.isnan(delta30):
        return "DISCARD (insufficient data)"
    if delta7 < 0 and delta30 < 0:
        return "DISCARD (negative edge)"
    if not np.isnan(oos7) and oos7 < 0 and not np.isnan(oos30) and oos30 < 0:
        return "DISCARD (OOS negative)"

    is_ok = (not np.isnan(p7) and p7 < PVALUE_THRESH and delta7 > 0.03 and n >= MIN_N_RELIABLE)
    oos_positive = (not np.isnan(oos7) and oos7 > 0) or (not np.isnan(oos30) and oos30 > 0)

    if is_ok and oos_positive:
        return "RED (strong edge)"
    if delta7 > 0 and delta30 > 0:
        return "ORANGE (positive but low N or marginal p-value)"
    return "DISCARD (insufficient edge)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("ETH/BTC RATIO SIGNAL RESEARCH")
    print("=" * 65)
    print(f"  Hipotesis: ratio < pct{SIGNAL_PCT*100:.0f} rolling {ROLLING_WINDOW}d -> ETH outperforma BTC")
    print(f"  Periodo:   {START_DATE} - {END_DATE}")
    print(f"  Split:     IS <{SPLIT_DATE} / OOS >={SPLIT_DATE}")
    print(f"  Cooldown:  {COOLDOWN_DAYS} dias entre senales")
    print(f"  Bootstrap: N={N_BOOTSTRAP:,}")
    print()

    df = load_data()
    df = df[(df.index >= START_DATE) & (df.index < END_DATE)]
    df = df.dropna()

    eth_prices = df["eth_close"]
    btc_prices = df["btc_close"]
    ratio = eth_prices / btc_prices

    print(f"  Ratio ETH/BTC stats (periodo completo):")
    print(f"    min={ratio.min():.5f}  max={ratio.max():.5f}  "
          f"mean={ratio.mean():.5f}  current={ratio.iloc[-1]:.5f}")
    print()

    signal_dates = build_signal_days(ratio)
    split = pd.Timestamp(SPLIT_DATE)
    n_is = sum(1 for d in signal_dates if d < split)
    n_oos = sum(1 for d in signal_dates if d >= split)
    print(f"  Senales totales: {len(signal_dates)}  (IS: {n_is}, OOS: {n_oos})")
    print()

    # Analyse each horizon
    results_by_horizon: dict[int, dict] = {}
    for h in HORIZONS_D:
        results_by_horizon[h] = analyse_horizon(eth_prices, btc_prices, signal_dates, h, SPLIT_DATE)

    # Print results table
    header = (f"  {'H':>4}  {'N':>4}  {'N_IS':>5}  {'N_OOS':>5}  "
              f"{'MeanOut':>8}  {'Baseline':>8}  {'Delta':>7}  "
              f"{'CI-Lo':>7}  {'CI-Hi':>7}  {'p-val':>7}  {'WR':>5}  "
              f"{'IS':>7}  {'OOS':>7}  Verdict")
    print(header)
    print("  " + "-" * 130)

    output_lines = [
        "ETH/BTC RATIO SIGNAL RESEARCH",
        "=" * 65,
        f"  Hipotesis: ratio < pct{SIGNAL_PCT*100:.0f} rolling {ROLLING_WINDOW}d -> ETH outperforma BTC",
        f"  Periodo:   {START_DATE} - {END_DATE}",
        f"  Split:     IS <{SPLIT_DATE} / OOS >={SPLIT_DATE}",
        f"  Cooldown:  {COOLDOWN_DAYS} dias entre senales",
        f"  Senales:   {len(signal_dates)}  (IS: {n_is}, OOS: {n_oos})",
        "",
        header,
        "  " + "-" * 130,
    ]

    def fmt_pct(v: float, decimals: int = 1) -> str:
        if np.isnan(v):
            return "    -  "
        return f"{v*100:+.{decimals}f}%"

    def fmt_p(v: float) -> str:
        if np.isnan(v):
            return "   -  "
        return f"{v:.4f}"

    for h in HORIZONS_D:
        r = results_by_horizon[h]
        verd = verdict({h: r, 30: results_by_horizon.get(30, {})}) if h == 7 else ""
        line = (f"  {h:>4}d  {r['n_total']:>4}  {r['n_is']:>5}  {r['n_oos']:>5}  "
                f"{fmt_pct(r['mean_ret']):>8}  {fmt_pct(r['baseline_mean']):>8}  "
                f"{fmt_pct(r['delta']):>7}  {fmt_pct(r['ci_lo']):>7}  {fmt_pct(r['ci_hi']):>7}  "
                f"{fmt_p(r['p_value']):>7}  {fmt_pct(r['win_rate'], 0):>5}  "
                f"{fmt_pct(r['is_mean']):>7}  {fmt_pct(r['oos_mean']):>7}  {verd}")
        print(line)
        output_lines.append(line)

    print()
    output_lines.append("")

    # Overall verdict
    verd = verdict(results_by_horizon)
    r7  = results_by_horizon.get(7, {})
    r14 = results_by_horizon.get(14, {})
    r30 = results_by_horizon.get(30, {})

    conclusion_lines = [
        "CONCLUSION",
        "==========",
        f"  Senal: ETH/BTC ratio < percentil {SIGNAL_PCT*100:.0f} rolling {ROLLING_WINDOW}d (cooldown {COOLDOWN_DAYS}d)",
        f"  N total: {len(signal_dates)}  (IS: {n_is}, OOS: {n_oos})",
        "",
        f"  7d:  mean_outperf={fmt_pct(r7.get('mean_ret',float('nan'))).strip()}"
        f"  delta={fmt_pct(r7.get('delta',float('nan'))).strip()}"
        f"  p={fmt_p(r7.get('p_value',float('nan'))).strip()}"
        f"  IS={fmt_pct(r7.get('is_mean',float('nan'))).strip()}"
        f"  OOS={fmt_pct(r7.get('oos_mean',float('nan'))).strip()}",
        f"  14d: mean_outperf={fmt_pct(r14.get('mean_ret',float('nan'))).strip()}"
        f"  delta={fmt_pct(r14.get('delta',float('nan'))).strip()}"
        f"  p={fmt_p(r14.get('p_value',float('nan'))).strip()}",
        f"  30d: mean_outperf={fmt_pct(r30.get('mean_ret',float('nan'))).strip()}"
        f"  delta={fmt_pct(r30.get('delta',float('nan'))).strip()}"
        f"  p={fmt_p(r30.get('p_value',float('nan'))).strip()}"
        f"  IS={fmt_pct(r30.get('is_mean',float('nan'))).strip()}"
        f"  OOS={fmt_pct(r30.get('oos_mean',float('nan'))).strip()}",
        "",
        f"  VERDICT: {verd}",
    ]

    if "DISCARD" in verd:
        conclusion_lines.append("  ACCION: No implementar como senal de produccion.")
    elif "ORANGE" in verd:
        conclusion_lines.append("  ACCION: Evidence debil. No implementar hasta N mayor o siguiente ciclo.")
    else:
        conclusion_lines.append(
            "  ACCION: Senal valida. Considerar como alerta ETH orange (si OOS confirma en proximo ciclo)."
        )

    for line in conclusion_lines:
        print(line)
    output_lines.extend(conclusion_lines)

    results_text = "\n".join(output_lines)
    RESULTS_FILE.write_text(results_text, encoding="utf-8")
    print(f"\n  Resultados guardados en {RESULTS_FILE}")


if __name__ == "__main__":
    main()
