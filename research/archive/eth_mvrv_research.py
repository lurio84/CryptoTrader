"""eth_mvrv_research.py
========================
Research 13: ETH MVRV as a buy signal (formal re-validation). DISCARDED.

VERDICT: DISCARD. See RESEARCH_ARCHIVE.md Research 13.
All thresholds (<0.8, 0.8-1.0, <1.0, exploration) failed: delta 30d is
NEGATIVE vs baseline (ETH bull market dominates). Same structural pattern
as BTC MVRV<1.0 (Research 7). Alerts mvrv_critical and mvrv_low removed
from production 2026-04-15.

Motivation
----------
`mvrv_critical` (ETH MVRV < 0.8) and `mvrv_low` (ETH MVRV 0.8-1.0) were in
production but their validation in `research/exit_strategy_research.py`
measured only forward returns + win rate. It did NOT apply the current
repo methodology (IS/OOS split + Mann-Whitney U + bootstrap CI).

This script closed the gap and discarded the signals.

Hypothesis
----------
When ETH MVRV drops into historical undervaluation zones (<1.0), forward
returns should exceed baseline. Two thresholds are tested:
- Critical: MVRV < 0.8
- Low:      0.8 <= MVRV < 1.0
- Exploratory: < 0.9, < 1.1, < 1.2 (for sensitivity)

Signal
------
- Daily indicator: MVRV on date t < threshold
- Cooldown: 7 days (matches production COOLDOWN_MVRV=168h)

Data
----
- ETH MVRV: CoinMetrics (cached at data/research_cache/eth_mvrv.csv)
- ETH price: CoinMetrics PriceUSD (cached at data/research_cache/eth_cm.csv)
- Period: 2015-08-08 (start of CoinMetrics ETH) -> 2026-04-01
- IS: <2022-01-01
- OOS: >=2022-01-01

Stats
-----
- Horizons: 7d, 14d, 30d
- Mann-Whitney U (alternative="greater")
- Bootstrap 95% CI (N=10_000)
- Verdict: same rules as Research 11 / 12

Run
---
    python research/eth_mvrv_research.py
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

FETCH_START = "2015-08-08"
END_DATE    = "2026-04-01"
IS_END      = "2022-01-01"
OOS_START   = "2022-01-01"

THRESHOLDS  = [
    ("critical", 0.0, 0.8),   # MVRV < 0.8
    ("low",      0.8, 1.0),   # 0.8 <= MVRV < 1.0
    ("undervalued", 0.0, 1.0),  # any MVRV < 1.0 (combined)
    ("explore_09",  0.0, 0.9),
    ("explore_11",  0.0, 1.1),
    ("explore_12",  0.0, 1.2),
]
HORIZONS_D   = [7, 14, 30]
COOLDOWN_D   = 7   # matches COOLDOWN_MVRV = 168h in production
N_BOOTSTRAP  = 10_000
MIN_N        = 3

CACHE_DIR    = Path(__file__).parent.parent / "data" / "research_cache"
MVRV_CACHE   = CACHE_DIR / "eth_mvrv.csv"
PRICE_CACHE  = CACHE_DIR / "eth_cm.csv"
RESULTS_FILE = CACHE_DIR / "eth_mvrv_results.txt"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    if not MVRV_CACHE.exists() or not PRICE_CACHE.exists():
        print(f"ERROR: missing caches. Run exit_strategy_research.py first.", file=sys.stderr)
        sys.exit(1)
    mvrv = pd.read_csv(MVRV_CACHE, parse_dates=["date"])
    price = pd.read_csv(PRICE_CACHE, parse_dates=["date"])
    df = mvrv.merge(price, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df = df[(df["date"] >= FETCH_START) & (df["date"] < END_DATE)]
    df = df.set_index("date")
    return df


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signals(df: pd.DataFrame, lo: float, hi: float) -> pd.DatetimeIndex:
    """Dates where lo <= MVRV < hi, with cooldown."""
    mask = (df["mvrv"] >= lo) & (df["mvrv"] < hi)
    candidates = df.index[mask]
    signals = []
    last = None
    for d in sorted(candidates):
        if last is not None and (d - last).days < COOLDOWN_D:
            continue
        signals.append(d)
        last = d
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Stats (shared pattern)
# ---------------------------------------------------------------------------

def forward_return(prices: pd.Series, signal_date, horizon_days: int) -> float | None:
    try:
        idx = prices.index.get_loc(signal_date)
    except KeyError:
        return None
    if isinstance(idx, slice):
        idx = idx.start
    target = idx + horizon_days
    if target >= len(prices):
        return None
    entry = float(prices.iloc[idx])
    exit_ = float(prices.iloc[target])
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


def analyse(prices, signal_dates, non_signal_dates, horizon):
    fwd = [r for r in (forward_return(prices, d, horizon) for d in signal_dates) if r is not None]
    base = [r for r in (forward_return(prices, d, horizon) for d in non_signal_dates) if r is not None]

    is_split = pd.Timestamp(IS_END)
    is_fwd  = [r for r in (forward_return(prices, d, horizon) for d in signal_dates if d <  is_split) if r is not None]
    oos_fwd = [r for r in (forward_return(prices, d, horizon) for d in signal_dates if d >= is_split) if r is not None]

    mean_ret  = float(np.mean(fwd)) if fwd else float("nan")
    base_mean = float(np.mean(base)) if base else float("nan")
    delta     = mean_ret - base_mean if not (np.isnan(mean_ret) or np.isnan(base_mean)) else float("nan")
    win_rate  = float(np.mean([r > 0 for r in fwd])) if fwd else float("nan")
    ci_lo, ci_hi = bootstrap_mean_ci(np.array(fwd)) if fwd else (float("nan"), float("nan"))

    p_value = float("nan")
    if len(fwd) >= MIN_N and len(base) >= MIN_N:
        _, p_value = stats.mannwhitneyu(fwd, base, alternative="greater")

    return {
        "n": len(fwd),
        "n_is": len(is_fwd),
        "n_oos": len(oos_fwd),
        "mean_ret": mean_ret,
        "base_mean": base_mean,
        "delta": delta,
        "win_rate": win_rate,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_value": p_value,
        "is_mean":  float(np.mean(is_fwd))  if is_fwd  else float("nan"),
        "oos_mean": float(np.mean(oos_fwd)) if oos_fwd else float("nan"),
    }


def verdict_row(res_by_h):
    r7  = res_by_h.get(7, {})
    r30 = res_by_h.get(30, {})
    n       = r30.get("n", 0)  # use 30d N since ETH MVRV signal is multi-week
    delta7  = r7.get("delta", float("nan"))
    delta30 = r30.get("delta", float("nan"))
    p30     = r30.get("p_value", float("nan"))
    oos7    = r7.get("oos_mean", float("nan"))
    oos30   = r30.get("oos_mean", float("nan"))

    if n < MIN_N:
        return "DISCARD (N<3)"
    if np.isnan(delta30):
        return "DISCARD (insufficient data)"
    if delta30 < 0 and (np.isnan(delta7) or delta7 < 0):
        return "DISCARD (negative edge)"
    if not np.isnan(oos30) and oos30 < 0:
        return "DISCARD (OOS negative)"

    is_strong = (not np.isnan(p30) and p30 < 0.05 and delta30 > 0.05 and n >= 5
                 and (np.isnan(oos30) or oos30 > 0))
    if is_strong:
        return "RED (strong edge)"
    if delta30 > 0 and (np.isnan(oos30) or oos30 > 0):
        return "ORANGE (positive but low N or marginal p)"
    return "DISCARD (insufficient edge)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("ETH MVRV BUY SIGNAL RESEARCH (Research 13)")
    print("=" * 65)
    print(f"  Period: {FETCH_START} - {END_DATE}")
    print(f"  IS: <{IS_END}  /  OOS: >={OOS_START}")
    print(f"  Cooldown: {COOLDOWN_D}d  |  Bootstrap: {N_BOOTSTRAP:,}  |  Horizons: {HORIZONS_D}")
    print()

    df = load_data()
    prices = df["price"]
    print(f"  Data: {len(df)} days, range {df.index.min().date()} -> {df.index.max().date()}")
    print(f"  MVRV stats: min={df['mvrv'].min():.3f}  median={df['mvrv'].median():.3f}  max={df['mvrv'].max():.3f}")
    print()

    results = []
    for name, lo, hi in THRESHOLDS:
        signals = build_signals(df, lo, hi)
        non_signal = prices.index.difference(signals)
        res_by_h = {h: analyse(prices, signals, non_signal, h) for h in HORIZONS_D}
        results.append({"name": name, "lo": lo, "hi": hi,
                        "res": res_by_h, "verdict": verdict_row(res_by_h)})

    header = (f"  {'signal':<14} {'range':<14}  {'N':>4}  {'N_IS':>4}  {'N_OOS':>5}  "
              f"{'D_7d':>7}  {'D_30d':>7}  {'p_30':>6}  {'WR_30':>6}  "
              f"{'IS_30':>6}  {'OOS_30':>6}  Verdict")
    sep = "  " + "-" * 115
    out = ["ETH MVRV BUY SIGNAL RESEARCH (Research 13)", "=" * 65, header, sep]
    print(header); print(sep)

    def fp(v, d=1):
        return f"{v*100:+.{d}f}%" if not (v is None or np.isnan(v)) else "  -  "
    def fpv(v):
        return f"{v:.3f}" if not (v is None or np.isnan(v)) else "  -  "

    for row in results:
        r7, r30 = row["res"][7], row["res"][30]
        rng = f"[{row['lo']:.2f},{row['hi']:.2f})"
        line = (f"  {row['name']:<14} {rng:<14}  {r30['n']:>4}  {r30['n_is']:>4}  {r30['n_oos']:>5}  "
                f"{fp(r7['delta']):>7}  {fp(r30['delta']):>7}  {fpv(r30['p_value']):>6}  "
                f"{fp(r30['win_rate']):>6}  {fp(r30['is_mean']):>6}  {fp(r30['oos_mean']):>6}  "
                f"{row['verdict']}")
        print(line); out.append(line)

    print(); out.append("")

    # Conclusion
    red    = [r for r in results if r["verdict"].startswith("RED")]
    orange = [r for r in results if r["verdict"].startswith("ORANGE")]

    conclusion = ["CONCLUSION", "=========="]
    if red:
        conclusion.append(f"  {len(red)} combo(s) with RED edge (30d horizon):")
        for r in red:
            r30 = r["res"][30]
            conclusion.append(
                f"    {r['name']:<14}  N={r30['n']}  d30={r30['delta']*100:+.1f}pp  "
                f"p={r30['p_value']:.3f}  IS={r30['is_mean']*100:+.1f}%  "
                f"OOS={r30['oos_mean']*100:+.1f}%  WR={r30['win_rate']*100:.0f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: RED -- current production thresholds validated.")
        conclusion.append("  ACCION: mantener ETH_MVRV_CRITICAL=0.8 y ETH_MVRV_LOW=1.0 en discord_bot.py.")
    elif orange:
        conclusion.append(f"  {len(orange)} combo(s) with ORANGE edge:")
        for r in orange:
            r30 = r["res"][30]
            conclusion.append(
                f"    {r['name']:<14}  N={r30['n']}  d30={r30['delta']*100:+.1f}pp  "
                f"p={r30['p_value']:.3f}  IS={r30['is_mean']*100:+.1f}%  "
                f"OOS={r30['oos_mean']*100:+.1f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: ORANGE -- edge marginal. Considerar downgrade de severidad.")
    else:
        conclusion.append("  All thresholds: DISCARD.")
        conclusion.append("  VERDICT: DISCARD -- ETH MVRV no ofrece edge bajo la metodologia actual.")

    for line in conclusion:
        print(line)
    out.extend(conclusion)

    RESULTS_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
