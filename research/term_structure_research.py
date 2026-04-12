"""term_structure_research.py
============================
Research R5 (Fase 3): BTC 3m futures term structure como senal.

Hipotesis
---------
- Contango extremo (basis 3m anualizado > +10%/ano): apalancamiento caliente;
  BTC tiende a corregir en los siguientes 7-21 dias.
- Backwardation (basis anualizado < 0%): capitulacion (vendedores forzados);
  suele preceder rebotes en 7-21 dias.

Datos
-----
- Spot: yfinance BTC-USD daily (local-only, misma fuente que resto de research).
- Futuros: Deribit public API, contratos quarterly BTC-{DDMMMYY}.
  * Endpoint: /public/get_tradingview_chart_data (sin API key).
  * Se filtran barras con volume>0 para descartar padding post-expiry.
  * Para cada dia se selecciona el contrato con DTE mas cercano a 90d
    dentro de [60, 120] dias.
- Basis anualizado = (future/spot - 1) * 365/DTE.

Metodologia (identica a R3/R4 de Fase 3 / plantilla eth_btc_ratio)
------------------------------------------------------------------
- Split IS/OOS: IS <2024-03-01 / OOS >=2024-03-01 (~70/30 sobre los dias
  con data de futuros disponible).
- Cooldown 7d entre senales (evitar clusters).
- Horizontes forward: 7d / 14d / 21d / 30d.
- Bootstrap 95% CI (N=10.000) + Mann-Whitney U.
- Veredicto RED si p<0.05 IS + delta positivo + OOS positivo + N_OOS>=10.

Run
---
    python research/term_structure_research.py

Output
------
- Cache:    data/research_cache/btc_term_structure.csv
- Resumen:  data/research_cache/term_structure_results.txt
"""

from __future__ import annotations

import calendar
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FETCH_START = "2019-12-01"
START_DATE  = "2020-06-01"
END_DATE    = "2026-04-01"
SPLIT_DATE  = "2024-03-01"

QUARTERLY_MONTHS = [3, 6, 9, 12]
MONTH_ABBR = ["", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

DTE_MIN, DTE_MAX, DTE_TARGET = 60, 120, 90

CONTANGO_HIGH      = 0.10   # +10%/yr annualized
BACKWARDATION_LOW  = 0.00   # 0%/yr annualized

COOLDOWN_DAYS = 7
HORIZONS_D    = [7, 14, 21, 30]

N_BOOTSTRAP    = 10_000
PVALUE_THRESH  = 0.05
MIN_N_RELIABLE = 5

CACHE_DIR    = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE   = CACHE_DIR / "btc_term_structure.csv"
RESULTS_FILE = CACHE_DIR / "term_structure_results.txt"

DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"


# ---------------------------------------------------------------------------
# Deribit quarterly futures fetch
# ---------------------------------------------------------------------------

def _last_friday(year: int, month: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    d = datetime(year, month, last_day, tzinfo=timezone.utc)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def _deribit_name(expiry: datetime) -> str:
    return f"BTC-{expiry.day}{MONTH_ABBR[expiry.month]}{expiry.year % 100:02d}"


def _iter_quarterlies(start: datetime, end: datetime) -> Iterable[datetime]:
    for year in range(start.year - 1, end.year + 2):
        for m in QUARTERLY_MONTHS:
            f = _last_friday(year, m)
            if start <= f <= end:
                yield f


def _fetch_deribit_contract(name: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    r = requests.get(
        DERIBIT_URL,
        params={
            "instrument_name": name,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": "1D",
        },
        timeout=30,
    )
    r.raise_for_status()
    res = r.json().get("result", {})
    ticks   = res.get("ticks", [])
    closes  = res.get("close", [])
    volumes = res.get("volume", [])
    if not ticks:
        return pd.DataFrame()
    dates = pd.to_datetime(ticks, unit="ms").normalize()
    df = pd.DataFrame({"date": dates, "future": closes, "volume": volumes})
    df = df[df["volume"] > 0]
    return df[["date", "future"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load or build the daily (spot, future, basis_ann) series."""
    if CACHE_FILE.exists():
        print(f"  [cache] Loading from {CACHE_FILE}")
        df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df

    print("  [download] Fetching BTC-USD spot from yfinance...")
    import yfinance as yf

    btc = yf.Ticker("BTC-USD").history(start=FETCH_START, end=END_DATE, interval="1d")
    if btc.empty:
        print("ERROR: yfinance returned empty BTC-USD data", file=sys.stderr)
        sys.exit(1)
    btc.index = pd.to_datetime(btc.index).tz_localize(None).normalize()
    spot = btc[["Close"]].rename(columns={"Close": "spot"})

    start_dt = datetime.fromisoformat(FETCH_START).replace(tzinfo=timezone.utc)
    end_dt   = datetime.fromisoformat(END_DATE).replace(tzinfo=timezone.utc)

    print("  [download] Fetching Deribit quarterly futures...")
    frames: list[pd.DataFrame] = []
    for expiry in _iter_quarterlies(start_dt, end_dt):
        name = _deribit_name(expiry)
        s_ms = int((expiry - timedelta(days=160)).timestamp() * 1000)
        e_ms = int(expiry.timestamp() * 1000)
        try:
            df_f = _fetch_deribit_contract(name, s_ms, e_ms)
        except requests.RequestException as exc:
            print(f"    {name}: ERROR {exc}")
            continue
        if df_f.empty:
            print(f"    {name}: no data")
            continue
        df_f["expiry"] = pd.Timestamp(expiry.date())
        frames.append(df_f)
        print(f"    {name}: {len(df_f)} bars")
        time.sleep(0.1)

    if not frames:
        print("ERROR: no quarterly futures data fetched from Deribit", file=sys.stderr)
        sys.exit(1)

    fdf = pd.concat(frames, ignore_index=True)
    fdf["dte"] = (fdf["expiry"] - fdf["date"]).dt.days
    fdf = fdf[(fdf["dte"] >= DTE_MIN) & (fdf["dte"] <= DTE_MAX)]

    fdf["dte_dist"] = (fdf["dte"] - DTE_TARGET).abs()
    fdf = fdf.sort_values(["date", "dte_dist"]).drop_duplicates("date", keep="first")
    fdf = fdf.drop(columns=["dte_dist"]).set_index("date")

    merged = fdf.join(spot, how="inner")
    merged["basis_ann"] = (merged["future"] / merged["spot"] - 1.0) * (365.0 / merged["dte"])
    merged = merged[["spot", "future", "expiry", "dte", "basis_ann"]].sort_index()

    merged.to_csv(CACHE_FILE)
    print(f"  [cache] Saved to {CACHE_FILE} ({len(merged)} rows)")
    return merged


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def bootstrap_mean_ci(x: np.ndarray, n: int = N_BOOTSTRAP, alpha: float = 0.05) -> tuple[float, float]:
    if len(x) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    means = np.array([rng.choice(x, size=len(x), replace=True).mean() for _ in range(n)])
    return (
        float(np.percentile(means, alpha / 2 * 100)),
        float(np.percentile(means, (1 - alpha / 2) * 100)),
    )


def forward_return(prices: pd.Series, date, horizon: int) -> float | None:
    try:
        idx = prices.index.get_loc(date)
    except KeyError:
        return None
    target = idx + horizon
    if target >= len(prices):
        return None
    return float((prices.iloc[target] - prices.iloc[idx]) / prices.iloc[idx])


def build_signal_days(basis: pd.Series, predicate, cooldown: int = COOLDOWN_DAYS) -> pd.DatetimeIndex:
    mask = predicate(basis)
    candidates = basis[mask].index
    signals: list = []
    last = None
    for d in sorted(candidates):
        if last is None or (d - last).days >= cooldown:
            signals.append(d)
            last = d
    return pd.DatetimeIndex(signals)


def analyse(
    prices: pd.Series,
    signal_dates: pd.DatetimeIndex,
    baseline_dates: pd.DatetimeIndex,
    horizon: int,
    direction: str,
    split_date: str,
) -> dict:
    sig_ret = [forward_return(prices, d, horizon) for d in signal_dates]
    sig_ret = [r for r in sig_ret if r is not None]
    base_ret = [forward_return(prices, d, horizon) for d in baseline_dates]
    base_ret = [r for r in base_ret if r is not None]

    sig_mean  = float(np.mean(sig_ret))  if sig_ret  else float("nan")
    base_mean = float(np.mean(base_ret)) if base_ret else float("nan")

    if direction == "long":
        delta = sig_mean - base_mean
        alt = "greater"
        win_mask = [r > 0 for r in sig_ret]
    else:  # short: signal-day returns expected LOWER than baseline
        delta = base_mean - sig_mean
        alt = "less"
        win_mask = [r < 0 for r in sig_ret]

    win_rate = float(np.mean(win_mask)) if win_mask else float("nan")
    ci_lo, ci_hi = bootstrap_mean_ci(np.array(sig_ret)) if sig_ret else (float("nan"), float("nan"))

    p_value = float("nan")
    if len(sig_ret) >= 3 and len(base_ret) >= 3:
        try:
            _, p_value = stats.mannwhitneyu(sig_ret, base_ret, alternative=alt)
        except ValueError:
            pass

    split = pd.Timestamp(split_date)
    is_ret  = [forward_return(prices, d, horizon) for d in signal_dates if d <  split]
    oos_ret = [forward_return(prices, d, horizon) for d in signal_dates if d >= split]
    is_ret  = [r for r in is_ret  if r is not None]
    oos_ret = [r for r in oos_ret if r is not None]

    # Report IS/OOS as "edge" (positive = signal worked in that direction)
    if direction == "long":
        is_mean  = float(np.mean(is_ret))  if is_ret  else float("nan")
        oos_mean = float(np.mean(oos_ret)) if oos_ret else float("nan")
    else:
        is_mean  = float(-np.mean(is_ret))  if is_ret  else float("nan")
        oos_mean = float(-np.mean(oos_ret)) if oos_ret else float("nan")

    return {
        "n_total":   len(sig_ret),
        "n_is":      len(is_ret),
        "n_oos":     len(oos_ret),
        "sig_mean":  sig_mean,
        "base_mean": base_mean,
        "delta":     delta,
        "win_rate":  win_rate,
        "ci_lo":     ci_lo,
        "ci_hi":     ci_hi,
        "p_value":   p_value,
        "is_mean":   is_mean,
        "oos_mean":  oos_mean,
    }


def verdict(results: dict[int, dict]) -> str:
    h7  = results.get(7, {})
    h14 = results.get(14, {})

    n       = h7.get("n_total", 0)
    n_oos14 = h14.get("n_oos", 0)
    delta7  = h7.get("delta", float("nan"))
    delta14 = h14.get("delta", float("nan"))
    p14     = h14.get("p_value", float("nan"))
    oos7    = h7.get("oos_mean", float("nan"))
    oos14   = h14.get("oos_mean", float("nan"))

    if n < 3:
        return "DISCARD (N<3)"
    if np.isnan(delta7) or np.isnan(delta14):
        return "DISCARD (insufficient data)"
    if delta7 < 0 and delta14 < 0:
        return "DISCARD (negative edge)"
    if not np.isnan(oos7) and not np.isnan(oos14) and oos7 < 0 and oos14 < 0:
        return "DISCARD (OOS negative)"

    is_ok = (
        not np.isnan(p14)
        and p14 < PVALUE_THRESH
        and delta14 > 0.02
        and n >= MIN_N_RELIABLE
    )
    oos_positive = (
        (not np.isnan(oos7) and oos7 > 0)
        or (not np.isnan(oos14) and oos14 > 0)
    )
    oos_enough = n_oos14 >= 10

    if is_ok and oos_positive and oos_enough:
        return "RED (strong edge)"
    if is_ok and oos_positive and not oos_enough:
        return f"ORANGE (edge IS ok but N_OOS={n_oos14} < 10)"
    if delta7 > 0 and delta14 > 0:
        return "ORANGE (positive but marginal)"
    return "DISCARD (insufficient edge)"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_pct(v: float, decimals: int = 1) -> str:
    if np.isnan(v):
        return "    -  "
    return f"{v*100:+.{decimals}f}%"


def fmt_p(v: float) -> str:
    if np.isnan(v):
        return "   -  "
    return f"{v:.4f}"


# ---------------------------------------------------------------------------
# Signal runner
# ---------------------------------------------------------------------------

def run_signal(
    prices: pd.Series,
    basis: pd.Series,
    direction: str,
    predicate,
    label: str,
    split_date: str,
    output_lines: list[str],
) -> tuple[str, dict[int, dict]]:
    signal_dates = build_signal_days(basis, predicate)
    signal_set = set(signal_dates)
    baseline_dates = pd.DatetimeIndex([d for d in basis.index if d not in signal_set])

    split = pd.Timestamp(split_date)
    n_is_sig  = sum(1 for d in signal_dates if d <  split)
    n_oos_sig = sum(1 for d in signal_dates if d >= split)

    print()
    print(f"  === {label} ===")
    print(f"  Senales totales: {len(signal_dates)} (IS: {n_is_sig}, OOS: {n_oos_sig})")
    output_lines.append("")
    output_lines.append(f"=== {label} ===")
    output_lines.append(f"Senales totales: {len(signal_dates)} (IS: {n_is_sig}, OOS: {n_oos_sig})")

    header = (
        f"  {'H':>4}  {'N':>4}  {'N_IS':>5}  {'N_OOS':>5}  "
        f"{'SigRet':>8}  {'BaseRet':>8}  {'Delta':>7}  "
        f"{'CI-Lo':>7}  {'CI-Hi':>7}  {'p-val':>7}  {'WR':>5}  "
        f"{'IS':>7}  {'OOS':>7}  Verdict"
    )
    print(header)
    print("  " + "-" * 130)
    output_lines.append(header)
    output_lines.append("  " + "-" * 130)

    results: dict[int, dict] = {}
    for h in HORIZONS_D:
        results[h] = analyse(prices, signal_dates, baseline_dates, h, direction, split_date)

    verd = verdict(results)

    for h in HORIZONS_D:
        r = results[h]
        v = verd if h == 14 else ""
        line = (
            f"  {h:>4}d  {r['n_total']:>4}  {r['n_is']:>5}  {r['n_oos']:>5}  "
            f"{fmt_pct(r['sig_mean']):>8}  {fmt_pct(r['base_mean']):>8}  "
            f"{fmt_pct(r['delta']):>7}  {fmt_pct(r['ci_lo']):>7}  {fmt_pct(r['ci_hi']):>7}  "
            f"{fmt_p(r['p_value']):>7}  {fmt_pct(r['win_rate'], 0):>5}  "
            f"{fmt_pct(r['is_mean']):>7}  {fmt_pct(r['oos_mean']):>7}  {v}"
        )
        print(line)
        output_lines.append(line)

    return verd, results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("BTC TERM STRUCTURE (3m BASIS) SIGNAL RESEARCH")
    print("=" * 65)
    print("  Fuentes: yfinance BTC-USD (spot) + Deribit quarterly futures")
    print(f"  Periodo: {START_DATE} - {END_DATE}")
    print(f"  Split:   IS <{SPLIT_DATE} / OOS >={SPLIT_DATE}")
    print(f"  Basis:   (future/spot - 1) * 365/DTE, DTE en [{DTE_MIN},{DTE_MAX}], target {DTE_TARGET}d")
    print(f"  Cooldown: {COOLDOWN_DAYS} dias entre senales")
    print(f"  Bootstrap: N={N_BOOTSTRAP:,}")
    print()

    df = load_data()
    df = df[(df.index >= START_DATE) & (df.index < END_DATE)]
    df = df.dropna()

    print(f"  Datos disponibles: {len(df)} dias con basis 3m")
    print(
        f"  Basis stats: min={df['basis_ann'].min():.3f}  "
        f"max={df['basis_ann'].max():.3f}  "
        f"mean={df['basis_ann'].mean():.3f}  "
        f"p95={df['basis_ann'].quantile(0.95):.3f}  "
        f"p05={df['basis_ann'].quantile(0.05):.3f}"
    )

    spot_prices = df["spot"]
    basis = df["basis_ann"]

    output_lines = [
        "BTC TERM STRUCTURE (3m BASIS) SIGNAL RESEARCH",
        "=" * 65,
        "  Fuentes: yfinance BTC-USD (spot) + Deribit quarterly futures",
        f"  Periodo: {START_DATE} - {END_DATE}",
        f"  Split:   IS <{SPLIT_DATE} / OOS >={SPLIT_DATE}",
        f"  Datos disponibles: {len(df)} dias",
        f"  Basis stats: min={df['basis_ann'].min():.3f}  "
        f"max={df['basis_ann'].max():.3f}  mean={df['basis_ann'].mean():.3f}  "
        f"p95={df['basis_ann'].quantile(0.95):.3f}  "
        f"p05={df['basis_ann'].quantile(0.05):.3f}",
    ]

    short_label = f"SHORT: basis_ann > +{CONTANGO_HIGH*100:.0f}%/yr (contango alto)"
    verd_short, _ = run_signal(
        spot_prices, basis, "short",
        lambda b: b > CONTANGO_HIGH, short_label,
        SPLIT_DATE, output_lines,
    )

    long_label = f"LONG: basis_ann < {BACKWARDATION_LOW*100:.0f}%/yr (backwardation)"
    verd_long, _ = run_signal(
        spot_prices, basis, "long",
        lambda b: b < BACKWARDATION_LOW, long_label,
        SPLIT_DATE, output_lines,
    )

    print()
    print("CONCLUSION")
    print("==========")
    print(f"  SHORT (basis > +{CONTANGO_HIGH*100:.0f}%): {verd_short}")
    print(f"  LONG  (basis < 0%):               {verd_long}")

    output_lines.append("")
    output_lines.append("CONCLUSION")
    output_lines.append("==========")
    output_lines.append(f"  SHORT (basis > +{CONTANGO_HIGH*100:.0f}%): {verd_short}")
    output_lines.append(f"  LONG  (basis < 0%):               {verd_long}")
    output_lines.append("")

    if "RED" in verd_short or "RED" in verd_long:
        output_lines.append("  ACCION: Candidato. Requiere aprobacion explicita antes de implementar alerta.")
    else:
        output_lines.append("  ACCION: No implementar como senal de produccion.")

    RESULTS_FILE.write_text("\n".join(output_lines), encoding="utf-8")
    print()
    print(f"  Resultados guardados en {RESULTS_FILE}")


if __name__ == "__main__":
    main()
