"""btc_mvrv_research.py
=====================
Research: Does BTC MVRV < 1.0 (or < 0.8) provide a buy signal?

Hypothesis
----------
When BTC trades below its realized price (MVRV < 1.0), the average holder is
at a loss -- historically a capitulation zone that precedes recoveries.
This mirrors the validated ETH MVRV signal (research3/5) but needs its own
backtest because BTC has different cycle dynamics (realized cap grows faster,
MVRV crosses below 1.0 less frequently than ETH).

Research questions
------------------
1. Do forward returns (7d / 14d / 30d / 90d) differ significantly from
   baseline when BTC MVRV < 1.0?
2. Is 0.8 a better threshold than 1.0 (fewer false signals, higher edge)?
3. Should the alert be severity RED (like ETH MVRV < 0.8) or ORANGE?
4. Does the signal generalise out-of-sample (post-2021)?

Setup
-----
- Data:     CoinMetrics community API -- BTC CapMVRVCur + PriceUSD, daily 2011-2026
- Signals:  MVRV enters zone (today < threshold AND yesterday >= threshold)
            vs sustained zone (any day MVRV < threshold, 30d cooldown to avoid
            counting same episode multiple times)
- Horizons: 7d, 14d, 30d, 90d forward return on BTC/USD
- Baseline: all days where MVRV >= threshold (same period)
- Stats:    bootstrap 95% CI (N=10000), Mann-Whitney U test (two-sided)
- Split:    Exploration 2011-2021 / Validation 2021-2026
- Thresholds tested: 0.8 and 1.0

Run
---
    python research/btc_mvrv_research.py

Output
------
Results table per threshold + CONCLUSION block (RED / ORANGE / DISCARD).
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

THRESHOLDS     = [0.8, 1.0]       # MVRV thresholds to test
HORIZONS_D     = [7, 14, 30, 90]  # forward return horizons in calendar days
N_BOOTSTRAP    = 10_000
PVALUE_THRESH  = 0.05
SPLIT_DATE     = "2021-01-01"     # exploration / validation boundary

CACHE_DIR      = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE     = CACHE_DIR / "btc_mvrv_daily.csv"

COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def fetch_btc_mvrv_history() -> pd.DataFrame:
    """Download BTC daily MVRV + PriceUSD from CoinMetrics community API.

    Returns DataFrame with columns [date, mvrv, price] indexed by date.
    Caches to CSV to avoid re-downloading on each run.
    """
    if CACHE_FILE.exists():
        print("  Loading BTC MVRV from cache ({})...".format(CACHE_FILE.name))
        df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        print("  Loaded {:,} daily bars ({} to {})".format(
            len(df), df.index.min().date(), df.index.max().date()
        ))
        return df

    print("  Downloading BTC MVRV + PriceUSD from CoinMetrics community API...")

    all_rows = []
    next_page = None

    while True:
        params = {
            "assets":       "btc",
            "metrics":      "CapMVRVCur,PriceUSD",
            "frequency":    "1d",
            "page_size":    "10000",
            "paging_from":  "start",
        }
        if next_page:
            params["next_page_token"] = next_page

        try:
            resp = requests.get(COINMETRICS_URL, params=params, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print("  ERROR: CoinMetrics request failed: {}".format(e))
            raise

        payload = resp.json()
        rows = payload.get("data", [])
        all_rows.extend(rows)
        print("  ... fetched {:,} rows so far".format(len(all_rows)))

        next_page = payload.get("next_page_token")
        if not next_page or not rows:
            break
        time.sleep(0.5)  # be polite to the free API

    if not all_rows:
        raise ValueError("CoinMetrics returned no data for BTC MVRV.")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"]).dt.normalize()
    df = df.set_index("date")

    # Coerce metrics to numeric; drop rows where either metric is missing
    df["mvrv"]  = pd.to_numeric(df["CapMVRVCur"], errors="coerce")
    df["price"] = pd.to_numeric(df["PriceUSD"],   errors="coerce")
    df = df[["mvrv", "price"]].dropna()
    df = df.sort_index()

    df.to_csv(CACHE_FILE)
    print("  Saved {:,} daily bars to {}".format(len(df), CACHE_FILE.name))
    return df


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def bootstrap_ci(
    data: np.ndarray,
    n_boot: int = N_BOOTSTRAP,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """95% CI for mean via bootstrap resampling."""
    rng = np.random.default_rng(seed)
    boot_means = np.fromiter(
        (np.mean(rng.choice(data, size=len(data), replace=True)) for _ in range(n_boot)),
        dtype=float,
        count=n_boot,
    )
    alpha = (1 - ci) / 2
    return float(np.percentile(boot_means, alpha * 100)), \
           float(np.percentile(boot_means, (1 - alpha) * 100))


def mann_whitney_pvalue(signal_rets: np.ndarray, baseline_rets: np.ndarray) -> float:
    """Two-sided Mann-Whitney U p-value. Returns 1.0 if insufficient data."""
    if len(signal_rets) < 3 or len(baseline_rets) < 3:
        return 1.0
    _, pval = stats.mannwhitneyu(signal_rets, baseline_rets, alternative="two-sided")
    return float(pval)


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signal_days(df: pd.DataFrame, threshold: float) -> pd.DatetimeIndex:
    """
    Return dates that are the ENTRY day into the signal zone.

    Entry = first day MVRV crosses below threshold (today < threshold
    AND yesterday >= threshold). Uses 30-day cooldown so each capitulation
    episode contributes at most one event. This is consistent with the
    production alert's 7-day cooldown (conservative here to avoid over-counting).
    """
    below = df["mvrv"] < threshold
    # cross-below: today is below, yesterday was not
    crossed = below & ~below.shift(1, fill_value=False)

    signal_dates = []
    # Use a sentinel that matches the index timezone (tz-naive after normalize())
    tz = crossed.index.tz
    last_signal = pd.Timestamp("1970-01-01", tz=tz) if tz is not None else pd.Timestamp("1970-01-01")

    for date in crossed[crossed].index:
        if (date - last_signal).days >= 30:
            signal_dates.append(date)
            last_signal = date

    return pd.DatetimeIndex(signal_dates)


def build_sustained_days(df: pd.DataFrame, threshold: float) -> pd.DatetimeIndex:
    """
    Alternative: ALL days where MVRV < threshold (sustained-zone approach).

    Used as secondary check -- more data points, but episodes are autocorrelated.
    """
    return df.index[df["mvrv"] < threshold]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_forward_return(df: pd.DataFrame, signal_date: pd.Timestamp, horizon: int) -> float | None:
    """
    Forward return H calendar days after signal_date.
    Finds the closest available price on or after signal_date + H days.
    """
    target = signal_date + pd.Timedelta(days=horizon)
    future = df.index[df.index >= target]
    if len(future) == 0:
        return None
    future_price = df.loc[future[0], "price"]
    base_price   = df.loc[signal_date, "price"]
    if base_price <= 0:
        return None
    return float((future_price - base_price) / base_price)


def analyse_threshold(
    df: pd.DataFrame,
    threshold: float,
    label: str = "Full period",
    verbose: bool = True,
) -> dict:
    """Run full analysis for a given threshold on the given df slice."""

    signal_dates = build_signal_days(df, threshold)
    baseline_dates = df.index[df["mvrv"] >= threshold]

    results: dict = {"threshold": threshold, "label": label, "n_events": len(signal_dates)}

    if verbose:
        below_days = int((df["mvrv"] < threshold).sum())
        total_days = len(df)
        print()
        print("  Threshold {:.1f} | {} | {:d} entry events | {:d}/{:d} days below ({:.1f}%)".format(
            threshold, label, len(signal_dates),
            below_days, total_days, 100 * below_days / total_days
        ))
        print("  Entry dates: {}".format(
            ", ".join(d.strftime("%Y-%m-%d") for d in signal_dates[:10])
            + (" ..." if len(signal_dates) > 10 else "")
        ))

    horizon_results = {}
    for h in HORIZONS_D:
        sig_rets   = []
        base_rets  = []

        for d in signal_dates:
            r = compute_forward_return(df, d, h)
            if r is not None:
                sig_rets.append(r)

        for d in baseline_dates:
            r = compute_forward_return(df, d, h)
            if r is not None:
                base_rets.append(r)

        sig_arr  = np.array(sig_rets)
        base_arr = np.array(base_rets)

        if len(sig_arr) < 3:
            horizon_results[h] = {
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

        horizon_results[h] = {
            "n":        len(sig_arr),
            "mean":     mean_sig,
            "ci_lo":    ci_lo,
            "ci_hi":    ci_hi,
            "baseline": mean_base,
            "delta":    mean_sig - mean_base,
            "pvalue":   pval,
            "win_rate": win_rate,
        }

    results["horizons"] = horizon_results
    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_results(r: dict) -> None:
    """Print a formatted table for one threshold/period combination."""
    print()
    print("  Threshold MVRV < {:.1f}  |  {}  |  N events = {:d}".format(
        r["threshold"], r["label"], r["n_events"]
    ))
    print("  {:>6}  {:>8}  {:>14}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        "Horiz", "N", "Mean (95% CI)", "Base", "Delta", "p-val", "Win%"
    ))
    print("  " + "-" * 70)
    for h, hr in r["horizons"].items():
        if hr["n"] < 3:
            print("  {:>5}d  {:>8d}  {:>14}  {:>8}  {:>8}  {:>8}  {:>8}".format(
                h, hr["n"], "N/A (N<3)", "-", "-", "-", "-"
            ))
            continue
        sig_str = "{:+.1f}% [{:+.1f},{:+.1f}]".format(
            hr["mean"] * 100, hr["ci_lo"] * 100, hr["ci_hi"] * 100
        )
        p_str = "{:.3f}".format(hr["pvalue"])
        p_mark = "*" if hr["pvalue"] < PVALUE_THRESH else " "
        print("  {:>5}d  {:>8d}  {:>14}  {:>7.1f}%  {:>+7.1f}pp  {:>7}{} {:>7.1f}%".format(
            h,
            hr["n"],
            sig_str,
            hr["baseline"] * 100,
            hr["delta"] * 100,
            p_str,
            p_mark,
            hr["win_rate"] * 100,
        ))


def verdict(results_full: list[dict], results_oos: list[dict]) -> str:
    """
    Produce a plain-text verdict:
    RED / ORANGE / DISCARD based on statistical evidence.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("VERDICT: BTC MVRV buy signal analysis")
    lines.append("=" * 70)

    for threshold, rf, ro in zip(THRESHOLDS, results_full, results_oos):
        lines.append("")
        lines.append("  Threshold MVRV < {:.1f}".format(threshold))
        lines.append("  --------------------------------")

        # Focus on 30d horizon (primary decision horizon, matches ETH MVRV)
        h30_full = rf["horizons"].get(30, {})
        h30_oos  = ro["horizons"].get(30, {})
        h90_full = rf["horizons"].get(90, {})

        n_full = h30_full.get("n", 0)
        n_oos  = h30_oos.get("n", 0)
        mean30 = h30_full.get("mean", float("nan")) * 100
        delta30 = h30_full.get("delta", float("nan")) * 100
        p30    = h30_full.get("pvalue", 1.0)
        ci_lo  = h30_full.get("ci_lo", float("nan")) * 100
        ci_hi  = h30_full.get("ci_hi", float("nan")) * 100
        wr30   = h30_full.get("win_rate", float("nan")) * 100

        mean30_oos  = h30_oos.get("mean", float("nan")) * 100
        delta30_oos = h30_oos.get("delta", float("nan")) * 100
        p30_oos     = h30_oos.get("pvalue", 1.0)

        if n_full < 3:
            lines.append("  DISCARD: only {:d} in-sample events. Insufficient data.".format(n_full))
            continue

        lines.append("  In-sample  (all data)  : N={:d}, 30d={:+.1f}% [CI {:+.1f},{:+.1f}], "
                     "delta={:+.1f}pp, p={:.3f}, WR={:.0f}%".format(
                         n_full, mean30, ci_lo, ci_hi, delta30, p30, wr30))

        if n_oos >= 3:
            lines.append("  Out-of-sample (2021+)  : N={:d}, 30d={:+.1f}%, delta={:+.1f}pp, p={:.3f}".format(
                n_oos, mean30_oos, delta30_oos, p30_oos))
        else:
            lines.append("  Out-of-sample (2021+)  : N={:d} -- INSUFFICIENT (signal too rare post-2021)".format(n_oos))

        # Decision logic:
        # RED: strong in-sample edge, p<0.05, positive OOS, N>=5
        # ORANGE: moderate edge or insufficient OOS
        # DISCARD: no edge or negative
        in_sample_ok  = (p30 < PVALUE_THRESH and delta30 > 3.0 and n_full >= 5)
        oos_ok         = (n_oos >= 3 and delta30_oos > 0)
        any_edge       = (delta30 > 0 and mean30 > 0)

        if in_sample_ok and oos_ok:
            lines.append("  => RECOMENDACION: RED -- edge estadisticamente significativo en muestra y OOS")
        elif in_sample_ok and n_oos < 3:
            lines.append("  => RECOMENDACION: ORANGE -- edge in-sample pero sin datos OOS suficientes (senal rara)")
        elif any_edge and p30 < 0.10:
            lines.append("  => RECOMENDACION: ORANGE -- edge positivo pero p>0.05 o N bajo")
        elif not any_edge:
            lines.append("  => RECOMENDACION: DISCARD -- sin edge o retornos negativos vs baseline")
        else:
            lines.append("  => RECOMENDACION: ORANGE -- evidencia mixta, mantener como alerta de baja severidad")

    lines.append("")
    lines.append("  Nota: MVRV alto NO es senal de venta (momentum continua, validado en research3).")
    lines.append("  Esta senal es exclusivamente para la zona de BAJA valoracion (entrada/compra).")
    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("BTC MVRV Buy Signal Research")
    print("=" * 70)
    print()

    # 1. Load data
    print("[1/4] Loading BTC MVRV + price history from CoinMetrics...")
    df = fetch_btc_mvrv_history()

    # Summary stats
    print()
    print("  Data range  : {} to {}".format(df.index.min().date(), df.index.max().date()))
    print("  Total days  : {:,}".format(len(df)))
    print("  MVRV range  : {:.3f} -- {:.3f}  (mean {:.3f}, median {:.3f})".format(
        df["mvrv"].min(), df["mvrv"].max(), df["mvrv"].mean(), df["mvrv"].median()
    ))
    for t in THRESHOLDS:
        n_below = int((df["mvrv"] < t).sum())
        print("  MVRV < {:.1f}  : {:,} days ({:.1f}% of history)".format(
            t, n_below, 100 * n_below / len(df)
        ))

    # Split
    df_explore  = df[df.index < SPLIT_DATE]
    df_validate = df[df.index >= SPLIT_DATE]
    print()
    print("  Exploration : {} to {} ({:,} days)".format(
        df_explore.index.min().date(), df_explore.index.max().date(), len(df_explore)
    ))
    print("  Validation  : {} to {} ({:,} days)".format(
        df_validate.index.min().date(), df_validate.index.max().date(), len(df_validate)
    ))

    # 2. Signal entry dates overview
    print()
    print("[2/4] Signal entry events (cross below threshold, 30d cooldown)...")
    for t in THRESHOLDS:
        sig = build_signal_days(df, t)
        sig_exp  = build_signal_days(df_explore, t)
        sig_val  = build_signal_days(df_validate, t)
        print("  MVRV < {:.1f}: total={:d}  exploration={:d}  validation={:d}".format(
            t, len(sig), len(sig_exp), len(sig_val)))
        print("    Dates: {}".format(
            ", ".join(d.strftime("%Y-%m") for d in sig)
        ))

    # 3. Full analysis per threshold
    print()
    print("[3/4] Forward return analysis...")

    results_full: list[dict] = []
    results_oos:  list[dict] = []

    for t in THRESHOLDS:
        print()
        print("  --- MVRV < {:.1f} ---".format(t))

        rf = analyse_threshold(df, t, label="Full 2011-2026")
        print_results(rf)
        results_full.append(rf)

        print()
        print("  --- MVRV < {:.1f} | Out-of-sample (>= {}) ---".format(t, SPLIT_DATE))
        ro = analyse_threshold(df_validate, t, label="OOS 2021-2026", verbose=False)
        print_results(ro)
        results_oos.append(ro)

    # 4. Comparison table: 0.8 vs 1.0 at 30d horizon (the decision horizon)
    print()
    print("[4/4] Threshold comparison at 30d horizon")
    print()
    print("  {:>12}  {:>8}  {:>10}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        "Threshold", "N", "Mean30d", "Base30d", "Delta", "p-val", "Win%"
    ))
    print("  " + "-" * 68)
    for rf in results_full:
        hr = rf["horizons"].get(30, {})
        if hr.get("n", 0) < 3:
            print("  MVRV < {:.1f}   {:>8d}  {:>10}  {:>8}  {:>8}  {:>8}  {:>8}".format(
                rf["threshold"], hr.get("n", 0), "N/A", "-", "-", "-", "-"
            ))
        else:
            print("  MVRV < {:.1f}   {:>8d}  {:>+9.1f}%  {:>+7.1f}%  {:>+7.1f}pp  {:>7.3f}  {:>6.0f}%".format(
                rf["threshold"],
                hr["n"],
                hr["mean"]     * 100,
                hr["baseline"] * 100,
                hr["delta"]    * 100,
                hr["pvalue"],
                hr["win_rate"] * 100,
            ))

    # 5. Verdict
    print()
    print(verdict(results_full, results_oos))

    # 6. Also print the sustained-zone stats (all days below threshold, informational)
    print()
    print("[Extra] Sustained zone stats (all days MVRV < threshold, no cooldown)")
    print("        These have high autocorrelation -- treat as descriptive only.")
    for t in THRESHOLDS:
        below_days = df[df["mvrv"] < t]
        if len(below_days) == 0:
            print("  MVRV < {:.1f}: 0 days".format(t))
            continue
        fwd30 = []
        for d in below_days.index:
            r = compute_forward_return(df, d, 30)
            if r is not None:
                fwd30.append(r)
        above_days = df[df["mvrv"] >= t]
        fwd30_base = []
        for d in above_days.index:
            r = compute_forward_return(df, d, 30)
            if r is not None:
                fwd30_base.append(r)
        arr = np.array(fwd30)
        base_arr = np.array(fwd30_base)
        if len(arr) >= 3:
            ci_lo, ci_hi = bootstrap_ci(arr)
            pval = mann_whitney_pvalue(arr, base_arr)
            print("  MVRV < {:.1f}: N={:,} days, 30d mean={:+.1f}% [CI {:+.1f},{:+.1f}], "
                  "base={:+.1f}%, delta={:+.1f}pp, p={:.3f}, WR={:.0f}%".format(
                      t, len(arr),
                      np.mean(arr) * 100,
                      ci_lo * 100, ci_hi * 100,
                      np.mean(base_arr) * 100,
                      (np.mean(arr) - np.mean(base_arr)) * 100,
                      pval,
                      np.mean(arr > 0) * 100,
                  ))
        else:
            print("  MVRV < {:.1f}: N={:,} days, insufficient".format(t, len(arr)))


if __name__ == "__main__":
    main()
