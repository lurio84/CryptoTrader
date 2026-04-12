"""btc_multi_day_crash_research.py
==================================
Research 11: BTC multi-day crash as a complementary buy signal.

Hypothesis
----------
The existing production alert detects single-day crashes (24h > -15%).
A distributed crash (e.g. -20% over 5 days) may not trigger the 24h alert.
This script tests whether multi-day crash signals provide edge BEYOND what
the 24h alert already captures.

Signal construction
-------------------
- signal(W, N): W-day return = (close[t] / close[t-W] - 1) * 100 < N
- Windows W: 3, 5, 7 calendar days
- Thresholds N: -10%, -15%, -20%, -25%
- Exclusion: skip signal if the 24h return (< -15%) fired in the last 3 days
  (to measure ADDITIONAL edge beyond the existing alert)
- Cooldown: 7 days minimum between signals per (W, N) combination

Stats
-----
- IS: 2015-01-01 to 2022-01-01 (~70%)
- OOS: 2022-01-01 to 2026-04-01 (~30%)
- Bootstrap 95% CI (N=10_000)
- Mann-Whitney U test (alternative="greater")
- Forward returns: 7d, 14d, 30d

Run
---
    python research/btc_multi_day_crash_research.py

Output
------
Results table + CONCLUSION block.
Saves to data/research_cache/btc_multi_day_results.txt
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

FETCH_START = "2015-01-01"
END_DATE    = "2026-04-01"
IS_END      = "2022-01-01"   # IS/OOS split
OOS_START   = "2022-01-01"

WINDOWS     = [3, 5, 7]
THRESHOLDS  = [-10, -15, -20, -25]   # percentages (negative = down)
HORIZONS_D  = [7, 14, 30]
COOLDOWN_D  = 7    # minimum days between signals per (W, N)
EXCLUDE_24H_DAYS = 3  # exclude if 24h alert fired within this many days

CRASH_24H_THRESHOLD = -0.15  # production value

N_BOOTSTRAP = 10_000
MIN_N       = 3

CACHE_DIR   = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BTC_CACHE   = CACHE_DIR / "btc_multi_day.csv"
RESULTS_FILE = CACHE_DIR / "btc_multi_day_results.txt"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_btc_daily() -> pd.DataFrame:
    """Load BTC-USD daily OHLCV from yfinance, cache to CSV."""
    if BTC_CACHE.exists():
        print(f"  [cache] Loading BTC daily from {BTC_CACHE}")
        df = pd.read_csv(BTC_CACHE, index_col=0, parse_dates=True)
        return df

    print("  [download] Fetching BTC-USD daily from yfinance...")
    import yfinance as yf
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=FETCH_START, end=END_DATE, interval="1d")
    if df.empty:
        print("ERROR: yfinance returned empty data for BTC-USD", file=sys.stderr)
        sys.exit(1)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.to_csv(BTC_CACHE)
    print(f"  [cache] Saved to {BTC_CACHE} ({len(df)} rows)")
    return df


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_24h_crash_dates(returns_1d: pd.Series) -> set:
    """Set of dates where 24h return < production threshold."""
    return set(returns_1d[returns_1d < CRASH_24H_THRESHOLD].index)


def build_multiday_signals(
    prices: pd.Series,
    crash_24h_dates: set,
    window: int,
    threshold_pct: float,
) -> pd.DatetimeIndex:
    """Build signal dates for a given (W, N) pair, excluding 24h overlaps."""
    w_returns = prices.pct_change(periods=window) * 100  # W-day return in %

    candidates = w_returns[w_returns < threshold_pct].index
    signals = []
    last_signal = None

    for date in sorted(candidates):
        # Cooldown filter
        if last_signal is not None and (date - last_signal).days < COOLDOWN_D:
            continue

        # Exclusion: skip if 24h crash alert fired within last EXCLUDE_24H_DAYS
        overlaps = any(
            0 <= (date - crash_d).days <= EXCLUDE_24H_DAYS
            for crash_d in crash_24h_dates
            if isinstance(crash_d, pd.Timestamp)
        )
        if overlaps:
            continue

        signals.append(date)
        last_signal = date

    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Statistics (same as btc_crash_sensitivity.py)
# ---------------------------------------------------------------------------

def forward_return(prices: pd.Series, signal_date, horizon_days: int) -> float | None:
    """H-day forward return from signal_date close."""
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
    return (exit_ - entry) / entry


def bootstrap_mean_ci(arr: np.ndarray) -> tuple[float, float]:
    """Bootstrap 95% CI for the mean."""
    if len(arr) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    means = np.array([
        rng.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(N_BOOTSTRAP)
    ])
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def analyse(
    prices: pd.Series,
    signal_dates: pd.DatetimeIndex,
    non_signal_dates: pd.Index,
    horizon: int,
) -> dict:
    """Compute stats for signal vs baseline at given horizon."""
    fwd = [forward_return(prices, d, horizon) for d in signal_dates]
    fwd = [r for r in fwd if r is not None]

    baseline = [forward_return(prices, d, horizon) for d in non_signal_dates]
    baseline = [r for r in baseline if r is not None]

    is_split = pd.Timestamp(IS_END)
    is_fwd  = [forward_return(prices, d, horizon) for d in signal_dates if d < is_split]
    oos_fwd = [forward_return(prices, d, horizon) for d in signal_dates if d >= is_split]
    is_fwd  = [r for r in is_fwd  if r is not None]
    oos_fwd = [r for r in oos_fwd if r is not None]

    n = len(fwd)
    mean_ret  = float(np.mean(fwd)) if fwd else float("nan")
    base_mean = float(np.mean(baseline)) if baseline else float("nan")
    delta     = mean_ret - base_mean if not (np.isnan(mean_ret) or np.isnan(base_mean)) else float("nan")
    win_rate  = float(np.mean([r > 0 for r in fwd])) if fwd else float("nan")
    ci_lo, ci_hi = bootstrap_mean_ci(np.array(fwd)) if fwd else (float("nan"), float("nan"))

    p_value = float("nan")
    if len(fwd) >= MIN_N and len(baseline) >= MIN_N:
        _, p_value = stats.mannwhitneyu(fwd, baseline, alternative="greater")

    return {
        "n": n,
        "n_is": len(is_fwd),
        "n_oos": len(oos_fwd),
        "mean_ret": mean_ret,
        "base_mean": base_mean,
        "delta": delta,
        "win_rate": win_rate,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_value": p_value,
        "is_mean": float(np.mean(is_fwd)) if is_fwd else float("nan"),
        "oos_mean": float(np.mean(oos_fwd)) if oos_fwd else float("nan"),
    }


def verdict_row(res_by_h: dict[int, dict]) -> str:
    """
    RED:     IS p<0.05, delta>3pp at 7d, N>=5, OOS positive
    ORANGE:  positive delta, OOS positive, but p>=0.05 or N<5
    DISCARD: negative delta or OOS negative or N<3
    """
    r7  = res_by_h.get(7, {})
    r30 = res_by_h.get(30, {})

    n       = r7.get("n", 0)
    delta7  = r7.get("delta", float("nan"))
    delta30 = r30.get("delta", float("nan"))
    p7      = r7.get("p_value", float("nan"))
    oos7    = r7.get("oos_mean", float("nan"))
    oos30   = r30.get("oos_mean", float("nan"))

    if n < MIN_N:
        return "DISCARD (N<3)"
    if np.isnan(delta7):
        return "DISCARD (insufficient data)"
    if delta7 < 0 and (np.isnan(delta30) or delta30 < 0):
        return "DISCARD (negative edge)"
    if not np.isnan(oos7) and oos7 < 0 and (np.isnan(oos30) or oos30 < 0):
        return "DISCARD (OOS negative)"

    is_strong = (not np.isnan(p7) and p7 < 0.05 and delta7 > 0.03 and n >= 5
                 and (np.isnan(oos7) or oos7 > 0))
    if is_strong:
        return "RED (strong edge)"
    if delta7 > 0 and (np.isnan(oos7) or oos7 > 0):
        return "ORANGE (positive but low N or marginal p)"
    return "DISCARD (insufficient edge)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("BTC MULTI-DAY CRASH SIGNAL RESEARCH (Research 11)")
    print("=" * 65)
    print(f"  Period: {FETCH_START} - {END_DATE}")
    print(f"  IS: <{IS_END}  /  OOS: >={OOS_START}")
    print(f"  Windows W: {WINDOWS}d  |  Thresholds: {THRESHOLDS}%")
    print(f"  Cooldown: {COOLDOWN_D}d  |  Exclude 24h overlap: {EXCLUDE_24H_DAYS}d")
    print(f"  Bootstrap: N={N_BOOTSTRAP:,}  |  Horizons: {HORIZONS_D}d")
    print()

    df = load_btc_daily()
    df = df[(df.index >= FETCH_START) & (df.index < END_DATE)].copy()
    prices = df["Close"]
    returns_1d = prices.pct_change()

    crash_24h_dates = build_24h_crash_dates(returns_1d)
    print(f"  24h crash events (< {CRASH_24H_THRESHOLD*100:.0f}%): {len(crash_24h_dates)}")
    print()

    # Pre-compute baseline (all non-signal days for any signal is approximate;
    # we use all days as baseline for simplicity, same as reference scripts)
    all_dates = prices.index

    results_table: list[dict] = []

    for W in WINDOWS:
        for N in THRESHOLDS:
            signal_dates = build_multiday_signals(prices, crash_24h_dates, W, N)
            signal_set = set(signal_dates)
            non_signal = all_dates.difference(signal_set)

            res_by_h: dict[int, dict] = {}
            for h in HORIZONS_D:
                res_by_h[h] = analyse(prices, signal_dates, non_signal, h)

            verd = verdict_row(res_by_h)
            results_table.append({
                "W": W,
                "N": N,
                "res": res_by_h,
                "verdict": verd,
            })

    # -----------------------------------------------------------------------
    # Print table
    # -----------------------------------------------------------------------

    header = (f"  {'W':>2}d {'N':>4}%  {'N_sig':>5}  {'N_IS':>4}  {'N_OOS':>5}  "
              f"{'D_7d':>7}  {'p_7d':>6}  {'WR_7':>6}  {'IS_7':>6}  {'OOS_7':>6}  "
              f"{'D_30d':>7}  {'OOS_30':>6}  Verdict")
    separator = "  " + "-" * 100

    output_lines = []
    output_lines.append("BTC MULTI-DAY CRASH SIGNAL RESEARCH (Research 11)")
    output_lines.append("=" * 65)
    output_lines.append(header)
    output_lines.append(separator)
    print(header)
    print(separator)

    def fp(v: float, decimals: int = 1) -> str:
        return f"{v*100:+.{decimals}f}%" if not np.isnan(v) else "  -  "

    def fpv(v: float) -> str:
        return f"{v:.3f}" if not np.isnan(v) else "  -  "

    for row in results_table:
        r7  = row["res"][7]
        r30 = row["res"][30]
        line = (f"  {row['W']:>2}d {row['N']:>4}%  {r7['n']:>5}  {r7['n_is']:>4}  {r7['n_oos']:>5}  "
                f"{fp(r7['delta']):>7}  {fpv(r7['p_value']):>6}  {fp(r7['win_rate']):>6}  "
                f"{fp(r7['is_mean']):>6}  {fp(r7['oos_mean']):>6}  "
                f"{fp(r30['delta']):>7}  {fp(r30['oos_mean']):>6}  {row['verdict']}")
        print(line)
        output_lines.append(line)

    print()
    output_lines.append("")

    # -----------------------------------------------------------------------
    # Conclusion
    # -----------------------------------------------------------------------

    red_rows    = [r for r in results_table if r["verdict"].startswith("RED")]
    orange_rows = [r for r in results_table if r["verdict"].startswith("ORANGE")]

    conclusion = ["CONCLUSION", "=========="]

    if red_rows:
        conclusion.append(f"  {len(red_rows)} combination(s) with RED (strong) edge:")
        for r in red_rows:
            r7 = r["res"][7]
            conclusion.append(
                f"    W={r['W']}d  N={r['N']}%  N={r7['n']}  "
                f"delta7d={r7['delta']*100:+.1f}pp  p={r7['p_value']:.3f}  "
                f"IS={r7['is_mean']*100:+.1f}%  OOS={r7['oos_mean']*100:+.1f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: RED -- consider implementing as Discord alert (orange severity)")
        conclusion.append("  ACCION: Implementar via Playbook A en CLAUDE.md con cooldown 7d.")
    elif orange_rows:
        conclusion.append(f"  {len(orange_rows)} combination(s) with ORANGE (marginal) edge:")
        for r in orange_rows:
            r7 = r["res"][7]
            conclusion.append(
                f"    W={r['W']}d  N={r['N']}%  N={r7['n']}  "
                f"delta7d={r7['delta']*100:+.1f}pp  p={r7['p_value']:.3f}  "
                f"IS={r7['is_mean']*100:+.1f}%  OOS={r7['oos_mean']*100:+.1f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: ORANGE -- evidence too weak for production. Monitor for more events.")
        conclusion.append("  ACCION: No implementar. Re-evaluar cuando N_OOS >= 5.")
    else:
        conclusion.append("  All (W, N) combinations: DISCARD.")
        conclusion.append("  VERDICT: DISCARD -- multi-day crash adds no edge beyond the existing 24h alert.")
        conclusion.append("  ACCION: No implementar. El crash 24h ya captura el edge disponible.")

    for line in conclusion:
        print(line)
    output_lines.extend(conclusion)

    RESULTS_FILE.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
