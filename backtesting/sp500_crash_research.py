"""sp500_crash_research.py
========================
Research: Do large S&P 500 weekly drops provide entry signals?

Hypothesis
----------
Similar to the BTC crash-buying signal (validated in CLAUDE.md, N=4),
large S&P 500 drawdowns might provide a buy signal with better statistical
power since there are more historical events.

Setup
-----
- Data:    yfinance ^GSPC weekly prices, 2000-01-01 to 2026-04-01
- Signals: weekly return <= -5%, -7%, -10%, -15%  (test all thresholds)
- Forward returns: 1w, 4w, 13w, 26w, 52w after signal date
- Baseline: all non-signal weeks in the same period
- Stats:    bootstrap 95% CI (N=10000), Mann-Whitney U test
- Split:    Exploration 2000-2012 / Validation 2012-2026 (same pattern as research3)
- Bonus:    Compound signal: S&P crash + BTC crash same week

Run
---
    python backtesting/sp500_crash_research.py

Output
------
Results table + CONCLUSION block (RECOMENDADO / NO IMPLEMENTAR).
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

START_DATE  = "2000-01-01"
END_DATE    = "2026-04-01"
SPLIT_DATE  = "2012-01-01"  # exploration / validation boundary

THRESHOLDS  = [-0.05, -0.07, -0.10, -0.15]  # weekly return thresholds
HORIZONS_W  = [1, 4, 13, 26, 52]            # forward look-ahead in weeks

N_BOOTSTRAP = 10_000
PVALUE_THRESHOLD = 0.05

CACHE_DIR   = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GSPC_CACHE  = CACHE_DIR / "gspc_weekly.csv"
BTC_CACHE   = CACHE_DIR / "btc_weekly_sp500.csv"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_gspc_weekly() -> pd.Series:
    """Load S&P 500 weekly closing prices. Cache to CSV."""
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    if GSPC_CACHE.exists():
        print(f"  Loading S&P 500 from cache ({GSPC_CACHE.name})...")
        df = pd.read_csv(GSPC_CACHE, index_col=0, parse_dates=True)
        return df["close"].squeeze()

    print("  Downloading S&P 500 weekly data from yfinance (2000-2026)...")
    raw = yf.download("^GSPC", start=START_DATE, end=END_DATE,
                      interval="1wk", progress=False, auto_adjust=True)
    if raw.empty:
        print("ERROR: Could not download ^GSPC data.")
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    closes = raw["Close"].dropna()
    closes.index = pd.to_datetime(closes.index)
    closes.name = "close"
    closes.to_frame().to_csv(GSPC_CACHE)
    print(f"  Saved {len(closes)} weekly bars to {GSPC_CACHE.name}")
    return closes


def load_btc_weekly() -> pd.Series:
    """Load BTC-USD weekly closing prices (2014+). Cache to CSV."""
    try:
        import yfinance as yf
    except ImportError:
        return pd.Series(dtype=float)

    if BTC_CACHE.exists():
        df = pd.read_csv(BTC_CACHE, index_col=0, parse_dates=True)
        return df["close"].squeeze()

    raw = yf.download("BTC-USD", start=START_DATE, end=END_DATE,
                      interval="1wk", progress=False, auto_adjust=True)
    if raw.empty:
        return pd.Series(dtype=float)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    closes = raw["Close"].dropna()
    closes.index = pd.to_datetime(closes.index)
    closes.name = "close"
    closes.to_frame().to_csv(BTC_CACHE)
    return closes


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
    means = np.array([
        np.mean(rng.choice(data, size=len(data), replace=True))
        for _ in range(n_boot)
    ])
    alpha = (1 - ci) / 2
    return float(np.percentile(means, alpha * 100)), float(np.percentile(means, (1 - alpha) * 100))


def mann_whitney_pvalue(signal_returns: np.ndarray, baseline_returns: np.ndarray) -> float:
    """Mann-Whitney U test p-value (two-sided). Returns 1.0 if insufficient data."""
    if len(signal_returns) < 3 or len(baseline_returns) < 3:
        return 1.0
    _, pval = stats.mannwhitneyu(signal_returns, baseline_returns, alternative="two-sided")
    return float(pval)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_forward_returns(
    prices: pd.Series,
    weekly_rets: pd.Series,
    horizon_weeks: int,
) -> pd.Series:
    """For each week, compute the forward return H weeks ahead."""
    fwd = {}
    price_arr = prices.values
    idx = prices.index

    for i, date in enumerate(idx):
        future_i = i + horizon_weeks
        if future_i < len(price_arr):
            fwd[date] = (price_arr[future_i] - price_arr[i]) / price_arr[i]

    return pd.Series(fwd)


def run_threshold_analysis(
    weekly_rets: pd.Series,
    prices: pd.Series,
    threshold: float,
    label: str = "Full",
) -> dict:
    """
    Compute signal stats for weekly_return <= threshold.

    Returns dict with results per horizon.
    """
    signal_mask = weekly_rets <= threshold
    baseline_mask = ~signal_mask

    results = {}
    for h in HORIZONS_W:
        fwd = compute_forward_returns(prices, weekly_rets, h)
        fwd = fwd.reindex(weekly_rets.index).dropna()

        sig_rets  = fwd[signal_mask & fwd.notna()].values
        base_rets = fwd[baseline_mask & fwd.notna()].values

        if len(sig_rets) < 3:
            results[h] = {
                "n":          len(sig_rets),
                "mean":       float("nan"),
                "ci_lo":      float("nan"),
                "ci_hi":      float("nan"),
                "baseline":   float(np.mean(base_rets)) if len(base_rets) > 0 else float("nan"),
                "delta":      float("nan"),
                "pvalue":     float("nan"),
                "win_rate":   float("nan"),
            }
            continue

        mean_sig   = float(np.mean(sig_rets))
        mean_base  = float(np.mean(base_rets)) if len(base_rets) > 0 else 0.0
        ci_lo, ci_hi = bootstrap_ci(sig_rets)
        pval = mann_whitney_pvalue(sig_rets, base_rets)
        win_rate = float(np.mean(sig_rets > 0))

        results[h] = {
            "n":        len(sig_rets),
            "mean":     mean_sig,
            "ci_lo":    ci_lo,
            "ci_hi":    ci_hi,
            "baseline": mean_base,
            "delta":    mean_sig - mean_base,
            "pvalue":   pval,
            "win_rate": win_rate,
        }

    results["_n_signal_weeks"] = int(signal_mask.sum())
    results["_n_total_weeks"]  = int(len(weekly_rets))
    results["_label"] = label
    return results


def check_compound_signal(
    sp500_rets: pd.Series,
    btc_rets: pd.Series,
    sp500_threshold: float = -0.07,
    btc_threshold: float = -0.10,
) -> dict:
    """Check if S&P crash + BTC crash coincide and measure forward S&P returns."""
    sp500_rets_aligned, btc_rets_aligned = sp500_rets.align(btc_rets, join="inner")
    if sp500_rets_aligned.empty:
        return {"n": 0, "note": "No overlapping data between S&P 500 and BTC"}

    compound_mask = (sp500_rets_aligned <= sp500_threshold) & (btc_rets_aligned <= btc_threshold)
    sp500_only_mask = (sp500_rets_aligned <= sp500_threshold) & ~compound_mask

    prices_aligned = (1 + sp500_rets_aligned).cumprod()  # synthetic price index

    result = {"n_compound": int(compound_mask.sum()), "n_sp500_only": int(sp500_only_mask.sum())}

    for label, mask in [("compound", compound_mask), ("sp500_only", sp500_only_mask)]:
        if mask.sum() < 3:
            result[label] = {"n": int(mask.sum()), "data": "insufficient"}
            continue
        fwd_4w = compute_forward_returns(prices_aligned, sp500_rets_aligned, 4)
        fwd_4w = fwd_4w.reindex(sp500_rets_aligned.index).dropna()
        sig_rets = fwd_4w[mask & fwd_4w.notna()].values
        base_rets = fwd_4w[~mask & fwd_4w.notna()].values
        result[label] = {
            "n":       len(sig_rets),
            "mean_4w": float(np.mean(sig_rets)) if len(sig_rets) > 0 else float("nan"),
            "baseline_4w": float(np.mean(base_rets)) if len(base_rets) > 0 else float("nan"),
        }

    return result


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _pct(x: float) -> str:
    if x != x:  # nan
        return "   N/A "
    return f"{x*100:+5.1f}%"


def _pval_str(p: float) -> str:
    if p != p:
        return "  N/A "
    if p < 0.001:
        return " <.001"
    return f" {p:.3f}"


def print_results_table(
    threshold: float,
    full_res: dict,
    expl_res: dict,
    val_res:  dict,
) -> None:
    n_sig = full_res.get("_n_signal_weeks", 0)
    n_tot = full_res.get("_n_total_weeks", 0)
    print(f"\n  Threshold: weekly return <= {threshold*100:.0f}%  |  N={n_sig} eventos / {n_tot} semanas totales")
    print(f"\n  {'H':>4}  {'Mean':>7}  {'CI-Lo':>7}  {'CI-Hi':>7}  {'Baseline':>8}  {'Delta':>7}  {'p-value':>7}  {'WinRate':>7}")
    print(f"  {'-'*4}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*7}")

    for h in HORIZONS_W:
        r = full_res.get(h, {})
        mean = r.get("mean", float("nan"))
        ci_lo = r.get("ci_lo", float("nan"))
        ci_hi = r.get("ci_hi", float("nan"))
        base  = r.get("baseline", float("nan"))
        delta = r.get("delta", float("nan"))
        pval  = r.get("pvalue", float("nan"))
        wr    = r.get("win_rate", float("nan"))
        wr_s  = f"{wr*100:.0f}%" if wr == wr else " N/A"
        print(f"  {h:>4}w {_pct(mean):>7}  {_pct(ci_lo):>7}  {_pct(ci_hi):>7}  {_pct(base):>8}  {_pct(delta):>7}  {_pval_str(pval):>7}  {wr_s:>7}")

    # Exploration / Validation
    expl_n = expl_res.get("_n_signal_weeks", 0)
    val_n  = val_res.get("_n_signal_weeks", 0)
    print(f"\n  --- Out-of-sample split (exploration 2000-2012 / validation 2012-2026) ---")
    print(f"  {'H':>4}  {'Expl mean (N='+ str(expl_n)+')':>18}  {'Val mean (N='+ str(val_n)+')':>18}")
    for h in HORIZONS_W:
        expl_m = expl_res.get(h, {}).get("mean", float("nan"))
        val_m  = val_res.get(h,  {}).get("mean", float("nan"))
        print(f"  {h:>4}w  {_pct(expl_m):>18}  {_pct(val_m):>18}")


def print_compound_results(comp: dict) -> None:
    print(f"\n  --- Senal compuesta: S&P <= -7% Y BTC <= -10% misma semana ---")
    n_comp = comp.get("n_compound", 0)
    n_sp   = comp.get("n_sp500_only", 0)
    print(f"  Eventos compuestos: {n_comp}  |  Solo S&P: {n_sp}")

    for key, label in [("compound", "Compuesta"), ("sp500_only", "Solo S&P")]:
        d = comp.get(key, {})
        if isinstance(d, dict) and d.get("data") != "insufficient":
            n   = d.get("n", 0)
            m4  = d.get("mean_4w", float("nan"))
            b4  = d.get("baseline_4w", float("nan"))
            delta = m4 - b4 if (m4 == m4 and b4 == b4) else float("nan")
            print(f"  {label} (N={n}): 4w mean={_pct(m4)}, baseline={_pct(b4)}, delta={_pct(delta)}")
        else:
            print(f"  {label}: datos insuficientes (N<3)")


def print_conclusion(all_results: dict[float, dict]) -> None:
    """Print actionable conclusion based on p-values and consistency."""
    print(f"\n{'='*60}")
    print("CONCLUSION")
    print(f"{'='*60}")

    strong_signals: list[str] = []
    for threshold, results in all_results.items():
        expl = results["expl"]
        val  = results["val"]
        # Check if the 4w and 13w horizons are consistently positive and significant
        for h in [4, 13]:
            full_r = results["full"].get(h, {})
            pval   = full_r.get("pvalue", 1.0)
            delta  = full_r.get("delta", 0.0)
            expl_m = expl.get(h, {}).get("mean", float("nan"))
            val_m  = val.get(h, {}).get("mean", float("nan"))
            consistent = (expl_m == expl_m and val_m == val_m and
                          expl_m > 0 and val_m > 0)
            if pval < PVALUE_THRESHOLD and delta > 0 and consistent:
                strong_signals.append(
                    f"  threshold={threshold*100:.0f}% horizon={h}w: "
                    f"p={pval:.3f}, delta={_pct(delta)}, consistente en ambos splits"
                )

    if strong_signals:
        print("\n  RECOMENDADO: Hay evidencia estadistica de edge.")
        print("  Considerar anadir alerta Discord para S&P 500 crash:")
        for s in strong_signals:
            print(s)
        print("\n  Nota: verificar que el edge no es atribuible a 2008 o COVID unicamente.")
        print("  Antes de implementar: revisar si las condiciones del mercado actual difieren.")
    else:
        print("\n  NO IMPLEMENTAR: No se encontro edge estadisticamente significativo")
        print("  y/o consistente entre periodos de exploracion y validacion.")
        print("\n  Razones posibles:")
        print("  - El S&P 500 se recupera de forma menos predecible que BTC post-crash")
        print("  - N de eventos puede ser insuficiente para algunos thresholds")
        print("  - La senal no generaliza fuera del periodo de entrenamiento")
        print("\n  Recomendacion: mantener el Sparplan S&P 500 sin alertas extra.")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("S&P 500 Crash Signal Research")
    print("=" * 60)
    print(f"  Periodo: {START_DATE} a {END_DATE}")
    print(f"  Thresholds: {[f'{t*100:.0f}%' for t in THRESHOLDS]}")
    print(f"  Horizontes forward: {HORIZONS_W} semanas")
    print(f"  Bootstrap CI: {N_BOOTSTRAP} iteraciones")
    print(f"  Split: exploracion 2000-2012 / validacion 2012-2026")
    print()

    # Load data
    print("Cargando datos...")
    gspc_prices = load_gspc_weekly()
    btc_prices  = load_btc_weekly()

    # Filter to date range
    gspc_prices = gspc_prices.loc[START_DATE:END_DATE]
    if not btc_prices.empty:
        btc_prices = btc_prices.loc[START_DATE:END_DATE]

    gspc_rets = gspc_prices.pct_change().dropna()
    btc_rets  = btc_prices.pct_change().dropna() if not btc_prices.empty else pd.Series(dtype=float)

    print(f"  S&P 500: {len(gspc_prices)} semanas ({gspc_prices.index.min().date()} a {gspc_prices.index.max().date()})")
    if not btc_rets.empty:
        print(f"  BTC:     {len(btc_prices)} semanas ({btc_prices.index.min().date()} a {btc_prices.index.max().date()})")

    # Split masks
    expl_mask = gspc_rets.index < SPLIT_DATE
    val_mask  = gspc_rets.index >= SPLIT_DATE

    all_results: dict[float, dict] = {}

    for threshold in THRESHOLDS:
        print(f"\n{'='*60}")
        print(f"THRESHOLD: weekly return <= {threshold*100:.0f}%")
        print(f"{'='*60}")

        full_res = run_threshold_analysis(gspc_rets, gspc_prices, threshold, label="Full 2000-2026")
        expl_res = run_threshold_analysis(
            gspc_rets[expl_mask], gspc_prices.reindex(gspc_rets[expl_mask].index),
            threshold, label="Expl 2000-2012"
        )
        val_res  = run_threshold_analysis(
            gspc_rets[val_mask], gspc_prices.reindex(gspc_rets[val_mask].index),
            threshold, label="Val 2012-2026"
        )

        print_results_table(threshold, full_res, expl_res, val_res)
        all_results[threshold] = {"full": full_res, "expl": expl_res, "val": val_res}

    # Compound signal
    if not btc_rets.empty:
        print(f"\n{'='*60}")
        print("SENAL COMPUESTA (S&P crash + BTC crash)")
        print(f"{'='*60}")
        comp = check_compound_signal(gspc_rets, btc_rets)
        print_compound_results(comp)

    # Conclusion
    print_conclusion(all_results)


if __name__ == "__main__":
    main()
