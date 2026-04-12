"""research_nupl.py
==================
Research: Does BTC NUPL provide a sell/reduce signal at high values?

Hypothesis
----------
NUPL (Net Unrealized Profit/Loss) = 1 - 1/MVRV measures what fraction of
BTC's market cap represents unrealized profit across all holders.

    NUPL = (Market Cap - Realized Cap) / Market Cap = 1 - (1 / MVRV)

Willy Woo's zones (empirical, not statistically validated):
    > 0.75  Euphoria/Greed    -- historically near cycle tops
    0.5-0.75 Belief           -- bull market
    0.25-0.5 Optimism         -- mid-cycle
    0-0.25   Hope/Fear        -- early recovery
    < 0.0   Capitulation      -- entire network at a loss (= MVRV < 1.0)

Research questions
------------------
1. Does BTC NUPL > 0.75 (or > 0.60) predict below-average forward returns?
   If so, it could serve as a DCA-out severity modifier or standalone alert.
2. Does high-NUPL signal hold OOS (2022-present)?
3. Secondary: NUPL < 0.0 as buy signal. NOTE: this is mathematically
   equivalent to BTC MVRV < 1.0, which was already DISCARDED in
   btc_mvrv_research.py (OOS delta = -17.2pp, WR = 0%). Included here
   only to confirm consistency with that prior result.

Key difference from existing signals
-------------------------------------
All current buy signals (ETH MVRV, funding rate, BTC crash, S&P crash)
are entry/accumulation signals. NUPL is tested as the first candidate
EXIT signal based on on-chain valuation -- distinct from price-based
DCA-out levels ($80k, $100k...).

Setup
-----
- Data:    BTC CapMVRVCur + PriceUSD from CoinMetrics (reuses btc_mvrv_daily.csv cache)
- NUPL:    Derived as 1 - 1/MVRV (no separate API call needed)
- Signals: NUPL crosses above high threshold (cross-above, 30d cooldown)
           NUPL crosses below low threshold (cross-below, 30d cooldown)
- Horizons: 7d, 14d, 30d, 90d forward return on BTC/USD
- Baseline: all days where NUPL is NOT in the signal zone (same period)
- Stats:   Bootstrap 95% CI (N=10000), Mann-Whitney U (two-sided)
- Split:   Exploration 2011-2022 / Validation 2022-2026

Run
---
    python research/research_nupl.py

Output
------
Results per threshold + CONCLUSION block (RED / ORANGE / DISCARD).
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# High NUPL thresholds to test as SELL/REDUCE signals
HIGH_THRESHOLDS = [0.60, 0.75]

# Low NUPL thresholds to test as BUY signals
# NOTE: NUPL < 0.0 == MVRV < 1.0, already DISCARDED in btc_mvrv_research.py
# Included here only for consistency check.
LOW_THRESHOLDS  = [0.0, 0.25]

HORIZONS_D      = [7, 14, 30, 90]
N_BOOTSTRAP     = 10_000
PVALUE_THRESH   = 0.05
SPLIT_DATE      = "2022-01-01"     # exploration / validation boundary

CACHE_DIR       = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Reuse BTC MVRV cache from btc_mvrv_research.py -- NUPL is derived from MVRV
CACHE_FILE      = CACHE_DIR / "btc_mvrv_daily.csv"

COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def fetch_btc_data() -> pd.DataFrame:
    """Load BTC MVRV + PriceUSD, then derive NUPL = 1 - 1/MVRV.

    Reuses btc_mvrv_daily.csv if present (written by btc_mvrv_research.py).
    Downloads from CoinMetrics if not cached.

    Returns DataFrame with columns [mvrv, price, nupl], DatetimeIndex.
    """
    if CACHE_FILE.exists():
        print("  Loading from cache ({})...".format(CACHE_FILE.name))
        df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        print("  Loaded {:,} daily bars ({} to {})".format(
            len(df), df.index.min().date(), df.index.max().date()
        ))
    else:
        print("  Cache not found -- downloading from CoinMetrics community API...")
        print("  (Run btc_mvrv_research.py first to populate cache faster.)")

        all_rows = []
        next_page = None
        while True:
            params = {
                "assets":      "btc",
                "metrics":     "CapMVRVCur,PriceUSD",
                "frequency":   "1d",
                "page_size":   "10000",
                "paging_from": "start",
            }
            if next_page:
                params["next_page_token"] = next_page

            resp = requests.get(COINMETRICS_URL, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("data", [])
            all_rows.extend(rows)
            print("  ... fetched {:,} rows".format(len(all_rows)))
            next_page = payload.get("next_page_token")
            if not next_page or not rows:
                break
            time.sleep(0.5)

        df = pd.DataFrame(all_rows)
        df["date"]  = pd.to_datetime(df["time"]).dt.normalize()
        df          = df.set_index("date")
        df["mvrv"]  = pd.to_numeric(df["CapMVRVCur"], errors="coerce")
        df["price"] = pd.to_numeric(df["PriceUSD"],   errors="coerce")
        df          = df[["mvrv", "price"]].dropna().sort_index()
        df.to_csv(CACHE_FILE)
        print("  Saved {:,} rows to {}".format(len(df), CACHE_FILE.name))

    # Derive NUPL from MVRV (mathematically equivalent, no rounding error)
    df = df[df["mvrv"] > 0].copy()
    df["nupl"] = 1.0 - 1.0 / df["mvrv"]
    return df


# ---------------------------------------------------------------------------
# Statistical helpers  (identical to btc_mvrv_research.py)
# ---------------------------------------------------------------------------

def bootstrap_ci(
    data: np.ndarray,
    n_boot: int = N_BOOTSTRAP,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    boot_means = np.fromiter(
        (np.mean(rng.choice(data, size=len(data), replace=True)) for _ in range(n_boot)),
        dtype=float,
        count=n_boot,
    )
    alpha = (1 - ci) / 2
    return float(np.percentile(boot_means, alpha * 100)), \
           float(np.percentile(boot_means, (1 - alpha) * 100))


def mann_whitney_pvalue(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or len(b) < 3:
        return 1.0
    _, pval = stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(pval)


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_crossabove_signals(df: pd.DataFrame, threshold: float) -> pd.DatetimeIndex:
    """Dates where NUPL crosses ABOVE threshold (signal for sell/reduce).

    30-day cooldown between events.
    """
    above = df["nupl"] > threshold
    crossed = above & ~above.shift(1, fill_value=False)

    signal_dates = []
    tz = crossed.index.tz
    last = pd.Timestamp("1970-01-01", tz=tz) if tz else pd.Timestamp("1970-01-01")

    for date in crossed[crossed].index:
        if (date - last).days >= 30:
            signal_dates.append(date)
            last = date

    return pd.DatetimeIndex(signal_dates)


def build_crossbelow_signals(df: pd.DataFrame, threshold: float) -> pd.DatetimeIndex:
    """Dates where NUPL crosses BELOW threshold (signal for buy).

    30-day cooldown between events.
    """
    below = df["nupl"] < threshold
    crossed = below & ~below.shift(1, fill_value=False)

    signal_dates = []
    tz = crossed.index.tz
    last = pd.Timestamp("1970-01-01", tz=tz) if tz else pd.Timestamp("1970-01-01")

    for date in crossed[crossed].index:
        if (date - last).days >= 30:
            signal_dates.append(date)
            last = date

    return pd.DatetimeIndex(signal_dates)


# ---------------------------------------------------------------------------
# Forward return computation
# ---------------------------------------------------------------------------

def compute_forward_return(df: pd.DataFrame, signal_date: pd.Timestamp, horizon: int) -> float | None:
    target = signal_date + pd.Timedelta(days=horizon)
    future = df.index[df.index >= target]
    if len(future) == 0:
        return None
    future_price = df.loc[future[0], "price"]
    base_price   = df.loc[signal_date, "price"]
    if base_price <= 0:
        return None
    return float((future_price - base_price) / base_price)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyse(
    df: pd.DataFrame,
    signal_dates: pd.DatetimeIndex,
    baseline_dates: pd.DatetimeIndex,
    label: str,
) -> dict:
    """Compute forward returns for signal vs baseline across all horizons."""
    results: dict = {"label": label, "n_events": len(signal_dates), "horizons": {}}

    for h in HORIZONS_D:
        sig_rets  = [r for d in signal_dates  if (r := compute_forward_return(df, d, h)) is not None]
        base_rets = [r for d in baseline_dates if (r := compute_forward_return(df, d, h)) is not None]

        sig_arr  = np.array(sig_rets)
        base_arr = np.array(base_rets)

        if len(sig_arr) < 3:
            results["horizons"][h] = {
                "n": len(sig_arr), "mean": float("nan"), "ci_lo": float("nan"),
                "ci_hi": float("nan"), "baseline": float(np.mean(base_arr)) if len(base_arr) else float("nan"),
                "delta": float("nan"), "pvalue": float("nan"), "win_rate": float("nan"),
            }
            continue

        mean_sig  = float(np.mean(sig_arr))
        mean_base = float(np.mean(base_arr)) if len(base_arr) else 0.0
        ci_lo, ci_hi = bootstrap_ci(sig_arr)
        pval = mann_whitney_pvalue(sig_arr, base_arr)
        win_rate = float(np.mean(sig_arr > 0))

        results["horizons"][h] = {
            "n":        len(sig_arr),
            "mean":     mean_sig,
            "ci_lo":    ci_lo,
            "ci_hi":    ci_hi,
            "baseline": mean_base,
            "delta":    mean_sig - mean_base,
            "pvalue":   pval,
            "win_rate": win_rate,
        }

    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_results(r: dict, threshold: float, direction: str) -> None:
    sign = ">" if direction == "high" else "<"
    print()
    print("  NUPL {} {:.2f}  |  {}  |  N events = {:d}".format(
        sign, threshold, r["label"], r["n_events"]
    ))
    print("  {:>6}  {:>8}  {:>17}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        "Horiz", "N", "Mean (95% CI)", "Base", "Delta", "p-val", "Win%"
    ))
    print("  " + "-" * 72)
    for h, hr in r["horizons"].items():
        if hr["n"] < 3:
            print("  {:>5}d  {:>8d}  {:>17}".format(h, hr["n"], "N/A (N<3)"))
            continue
        sig_str = "{:+.1f}% [{:+.1f},{:+.1f}]".format(
            hr["mean"] * 100, hr["ci_lo"] * 100, hr["ci_hi"] * 100
        )
        p_mark = "*" if hr["pvalue"] < PVALUE_THRESH else " "
        print("  {:>5}d  {:>8d}  {:>17}  {:>7.1f}%  {:>+7.1f}pp  {:>7.3f}{} {:>7.1f}%".format(
            h,
            hr["n"],
            sig_str,
            hr["baseline"] * 100,
            hr["delta"] * 100,
            hr["pvalue"],
            p_mark,
            hr["win_rate"] * 100,
        ))


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verdict(
    high_full: list[dict], high_oos: list[dict],
    low_full: list[dict],  low_oos: list[dict],
) -> str:
    lines = ["=" * 70, "VERDICT: BTC NUPL signal analysis", "=" * 70]

    lines.append("")
    lines.append("  HIGH NUPL (sell/reduce signal)")
    lines.append("  --------------------------------")

    for threshold, rf, ro in zip(HIGH_THRESHOLDS, high_full, high_oos):
        lines.append("")
        lines.append("  NUPL > {:.2f}".format(threshold))

        h30_f = rf["horizons"].get(30, {})
        h30_o = ro["horizons"].get(30, {})

        n_f = h30_f.get("n", 0)
        n_o = h30_o.get("n", 0)
        delta_f  = h30_f.get("delta", float("nan")) * 100
        delta_o  = h30_o.get("delta", float("nan")) * 100
        p_f      = h30_f.get("pvalue", 1.0)
        p_o      = h30_o.get("pvalue", 1.0)
        mean_f   = h30_f.get("mean", float("nan")) * 100
        ci_lo    = h30_f.get("ci_lo", float("nan")) * 100
        ci_hi    = h30_f.get("ci_hi", float("nan")) * 100
        wr_f     = h30_f.get("win_rate", float("nan")) * 100

        if n_f < 3:
            lines.append("  DISCARD: solo {:d} eventos in-sample. Datos insuficientes.".format(n_f))
            continue

        lines.append("  IS (2011-2022) : N={:d}, 30d={:+.1f}% [CI {:+.1f},{:+.1f}], delta={:+.1f}pp, p={:.3f}, WR={:.0f}%".format(
            n_f, mean_f, ci_lo, ci_hi, delta_f, p_f, wr_f))

        if n_o >= 3:
            lines.append("  OOS (2022+)   : N={:d}, 30d delta={:+.1f}pp, p={:.3f}".format(n_o, delta_o, p_o))
        else:
            lines.append("  OOS (2022+)   : N={:d} -- INSUFICIENTE".format(n_o))

        # For a SELL signal: edge = negative delta (lower returns vs baseline when NUPL is high)
        has_edge = (delta_f < -3.0 and p_f < PVALUE_THRESH and n_f >= 5)
        oos_ok   = (n_o >= 3 and delta_o < 0)

        if has_edge and oos_ok:
            lines.append("  => RECOMENDACION: ORANGE -- reducir % DCA-out cuando NUPL > {:.2f}".format(threshold))
        elif has_edge and n_o < 3:
            lines.append("  => RECOMENDACION: INFORMATIVO -- edge IS pero sin OOS suficiente")
        elif delta_f < 0 and p_f < 0.10:
            lines.append("  => RECOMENDACION: INFORMATIVO -- tendencia negativa pero p>{:.2f}".format(PVALUE_THRESH))
        else:
            lines.append("  => RECOMENDACION: DISCARD -- sin edge o resultados positivos (momentum continua)")

    lines.append("")
    lines.append("  LOW NUPL (buy signal -- referencia vs btc_mvrv_research.py)")
    lines.append("  ---------------------------------------------------------------")
    lines.append("  NOTA: NUPL < 0.0 == MVRV < 1.0. Ya descartado en btc_mvrv_research.py")
    lines.append("  (OOS WR=0%, delta=-17.2pp). Incluido aqui solo para consistencia.")

    for threshold, rf, ro in zip(LOW_THRESHOLDS, low_full, low_oos):
        h30_f = rf["horizons"].get(30, {})
        n_f   = h30_f.get("n", 0)
        delta_f = h30_f.get("delta", float("nan")) * 100 if n_f >= 3 else float("nan")
        p_f   = h30_f.get("pvalue", 1.0)
        lines.append("")
        if n_f < 3:
            lines.append("  NUPL < {:.2f}: N={:d} -- DISCARD (datos insuficientes)".format(threshold, n_f))
        elif delta_f < 0:
            lines.append("  NUPL < {:.2f}: N={:d}, delta={:+.1f}pp, p={:.3f} -- DISCARD (negativo, consistente con MVRV<1.0)".format(
                threshold, n_f, delta_f, p_f))
        else:
            lines.append("  NUPL < {:.2f}: N={:d}, delta={:+.1f}pp, p={:.3f}".format(threshold, n_f, delta_f, p_f))

    lines += ["", "=" * 70]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("BTC NUPL Signal Research")
    print("=" * 70)

    # 1. Load data
    print("\n[1/4] Loading BTC MVRV + price data...")
    df = fetch_btc_data()

    print()
    print("  Data range  : {} to {}".format(df.index.min().date(), df.index.max().date()))
    print("  Total days  : {:,}".format(len(df)))
    print("  MVRV range  : {:.3f} -- {:.3f}".format(df["mvrv"].min(), df["mvrv"].max()))
    print("  NUPL range  : {:.3f} -- {:.3f}  (mean {:.3f}, median {:.3f})".format(
        df["nupl"].min(), df["nupl"].max(), df["nupl"].mean(), df["nupl"].median()
    ))
    print()
    for t in HIGH_THRESHOLDS:
        n = int((df["nupl"] > t).sum())
        print("  NUPL > {:.2f}  : {:,} days ({:.1f}% of history)".format(t, n, 100 * n / len(df)))
    for t in LOW_THRESHOLDS:
        n = int((df["nupl"] < t).sum())
        print("  NUPL < {:.2f}  : {:,} days ({:.1f}% of history)".format(t, n, 100 * n / len(df)))

    # Split
    df_is  = df[df.index < SPLIT_DATE]
    df_oos = df[df.index >= SPLIT_DATE]
    print()
    print("  IS  : {} to {} ({:,} days)".format(
        df_is.index.min().date(), df_is.index.max().date(), len(df_is)))
    print("  OOS : {} to {} ({:,} days)".format(
        df_oos.index.min().date(), df_oos.index.max().date(), len(df_oos)))

    # 2. Signal dates
    print("\n[2/4] Signal entry events (30d cooldown)...")
    for t in HIGH_THRESHOLDS:
        sig_is  = build_crossabove_signals(df_is, t)
        sig_oos = build_crossabove_signals(df_oos, t)
        print("  NUPL > {:.2f}: IS={:d}  OOS={:d}  dates={}".format(
            t, len(sig_is), len(sig_oos),
            ", ".join(d.strftime("%Y-%m") for d in build_crossabove_signals(df, t))
        ))
    for t in LOW_THRESHOLDS:
        sig_is  = build_crossbelow_signals(df_is, t)
        sig_oos = build_crossbelow_signals(df_oos, t)
        print("  NUPL < {:.2f}: IS={:d}  OOS={:d}  dates={}".format(
            t, len(sig_is), len(sig_oos),
            ", ".join(d.strftime("%Y-%m") for d in build_crossbelow_signals(df, t))
        ))

    # 3. Forward return analysis
    print("\n[3/4] Forward return analysis...")

    high_full_results: list[dict] = []
    high_oos_results:  list[dict] = []
    low_full_results:  list[dict] = []
    low_oos_results:   list[dict] = []

    # HIGH NUPL (sell signal candidates)
    for t in HIGH_THRESHOLDS:
        print("\n  --- NUPL > {:.2f} (high, sell/reduce candidate) ---".format(t))

        sig_is   = build_crossabove_signals(df_is, t)
        base_is  = df_is.index[df_is["nupl"] <= t]
        r_is = analyse(df, sig_is, base_is, "IS 2011-2022")
        print_results(r_is, t, "high")
        high_full_results.append(r_is)

        sig_oos  = build_crossabove_signals(df_oos, t)
        base_oos = df_oos.index[df_oos["nupl"] <= t]
        print()
        r_oos = analyse(df, sig_oos, base_oos, "OOS 2022-2026")
        print_results(r_oos, t, "high")
        high_oos_results.append(r_oos)

    # LOW NUPL (buy signal candidates)
    for t in LOW_THRESHOLDS:
        print("\n  --- NUPL < {:.2f} (low, buy candidate) ---".format(t))

        sig_is   = build_crossbelow_signals(df_is, t)
        base_is  = df_is.index[df_is["nupl"] >= t]
        r_is = analyse(df, sig_is, base_is, "IS 2011-2022")
        print_results(r_is, t, "low")
        low_full_results.append(r_is)

        sig_oos  = build_crossbelow_signals(df_oos, t)
        base_oos = df_oos.index[df_oos["nupl"] >= t]
        print()
        r_oos = analyse(df, sig_oos, base_oos, "OOS 2022-2026")
        print_results(r_oos, t, "low")
        low_oos_results.append(r_oos)

    # 4. Summary table at 30d for all thresholds
    print("\n[4/4] Summary at 30d horizon")
    print()
    print("  {:>14}  {:>8}  {:>10}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        "Threshold", "N (IS)", "Mean30d", "Base30d", "Delta", "p-val", "Win%"
    ))
    print("  " + "-" * 70)

    all_thresholds = (
        [("NUPL > {:.2f}".format(t), r) for t, r in zip(HIGH_THRESHOLDS, high_full_results)] +
        [("NUPL < {:.2f}".format(t), r) for t, r in zip(LOW_THRESHOLDS, low_full_results)]
    )
    for label, r in all_thresholds:
        hr = r["horizons"].get(30, {})
        if hr.get("n", 0) < 3:
            print("  {:>14}  {:>8d}  {:>10}".format(label, hr.get("n", 0), "N/A"))
        else:
            print("  {:>14}  {:>8d}  {:>+9.1f}%  {:>+7.1f}%  {:>+7.1f}pp  {:>7.3f}  {:>6.0f}%".format(
                label,
                hr["n"],
                hr["mean"]     * 100,
                hr["baseline"] * 100,
                hr["delta"]    * 100,
                hr["pvalue"],
                hr["win_rate"] * 100,
            ))

    # 5. Verdict
    print()
    print(verdict(high_full_results, high_oos_results, low_full_results, low_oos_results))


if __name__ == "__main__":
    main()
