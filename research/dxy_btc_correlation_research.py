"""dxy_btc_correlation_research.py
====================================
Research R4 (Fase 3): DXY lead/lag signal for BTC.

Hypothesis
----------
Sharp moves in the US Dollar Index (DXY) anticipate BTC returns with a
1-5 day lag, with inverse correlation. The tested BUY signal:

    DXY drops >= threshold over W days => BTC rises in the next H days.

Economic logic: BTC behaves as an inverse-USD risk asset. A weakening
dollar (expansive policy, loss of confidence) channels capital into
alternative assets including crypto.

Parametrizations tested (exactly two, no significance fishing)
--------------------------------------------------------------
- Signal A: DXY_5d change <= -2.0%   forward horizon 7d  (also reported at 3/14/30d)
- Signal B: DXY_10d change <= -1.5%  forward horizon 14d (also reported at 3/7/30d)

Methodology
-----------
- IS : 2015-01-01 - 2022-01-01  (~70%)
- OOS: 2022-01-01 - 2026-04-01  (~30%)
- Bootstrap 95% CI for mean forward return (N=10_000)
- Mann-Whitney U test, alternative="greater"
- Cooldown: 7d between signals per parametrization
- PASS criteria: p<0.05 IS AND positive OOS AND N_OOS >= 10

Data
----
DXY: FRED DTWEXBGS (Nominal Broad US Dollar Index, daily, no API key).
BTC: yfinance BTC-USD cache (reuses data/research_cache/btc_multi_day.csv).

Run
---
    python research/dxy_btc_correlation_research.py

Output: table + CONCLUSION block. Saved to
data/research_cache/dxy_btc_correlation_results.txt
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FETCH_START = "2015-01-01"
END_DATE    = "2026-04-01"
IS_END      = "2022-01-01"
OOS_START   = "2022-01-01"

# Exactly two parametrizations.
# Each entry: (name, window_days, threshold_pct, primary_horizon)
PARAMS = [
    ("A", 5,  -2.0, 7),
    ("B", 10, -1.5, 14),
]
REPORT_HORIZONS = [3, 7, 14, 30]

COOLDOWN_D  = 7
N_BOOTSTRAP = 10_000
MIN_N_OOS   = 10

CACHE_DIR    = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DXY_CACHE    = CACHE_DIR / "dxy_daily.csv"
BTC_CACHE    = CACHE_DIR / "btc_multi_day.csv"
RESULTS_FILE = CACHE_DIR / "dxy_btc_correlation_results.txt"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dxy() -> pd.Series:
    """Load DXY daily close from FRED (DTWEXBGS), cache to CSV.

    Falls back to cache on network error. If neither is available, exits 1.
    """
    if DXY_CACHE.exists():
        print(f"  [cache] Loading DXY from {DXY_CACHE}")
        df = pd.read_csv(DXY_CACHE, index_col=0, parse_dates=True)
        series = df.iloc[:, 0].astype(float)
        series.index = pd.to_datetime(series.index)
        return series.dropna()

    print("  [download] Fetching FRED DTWEXBGS ...")
    try:
        r = requests.get(FRED_URL, timeout=30)
        r.raise_for_status()
    except Exception as exc:
        print(f"ERROR: FRED fetch failed ({exc}). No cache available.", file=sys.stderr)
        print("  Alternativa sugerida: Stooq dx.f (DXY futures daily).", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(StringIO(r.text))
    if df.empty or df.shape[1] < 2:
        print("ERROR: empty or malformed FRED response.", file=sys.stderr)
        sys.exit(1)
    df.columns = ["date", "dxy"]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["dxy"] = pd.to_numeric(df["dxy"], errors="coerce")
    df = df.dropna()
    df.to_csv(DXY_CACHE)
    print(f"  [cache] Saved DXY to {DXY_CACHE} ({len(df)} rows)")
    return df["dxy"]


def load_btc() -> pd.Series:
    """Load BTC-USD daily Close from cached CSV written by prior research."""
    if not BTC_CACHE.exists():
        print(f"ERROR: BTC cache not found at {BTC_CACHE}.", file=sys.stderr)
        print("  Run research/btc_multi_day_crash_research.py first to populate it.", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(BTC_CACHE, index_col=0, parse_dates=True)
    series = df["Close"].astype(float)
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signal_dates(
    dxy: pd.Series,
    window: int,
    threshold_pct: float,
) -> pd.DatetimeIndex:
    """Dates where DXY W-day change crosses below threshold, with 7d cooldown."""
    w_change = (dxy.pct_change(periods=window) * 100)
    candidates = w_change[w_change <= threshold_pct].index

    signals: list[pd.Timestamp] = []
    last = None
    for d in sorted(candidates):
        if last is not None and (d - last).days < COOLDOWN_D:
            continue
        signals.append(d)
        last = d
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def forward_return(prices: pd.Series, entry_date: pd.Timestamp, horizon_days: int) -> float | None:
    """Return H-day forward return from entry_date, aligned to next BTC trading day.

    If entry_date is not in BTC index (DXY is business days, BTC is 7d), we
    pick the first BTC date >= entry_date.
    """
    pos = prices.index.searchsorted(entry_date, side="left")
    if pos >= len(prices):
        return None
    idx = pos
    target = idx + horizon_days
    if target >= len(prices):
        return None
    entry = prices.iloc[idx]
    exit_ = prices.iloc[target]
    if entry == 0:
        return None
    return (exit_ - entry) / entry


def bootstrap_mean_ci(arr: np.ndarray) -> tuple[float, float]:
    if len(arr) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    means = np.array([
        rng.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(N_BOOTSTRAP)
    ])
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def analyse(
    btc: pd.Series,
    signal_dates: pd.DatetimeIndex,
    non_signal_dates: pd.Index,
    horizon: int,
) -> dict:
    fwd = [forward_return(btc, d, horizon) for d in signal_dates]
    fwd = [r for r in fwd if r is not None]

    baseline = [forward_return(btc, d, horizon) for d in non_signal_dates]
    baseline = [r for r in baseline if r is not None]

    is_split = pd.Timestamp(IS_END)
    is_fwd  = [forward_return(btc, d, horizon) for d in signal_dates if d < is_split]
    oos_fwd = [forward_return(btc, d, horizon) for d in signal_dates if d >= is_split]
    is_fwd  = [r for r in is_fwd  if r is not None]
    oos_fwd = [r for r in oos_fwd if r is not None]

    # IS-only p-value, as the validation test is on in-sample.
    is_baseline = [forward_return(btc, d, horizon) for d in non_signal_dates if d < is_split]
    is_baseline = [r for r in is_baseline if r is not None]

    p_value_is = float("nan")
    if len(is_fwd) >= 3 and len(is_baseline) >= 3:
        _, p_value_is = stats.mannwhitneyu(is_fwd, is_baseline, alternative="greater")

    p_value_all = float("nan")
    if len(fwd) >= 3 and len(baseline) >= 3:
        _, p_value_all = stats.mannwhitneyu(fwd, baseline, alternative="greater")

    ci_lo, ci_hi = bootstrap_mean_ci(np.array(fwd)) if fwd else (float("nan"), float("nan"))

    return {
        "n": len(fwd),
        "n_is": len(is_fwd),
        "n_oos": len(oos_fwd),
        "mean_ret": float(np.mean(fwd)) if fwd else float("nan"),
        "base_mean": float(np.mean(baseline)) if baseline else float("nan"),
        "delta": (float(np.mean(fwd)) - float(np.mean(baseline))) if fwd and baseline else float("nan"),
        "win_rate": float(np.mean([r > 0 for r in fwd])) if fwd else float("nan"),
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_value_is": p_value_is,
        "p_value_all": p_value_all,
        "is_mean": float(np.mean(is_fwd)) if is_fwd else float("nan"),
        "oos_mean": float(np.mean(oos_fwd)) if oos_fwd else float("nan"),
    }


def verdict(res_primary: dict) -> str:
    """Hard rule: p<0.05 IS AND positive OOS mean AND N_OOS >= MIN_N_OOS."""
    p_is  = res_primary.get("p_value_is", float("nan"))
    oos   = res_primary.get("oos_mean", float("nan"))
    n_oos = res_primary.get("n_oos", 0)
    delta = res_primary.get("delta", float("nan"))

    if n_oos < MIN_N_OOS:
        return f"DISCARD (N_OOS={n_oos} < {MIN_N_OOS})"
    if np.isnan(p_is) or p_is >= 0.05:
        return f"DISCARD (p_IS={p_is:.3f} >= 0.05)"
    if np.isnan(oos) or oos <= 0:
        return f"DISCARD (OOS mean={oos*100:+.1f}% not positive)"
    if np.isnan(delta) or delta <= 0:
        return "DISCARD (delta not positive)"
    return "PASS (p<0.05 IS + positive OOS + N_OOS>=10)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fp(v: float, decimals: int = 1) -> str:
    return f"{v*100:+.{decimals}f}%" if not (isinstance(v, float) and np.isnan(v)) else "  -  "


def fpv(v: float) -> str:
    return f"{v:.3f}" if not (isinstance(v, float) and np.isnan(v)) else "  -  "


def main() -> None:
    out: list[str] = []

    def log(line: str = "") -> None:
        print(line)
        out.append(line)

    log("DXY->BTC LEAD/LAG RESEARCH (Research R4)")
    log("=" * 70)
    log(f"  Period: {FETCH_START} - {END_DATE}")
    log(f"  IS: <{IS_END}  /  OOS: >={OOS_START}")
    log(f"  Params: A (DXY_5d <= -2%, H=7d)  |  B (DXY_10d <= -1.5%, H=14d)")
    log(f"  Cooldown: {COOLDOWN_D}d  |  Bootstrap: N={N_BOOTSTRAP:,}")
    log(f"  PASS rule: p_IS<0.05 AND OOS>0 AND N_OOS>={MIN_N_OOS}")
    log("")

    dxy = load_dxy()
    btc = load_btc()

    dxy = dxy[(dxy.index >= FETCH_START) & (dxy.index < END_DATE)]
    btc = btc[(btc.index >= FETCH_START) & (btc.index < END_DATE)]

    log(f"  DXY rows: {len(dxy)}   BTC rows: {len(btc)}")
    log(f"  DXY range: {dxy.index.min().date()} .. {dxy.index.max().date()}")
    log(f"  BTC range: {btc.index.min().date()} .. {btc.index.max().date()}")
    log("")

    # Baseline: all DXY business days (each row is a potential observation day).
    all_dates = dxy.index

    results: dict[str, dict] = {}

    for name, W, thr, primary_h in PARAMS:
        signal_dates = build_signal_dates(dxy, W, thr)
        signal_set = set(signal_dates)
        non_signal = all_dates.difference(signal_set)

        by_h: dict[int, dict] = {}
        for h in REPORT_HORIZONS:
            by_h[h] = analyse(btc, signal_dates, non_signal, h)

        results[name] = {
            "W": W,
            "threshold": thr,
            "primary_h": primary_h,
            "by_h": by_h,
            "n_signals": len(signal_dates),
            "verdict": verdict(by_h[primary_h]),
        }

    # -----------------------------------------------------------------------
    # Report each parametrization
    # -----------------------------------------------------------------------

    for name in ("A", "B"):
        r = results[name]
        log(f"Signal {name}: DXY_{r['W']}d <= {r['threshold']:.1f}%   (primary H={r['primary_h']}d)")
        log("-" * 70)
        log(f"  Total signals: {r['n_signals']}")
        header = (f"  {'H':>3}d  {'N':>4}  {'N_IS':>4}  {'N_OOS':>5}  "
                  f"{'delta':>7}  {'p_IS':>6}  {'p_all':>6}  "
                  f"{'WR':>6}  {'CI95':>18}  {'IS':>7}  {'OOS':>7}")
        log(header)
        log("  " + "-" * 96)
        for h in REPORT_HORIZONS:
            res = r["by_h"][h]
            ci = f"[{fp(res['ci_lo'])},{fp(res['ci_hi'])}]"
            marker = "  <<"  if h == r["primary_h"] else ""
            line = (f"  {h:>3}d  {res['n']:>4}  {res['n_is']:>4}  {res['n_oos']:>5}  "
                    f"{fp(res['delta']):>7}  {fpv(res['p_value_is']):>6}  {fpv(res['p_value_all']):>6}  "
                    f"{fp(res['win_rate']):>6}  {ci:>18}  "
                    f"{fp(res['is_mean']):>7}  {fp(res['oos_mean']):>7}{marker}")
            log(line)
        log("")
        log(f"  VERDICT ({name}): {r['verdict']}")
        log("")

    # -----------------------------------------------------------------------
    # Overall conclusion
    # -----------------------------------------------------------------------

    log("CONCLUSION")
    log("==========")
    passed = [n for n, r in results.items() if r["verdict"].startswith("PASS")]
    if passed:
        log(f"  PASSED: {', '.join(passed)}")
        for n in passed:
            r = results[n]
            res = r["by_h"][r["primary_h"]]
            log(f"    Signal {n}: DXY_{r['W']}d <= {r['threshold']:.1f}%  H={r['primary_h']}d  "
                f"N={res['n']}  N_OOS={res['n_oos']}  "
                f"delta={fp(res['delta'])}  p_IS={fpv(res['p_value_is'])}  "
                f"OOS={fp(res['oos_mean'])}")
        log("")
        log("  ACCION: Candidato a alerta (Playbook A). Requiere revision manual antes de")
        log("          modificar discord_bot.py (no hacerlo automaticamente desde este script).")
    else:
        log("  Neither Signal A nor Signal B passed the PASS rule.")
        log("  VERDICT: DISCARD -- DXY lead/lag does not provide actionable buy edge")
        log("           under the methodology (p<0.05 IS AND OOS>0 AND N_OOS>=10).")
        log("  ACCION: No implementar. Archivar en RESEARCH_ARCHIVE.md como senal descartada.")

    RESULTS_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
