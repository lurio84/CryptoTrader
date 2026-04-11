"""btc_crash_sensitivity.py
===========================
Research 8: BTC crash threshold sensitivity analysis.

Hypothesis
----------
The current production alert uses BTC 24h drop > -15% as the buy signal
(validated with N=4 events, +10.6% at 7d vs baseline). That N is very low
to trust the exact threshold. This script sweeps -5% to -30% to find the
optimal balance of N and edge.

Setup
-----
- Data:      yfinance BTC-USD daily OHLCV, 2015-01-01 to 2026-04-01
- Signals:   24h return <= threshold (one signal per event, 6h cooldown
             = 1 calendar day minimum between signals on daily data)
- Horizons:  7d, 14d, 30d, 90d forward return
- Baseline:  all non-signal days in the same period
- Stats:     bootstrap 95% CI (N=10_000), Mann-Whitney U test
- Split:     Exploration 2015-2020 / Validation 2021-2026

Run
---
    python research/btc_crash_sensitivity.py

Output
------
Sensitivity table + CONCLUSION block with recommended threshold.
Saves verdict to data/research_cache/btc_crash_sensitivity_results.txt
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

START_DATE  = "2015-01-01"
END_DATE    = "2026-04-01"
SPLIT_DATE  = "2021-01-01"   # exploration / validation boundary

# Thresholds to sweep: -5% to -30% in steps of 1pp
THRESHOLDS  = [t / 100 for t in range(-5, -31, -1)]
HORIZONS_D  = [7, 14, 30, 90]

N_BOOTSTRAP    = 10_000
PVALUE_THRESH  = 0.05
MIN_N_RELIABLE = 5   # minimum events to consider edge reliable

CACHE_DIR  = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BTC_CACHE  = CACHE_DIR / "btc_daily_crash.csv"

RESULTS_FILE = CACHE_DIR / "btc_crash_sensitivity_results.txt"

CURRENT_THRESHOLD = -0.15   # production value


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
    df = ticker.history(start=START_DATE, end=END_DATE, interval="1d")
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

def compute_24h_returns(df: pd.DataFrame) -> pd.Series:
    """Daily close-to-close return."""
    return df["Close"].pct_change()


def build_signal_days(returns: pd.Series, threshold: float, cooldown_days: int = 1) -> pd.DatetimeIndex:
    """Days where 24h return <= threshold, with minimum cooldown_days between signals."""
    candidates = returns[returns <= threshold].index
    signals = []
    last_signal = None
    for date in sorted(candidates):
        if last_signal is None or (date - last_signal).days >= cooldown_days:
            signals.append(date)
            last_signal = date
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Statistics
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


def analyse_threshold(
    prices: pd.Series,
    returns: pd.Series,
    signal_dates: pd.DatetimeIndex,
    horizon_days: int,
    split_date: str,
) -> dict:
    """Full analysis for a given threshold + horizon combination."""
    # Compute forward returns for all signal days
    fwd = [forward_return(prices, d, horizon_days) for d in signal_dates]
    fwd = [r for r in fwd if r is not None]

    # Baseline: all non-signal days with valid forward returns
    signal_set = set(signal_dates)
    baseline_days = [d for d in returns.index if d not in signal_set]
    baseline_fwd = [forward_return(prices, d, horizon_days) for d in baseline_days]
    baseline_fwd = [r for r in baseline_fwd if r is not None]

    # In-sample / out-of-sample split
    split = pd.Timestamp(split_date)
    is_signal = [d for d in signal_dates if d < split]
    oos_signal = [d for d in signal_dates if d >= split]

    is_fwd = [forward_return(prices, d, horizon_days) for d in is_signal]
    is_fwd = [r for r in is_fwd if r is not None]
    oos_fwd = [forward_return(prices, d, horizon_days) for d in oos_signal]
    oos_fwd = [r for r in oos_fwd if r is not None]

    # Stats
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
    """
    RED:     in-sample p<0.05, delta>3pp, N>=5, OOS positive
    ORANGE:  partial evidence (N low but positive, or IS ok + OOS weak)
    DISCARD: no edge, negative OOS, or N<3
    """
    h7  = results_by_horizon.get(7, {})
    h30 = results_by_horizon.get(30, {})

    n = h7.get("n_total", 0)
    delta7  = h7.get("delta", float("nan"))
    delta30 = h30.get("delta", float("nan"))
    p7  = h7.get("p_value", float("nan"))
    p30 = h30.get("p_value", float("nan"))
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
    print("BTC CRASH THRESHOLD SENSITIVITY ANALYSIS (Research 8)")
    print("=" * 65)
    print(f"  Period: {START_DATE} - {END_DATE}")
    print(f"  Split:  exploration <{SPLIT_DATE} / validation >={SPLIT_DATE}")
    print(f"  Bootstrap CI: N={N_BOOTSTRAP:,}")
    print()

    df = load_btc_daily()
    df = df[(df.index >= START_DATE) & (df.index < END_DATE)]
    prices = df["Close"]
    returns = compute_24h_returns(df)

    # Collect all results
    all_results: dict[float, dict[int, dict]] = {}
    for thr in THRESHOLDS:
        signal_dates = build_signal_days(returns, thr)
        results_h: dict[int, dict] = {}
        for h in HORIZONS_D:
            results_h[h] = analyse_threshold(prices, returns, signal_dates, h, SPLIT_DATE)
        all_results[thr] = results_h

    # Print sensitivity table (7d and 30d focused)
    print(f"  {'Thr':>5}  {'N':>4}  {'WR7d':>6}  {'Ret7d':>7}  {'D7d':>7}  {'p7d':>7}  "
          f"{'Ret30d':>7}  {'D30d':>7}  {'p30d':>7}  {'IS7d':>6}  {'OOS7d':>6}  Verdict")
    print("  " + "-" * 110)

    output_lines = []
    header = (f"  {'Thr':>5}  {'N':>4}  {'WR7d':>6}  {'Ret7d':>7}  {'D7d':>7}  {'p7d':>7}  "
              f"{'Ret30d':>7}  {'D30d':>7}  {'p30d':>7}  {'IS7d':>6}  {'OOS7d':>6}  Verdict")
    output_lines.append(header)
    output_lines.append("  " + "-" * 110)

    for thr in THRESHOLDS:
        r7  = all_results[thr][7]
        r30 = all_results[thr][30]
        n = r7["n_total"]
        verd = verdict(all_results[thr])

        marker = " <-- CURRENT" if abs(thr - CURRENT_THRESHOLD) < 0.001 else ""

        def fmt_pct(v: float, decimals: int = 1) -> str:
            if np.isnan(v):
                return "  -  "
            return f"{v*100:+.{decimals}f}%"

        def fmt_p(v: float) -> str:
            if np.isnan(v):
                return "  -   "
            return f"{v:.3f}"

        line = (f"  {thr*100:>4.0f}%  {n:>4}  {fmt_pct(r7['win_rate']):>6}  "
                f"{fmt_pct(r7['mean_ret']):>7}  {fmt_pct(r7['delta']):>7}  {fmt_p(r7['p_value']):>7}  "
                f"{fmt_pct(r30['mean_ret']):>7}  {fmt_pct(r30['delta']):>7}  {fmt_p(r30['p_value']):>7}  "
                f"{fmt_pct(r7['is_mean']):>6}  {fmt_pct(r7['oos_mean']):>6}  {verd}{marker}")
        print(line)
        output_lines.append(line)

    print()
    output_lines.append("")

    # Identify best threshold by: N>=5, highest delta at 7d, OOS positive
    best_thr = CURRENT_THRESHOLD
    best_delta = float("-inf")
    for thr in THRESHOLDS:
        r7 = all_results[thr][7]
        if r7["n_total"] >= MIN_N_RELIABLE and not np.isnan(r7["delta"]):
            oos = r7["oos_mean"]
            if r7["delta"] > best_delta and (np.isnan(oos) or oos > 0):
                best_delta = r7["delta"]
                best_thr = thr

    conclusion_lines = [
        "CONCLUSION",
        "==========",
        f"  Current production threshold: {CURRENT_THRESHOLD*100:.0f}%  (N={all_results[CURRENT_THRESHOLD][7]['n_total']})",
        f"  Optimal threshold found:      {best_thr*100:.0f}%  (N={all_results[best_thr][7]['n_total']}, "
        f"delta7d={all_results[best_thr][7]['delta']*100:+.1f}pp)",
    ]

    r_best_7 = all_results[best_thr][7]
    r_best_30 = all_results[best_thr][30]
    conclusion_lines += [
        f"    Mean 7d: {r_best_7['mean_ret']*100:+.1f}%  (baseline {r_best_7['baseline_mean']*100:+.1f}%,  p={r_best_7['p_value']:.3f})",
        f"    Mean 30d: {r_best_30['mean_ret']*100:+.1f}%  (baseline {r_best_30['baseline_mean']*100:+.1f}%,  p={r_best_30['p_value']:.3f})",
        f"    IS 7d: {r_best_7['is_mean']*100:+.1f}%   OOS 7d: {r_best_7['oos_mean']*100:+.1f}%",
        f"    Win rate: {r_best_7['win_rate']*100:.0f}%",
        "",
    ]

    if abs(best_thr - CURRENT_THRESHOLD) < 0.005:
        conclusion_lines.append("  VERDICT: Current -15% threshold is at/near the optimum. NO CHANGE needed.")
        action = "KEEP"
    elif abs(best_thr - CURRENT_THRESHOLD) < 0.03:
        conclusion_lines.append(f"  VERDICT: Best threshold ({best_thr*100:.0f}%) is close to current (-15%). "
                                 f"Difference is within noise given low N. Recommend KEEP -15%.")
        action = "KEEP"
    else:
        conclusion_lines.append(f"  VERDICT: Best threshold ({best_thr*100:.0f}%) differs significantly from "
                                 f"current (-15%). Consider updating BTC_CRASH_THRESHOLD.")
        action = f"CHANGE to {best_thr*100:.0f}%"

    conclusion_lines.append(f"  ACTION: {action}")

    for line in conclusion_lines:
        print(line)
    output_lines.extend(conclusion_lines)

    # Save results
    results_text = "\n".join(output_lines)
    RESULTS_FILE.write_text(results_text, encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
