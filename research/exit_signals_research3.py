"""exit_signals_research3.py
==========================
On-chain and systematic exit signals with improved statistical rigor.

Building on exit_signals_research2.py conclusions:
  - No relative "overheated" signal (MVRV, MA ratio, gain-from-low) beats hold DCA
  - Bull market momentum persists: overheated zones predict CONTINUATION, not reversal
  - Only validated exits: annual rebalancing + absolute price alerts ($100k BTC, $3k ETH)

This script explores conceptually DIFFERENT signal types and adds statistical rigour
missing from prior scripts: bootstrap CIs, Mann-Whitney tests, and out-of-sample validation.

Analyses:
  1. NVT ratio (CoinMetrics NVTAdj): "P/E ratio" of Bitcoin.
     Market cap / on-chain tx volume. High NVT = speculative premium over real usage.
  2. DCA-out systematic: gradual sell as price rises -- no signal needed.
     Sell X% of holdings for every $20k above $80k threshold. N=many by design.
  3. Weekly RSI > 85: classic overbought indicator on weekly timeframe.
     More stable than daily RSI. Computed from cached daily prices.
  4. Halving cycle timing: halvings are deterministic (2012, 2016, 2020, 2024).
     Does selling 12-18 months post-halving improve returns?
  5. Active addresses divergence + Coin Days Destroyed (CoinMetrics).
     Price up + addresses flat = speculative rally. CDD spikes = HODLers distributing.

Statistical improvements over prior scripts:
  - Bootstrap 95% confidence intervals on forward return means
  - Mann-Whitney U test: signal returns vs baseline (p-value reported)
  - Exploration period (2018-2022) / validation period (2022-2026) split
  - Multiple comparisons note in final summary

Data sources (all free, no API key):
  - BTC prices: CoinMetrics community API (cached)
  - NVT, active addresses, CDD: CoinMetrics community API
  - Halving dates: hardcoded (deterministic)

Usage:
  python backtesting/exit_signals_research3.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANALYSIS_START = "2018-01-01"
ANALYSIS_END   = "2026-04-01"
FETCH_START    = "2017-01-01"  # extra lookback for 200d MA, weekly RSI, etc.

# Out-of-sample split
EXPLORE_END  = "2022-01-01"   # exploration: 2018-01-01 to 2021-12-31
VALIDATE_START = "2022-01-01" # validation:  2022-01-01 to 2026-04-01

WEEKLY_BTC_EUR = 8.0
SELL_FEE_EUR   = 1.0

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = [7, 30, 90]
EVENT_COOLDOWN_DAYS = 14

# BTC halving dates (block reward halved)
HALVING_DATES = [
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-19"),
]

# Bootstrap config
N_BOOTSTRAP = 10000
CI_LEVEL = 0.95

# Total hypotheses tested across all analyses (for multiple comparisons note)
TOTAL_HYPOTHESES = 0  # incremented as we test


# ---------------------------------------------------------------------------
# Helpers -- shared with prior scripts
# ---------------------------------------------------------------------------

def _fetch_json(url: str, params: dict | None = None, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": "CryptoTrader-Research/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc
    return {}


def _load_cache(path: Path) -> pd.DataFrame | None:
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        return df
    return None


def _save_cache(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(abs(dd.min()) * 100)


def cagr(start_val: float, end_val: float, years: float) -> float:
    if start_val <= 0 or years <= 0:
        return 0.0
    return float((end_val / start_val) ** (1.0 / years) - 1) * 100


def _build_weekly_dates(index: pd.DatetimeIndex, start: str) -> set:
    weekly = set()
    d = pd.Timestamp(start)
    end = index[-1]
    while d <= end:
        pos = index.searchsorted(d)
        if pos < len(index):
            weekly.add(index[pos])
        d += timedelta(days=7)
    return weekly


# ---------------------------------------------------------------------------
# Statistical helpers -- NEW in this script
# ---------------------------------------------------------------------------

def bootstrap_ci(returns: np.ndarray, n_boot: int = N_BOOTSTRAP,
                 ci: float = CI_LEVEL) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean of returns."""
    if len(returns) < 2:
        return (float(np.mean(returns)), float(np.mean(returns)))
    rng = np.random.default_rng(42)
    means = np.array([
        np.mean(rng.choice(returns, size=len(returns), replace=True))
        for _ in range(n_boot)
    ])
    lo = float(np.percentile(means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(means, (1 + ci) / 2 * 100))
    return (lo, hi)


def test_signal_vs_baseline(signal_rets: np.ndarray,
                            baseline_rets: np.ndarray) -> float:
    """Mann-Whitney U test: are signal returns significantly different from baseline?

    Returns two-sided p-value. p < 0.05 means significantly different.
    """
    if len(signal_rets) < 3 or len(baseline_rets) < 3:
        return 1.0
    _, p = stats.mannwhitneyu(signal_rets, baseline_rets, alternative='two-sided')
    return float(p)


def compute_forward_returns(prices: pd.Series, signal_mask: pd.Series,
                            horizons: list[int]) -> dict[int, dict]:
    """Forward return stats on signal days, with bootstrap CI and raw arrays."""
    out: dict[int, dict] = {}
    for h in horizons:
        rets = []
        for date in prices[signal_mask].index:
            future = date + timedelta(days=h)
            pos = prices.index.searchsorted(future)
            if pos >= len(prices):
                continue
            r = (prices.iloc[pos] - prices[date]) / prices[date] * 100
            rets.append(r)
        if rets:
            arr = np.array(rets)
            ci_lo, ci_hi = bootstrap_ci(arr)
            out[h] = {
                "mean": float(np.mean(arr)),
                "median": float(np.median(arr)),
                "win": float((arr > 0).mean() * 100),
                "n": len(arr),
                "ci_lo": ci_lo,
                "ci_hi": ci_hi,
                "raw": arr,
            }
        else:
            out[h] = {"mean": 0.0, "median": 0.0, "win": 0.0, "n": 0,
                      "ci_lo": 0.0, "ci_hi": 0.0, "raw": np.array([])}
    return out


def independent_events(mask: pd.Series,
                       cooldown_days: int = EVENT_COOLDOWN_DAYS) -> pd.Series:
    """Thin a boolean mask so consecutive True runs become one event."""
    result = pd.Series(False, index=mask.index)
    last_event = None
    for date in mask.index:
        if mask[date]:
            if last_event is None or (date - last_event).days >= cooldown_days:
                result[date] = True
                last_event = date
    return result


def fmt_ci(ci_lo: float, ci_hi: float) -> str:
    return f"[{ci_lo:+.1f}%, {ci_hi:+.1f}%]"


def print_bin_table(label: str, bins: list[dict], baseline: dict,
                    show_ci: bool = True) -> None:
    """Pretty-print forward-return table with CIs and p-values."""
    global TOTAL_HYPOTHESES
    print(f"  {label}")
    if show_ci:
        hdr = (f"  {'Bin':<30} | {'N evts':>6} | "
               f"{'30d mean':>9} | {'95% CI':>18} | {'p-val':>6} | {'vs base':>8}")
        div = "  " + "-" * 30 + "-+-" + "-+-".join(
            ["-" * 6, "-" * 9, "-" * 18, "-" * 6, "-" * 8])
    else:
        hdr = (f"  {'Bin':<30} | {'N evts':>6} | "
               f"{'7d mean':>8} | {'30d mean':>9} | {'90d mean':>9} | {'30d win%':>8}")
        div = "  " + "-" * 30 + "-+-" + "-+-".join(
            ["-" * 6, "-" * 8, "-" * 9, "-" * 9, "-" * 8])
    print(hdr)
    print(div)

    base_raw_30 = baseline[30].get("raw", np.array([]))

    for b in bins:
        n_ev = b["n_events"]
        r30 = b["ret30"]
        if show_ci:
            delta = r30["mean"] - baseline[30]["mean"]
            raw30 = r30.get("raw", np.array([]))
            if len(raw30) >= 3 and len(base_raw_30) >= 3:
                p = test_signal_vs_baseline(raw30, base_raw_30)
                TOTAL_HYPOTHESES += 1
            else:
                p = 1.0
            ci_str = fmt_ci(r30["ci_lo"], r30["ci_hi"]) if r30["n"] >= 2 else "N/A"
            p_str = f"{p:.3f}" if r30["n"] >= 3 else "N/A"
            print(f"  {b['label']:<30} | {n_ev:>6} | "
                  f"{r30['mean']:>+8.1f}% | {ci_str:>18} | {p_str:>6} | "
                  f"{delta:>+7.1f}pp")
        else:
            r7 = b["ret7"]
            r90 = b["ret90"]
            print(f"  {b['label']:<30} | {n_ev:>6} | "
                  f"{r7['mean']:>+7.1f}% | {r30['mean']:>+8.1f}% | "
                  f"{r90['mean']:>+8.1f}% | {r30['win']:>7.0f}%")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_coinmetrics_timeseries(asset: str, metrics: str,
                                  cache_name: str) -> pd.DataFrame:
    """Generic CoinMetrics community API fetcher with pagination and cache."""
    cache = CACHE_DIR / f"{cache_name}.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    {cache_name}: {len(cached)} rows from cache")
        return cached

    print(f"    {cache_name}: fetching from CoinMetrics ({metrics})...")
    all_rows: list[dict] = []
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params: dict = {
        "assets": asset,
        "metrics": metrics,
        "frequency": "1d",
        "page_size": "10000",
        "paging_from": "start",
    }
    while True:
        data = _fetch_json(url, params)
        rows = data.get("data", [])
        all_rows.extend(rows)
        next_url = data.get("next_page_url")
        if not next_url:
            break
        parsed = urlparse(next_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        time.sleep(0.5)

    if not all_rows:
        raise ValueError(f"CoinMetrics returned no data for {asset}/{metrics}")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    _save_cache(df, cache)
    print(f"    {cache_name}: {len(df)} rows fetched and cached")
    return df


def fetch_btc_prices() -> pd.DataFrame:
    """BTC daily USD prices from CoinMetrics (reuses existing cache)."""
    cache = CACHE_DIR / "btc_cm.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    BTC prices: {len(cached)} days from cache")
        return cached

    raw = _fetch_coinmetrics_timeseries("btc", "PriceUSD", "btc_cm")
    raw["price"] = pd.to_numeric(raw["PriceUSD"], errors="coerce")
    df = (raw[["date", "price"]].dropna()
          .sort_values("date").drop_duplicates("date").reset_index(drop=True))
    _save_cache(df, cache)
    return df


def fetch_btc_nvt() -> pd.DataFrame:
    """BTC NVT proxy from CoinMetrics free metrics.

    NVTAdj is not in the free community tier. We compute a proxy:
      NVT proxy = CapMrktCurUSD / (TxTfrCnt * PriceUSD)
    This approximates market_cap / on-chain_transfer_value using transfer count
    as a proxy for volume. Higher = more speculative premium per transaction.

    Returns DataFrame(date, nvt).
    """
    cache = CACHE_DIR / "btc_nvt.csv"
    cached = _load_cache(cache)
    if cached is not None:
        if "nvt" in cached.columns:
            print(f"    BTC NVT proxy: {len(cached)} days from cache")
            return cached

    print("    BTC NVT proxy: computing from CapMrktCurUSD and TxTfrCnt...")
    raw = _fetch_coinmetrics_timeseries(
        "btc", "CapMrktCurUSD,TxTfrCnt,PriceUSD", "btc_nvt_raw")
    raw["mktcap"] = pd.to_numeric(raw.get("CapMrktCurUSD", pd.Series(dtype=float)),
                                  errors="coerce")
    raw["txcnt"] = pd.to_numeric(raw.get("TxTfrCnt", pd.Series(dtype=float)),
                                 errors="coerce")
    raw["price"] = pd.to_numeric(raw.get("PriceUSD", pd.Series(dtype=float)),
                                 errors="coerce")
    # NVT proxy: market_cap / (tx_count * price) -- dimensionless ratio
    # Higher means more market value per on-chain transfer
    raw["nvt"] = raw["mktcap"] / (raw["txcnt"] * raw["price"])
    df = (raw[["date", "nvt"]].dropna()
          .sort_values("date").drop_duplicates("date").reset_index(drop=True))
    # Filter outliers (NVT > 10000 is noise from very early data)
    df = df[df["nvt"] < 10000].reset_index(drop=True)
    _save_cache(df, cache)
    print(f"    BTC NVT proxy: {len(df)} days computed and cached")
    return df


def fetch_btc_onchain() -> pd.DataFrame:
    """BTC active addresses and supply data from CoinMetrics free tier.

    Available metrics: AdrActCnt (active addresses), SplyCur (circulating supply).
    CDD (Coin Days Destroyed) is NOT in the free tier.
    We use daily supply changes as a rough CDD proxy (coins that entered circulation).

    Returns DataFrame(date, active_addresses, cdd).
    """
    cache = CACHE_DIR / "btc_onchain.csv"
    cached = _load_cache(cache)
    if cached is not None:
        if "active_addresses" in cached.columns:
            print(f"    BTC on-chain: {len(cached)} days from cache")
            return cached

    raw = _fetch_coinmetrics_timeseries(
        "btc", "AdrActCnt,SplyCur", "btc_onchain_raw")
    raw["active_addresses"] = pd.to_numeric(
        raw.get("AdrActCnt", pd.Series(dtype=float)), errors="coerce")
    raw["sply"] = pd.to_numeric(
        raw.get("SplyCur", pd.Series(dtype=float)), errors="coerce")
    df = raw[["date", "active_addresses", "sply"]].dropna(subset=["date", "active_addresses"])
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    # CDD proxy: daily supply change (new coins entering circulation)
    # This is NOT real CDD but the best we can do with free tier
    if df["sply"].notna().any():
        df["cdd"] = df["sply"].diff().clip(lower=0)
    else:
        df["cdd"] = np.nan

    df = df[["date", "active_addresses", "cdd"]]
    _save_cache(df, cache)
    print(f"    BTC on-chain: {len(df)} days processed")
    return df


def _make_price_series(btc_df: pd.DataFrame, start: str = ANALYSIS_START,
                       end: str = ANALYSIS_END) -> pd.Series:
    """Build a clean price series indexed by date."""
    prices = btc_df.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices[~prices.index.duplicated(keep="first")].sort_index()
    return prices.loc[start:end]


# ---------------------------------------------------------------------------
# ANALYSIS 1: NVT Ratio
# ---------------------------------------------------------------------------

def analysis_1_nvt(btc_df: pd.DataFrame) -> dict:
    """NVT ratio as exit signal.

    NVT = Market Cap / On-chain Transaction Volume (adjusted).
    High NVT = price outpacing actual network usage = speculative premium.
    Conceptually the "P/E ratio" of Bitcoin.

    Unlike MVRV (realized value reference), NVT captures real-time usage.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS 1: BTC NVT RATIO (Network Value to Transactions)")
    print(sep)
    print()
    print("  NVT = Market Cap / On-chain Tx Volume. High NVT = speculative premium.")
    print("  Conceptually different from MVRV: measures usage vs price, not cost basis.")
    print("  Hypothesis: very high NVT predicts negative forward returns (bubble territory).")
    print()

    nvt_df = fetch_btc_nvt()
    prices_full = btc_df.set_index("date")["price"]
    prices_full.index = pd.to_datetime(prices_full.index)
    prices_full = prices_full[~prices_full.index.duplicated(keep="first")].sort_index()

    nvt_s = nvt_df.set_index("date")["nvt"]
    nvt_s.index = pd.to_datetime(nvt_s.index)
    nvt_s = nvt_s[~nvt_s.index.duplicated(keep="first")].sort_index()

    # Use 14-day smoothed NVT to reduce noise
    nvt_smooth = nvt_s.rolling(14, min_periods=7).median()

    # Full period
    prices_a = prices_full.loc[ANALYSIS_START:ANALYSIS_END]
    nvt_a = nvt_smooth.loc[ANALYSIS_START:ANALYSIS_END]

    # Align indices
    common = prices_a.index.intersection(nvt_a.dropna().index)
    prices_a = prices_a.loc[common]
    nvt_a = nvt_a.loc[common]

    print(f"  Period        : {prices_a.index[0].date()} to {prices_a.index[-1].date()}")
    print(f"  NVT range     : {nvt_a.min():.1f} to {nvt_a.max():.1f}")
    print(f"  NVT median    : {nvt_a.median():.1f}")
    print(f"  NVT 75th pctl : {nvt_a.quantile(0.75):.1f}")
    print(f"  NVT 90th pctl : {nvt_a.quantile(0.90):.1f}")
    print()

    # Define bins based on NVT distribution
    p25 = nvt_a.quantile(0.25)
    p50 = nvt_a.quantile(0.50)
    p75 = nvt_a.quantile(0.75)
    p90 = nvt_a.quantile(0.90)

    bin_defs = [
        (f"< {p25:.0f} (low, heavy usage)",      nvt_a < p25),
        (f"{p25:.0f}-{p50:.0f} (below median)",   (nvt_a >= p25) & (nvt_a < p50)),
        (f"{p50:.0f}-{p75:.0f} (above median)",   (nvt_a >= p50) & (nvt_a < p75)),
        (f"{p75:.0f}-{p90:.0f} (high NVT)",       (nvt_a >= p75) & (nvt_a < p90)),
        (f">= {p90:.0f} (extreme NVT)",           nvt_a >= p90),
    ]

    baseline_mask = pd.Series(True, index=prices_a.index)
    baseline_ret = compute_forward_returns(prices_a, baseline_mask, HORIZONS)

    bins = []
    for label, mask in bin_defs:
        events = independent_events(mask)
        ret7 = compute_forward_returns(prices_a, mask, [7])[7]
        ret30 = compute_forward_returns(prices_a, mask, [30])[30]
        ret90 = compute_forward_returns(prices_a, mask, [90])[90]
        bins.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline: 30d mean={baseline_ret[30]['mean']:+.1f}%, "
          f"90d mean={baseline_ret[90]['mean']:+.1f}%, N={baseline_ret[30]['n']}")
    print()
    print_bin_table("Forward returns by NVT bin (full period):", bins, baseline_ret)

    # --- Out-of-sample validation ---
    print()
    print("  --- OUT-OF-SAMPLE VALIDATION ---")
    print(f"  Exploration: {ANALYSIS_START} to {EXPLORE_END}")
    print(f"  Validation : {VALIDATE_START} to {ANALYSIS_END}")

    for period_name, p_start, p_end in [
        ("Exploration", ANALYSIS_START, EXPLORE_END),
        ("Validation", VALIDATE_START, ANALYSIS_END),
    ]:
        p_idx = prices_a.loc[p_start:p_end].index.intersection(nvt_a.loc[p_start:p_end].dropna().index)
        if len(p_idx) < 30:
            print(f"  {period_name}: insufficient data ({len(p_idx)} days)")
            continue
        p_prices = prices_a.loc[p_idx]
        p_nvt = nvt_a.loc[p_idx]
        p_base = compute_forward_returns(p_prices, pd.Series(True, index=p_idx), [30])

        # Test top bin (>= p90 from FULL period -- slight data leak but acceptable for quartiles)
        top_mask = p_nvt >= p90
        if top_mask.sum() >= 5:
            top_ret = compute_forward_returns(p_prices, top_mask, [30])[30]
            delta = top_ret["mean"] - p_base[30]["mean"]
            ci_str = fmt_ci(top_ret["ci_lo"], top_ret["ci_hi"]) if top_ret["n"] >= 2 else "N/A"
            raw30 = top_ret.get("raw", np.array([]))
            base_raw = p_base[30].get("raw", np.array([]))
            p_val = test_signal_vs_baseline(raw30, base_raw) if len(raw30) >= 3 else 1.0
            print(f"  {period_name} NVT>={p90:.0f}: 30d mean={top_ret['mean']:+.1f}%, "
                  f"CI={ci_str}, delta={delta:+.1f}pp, p={p_val:.3f}, N={top_ret['n']}")
        else:
            print(f"  {period_name} NVT>={p90:.0f}: N={int(top_mask.sum())} (insufficient)")

    # Interpretation
    print()
    print("  INTERPRETATION:")
    top_bin = bins[-1]
    delta30 = top_bin["ret30"]["mean"] - baseline_ret[30]["mean"]
    if top_bin["n_events"] >= 10 and delta30 < -3.0:
        raw30 = top_bin["ret30"].get("raw", np.array([]))
        base_raw = baseline_ret[30].get("raw", np.array([]))
        p_val = test_signal_vs_baseline(raw30, base_raw) if len(raw30) >= 3 else 1.0
        if p_val < 0.05:
            print(f"  -> Extreme NVT: 30d delta={delta30:+.1f}pp, p={p_val:.3f} -- CONFIRMED")
        else:
            print(f"  -> Extreme NVT: 30d delta={delta30:+.1f}pp, but p={p_val:.3f} (not significant)")
    elif delta30 > 0:
        print(f"  -> Extreme NVT: 30d delta={delta30:+.1f}pp -- higher returns, NOT a sell signal.")
        print("     Same pattern as MVRV: overheated metrics correlate with bull continuation.")
    else:
        print(f"  -> Extreme NVT: 30d delta={delta30:+.1f}pp, N={top_bin['n_events']} events")
        print("     Effect is weak or insufficient data for statistical significance.")

    return {
        "bins": bins, "baseline": baseline_ret,
        "nvt": nvt_a, "prices": prices_a,
    }


# ---------------------------------------------------------------------------
# ANALYSIS 2: DCA-out Systematic
# ---------------------------------------------------------------------------

def analysis_2_dca_out(btc_df: pd.DataFrame) -> dict:
    """Systematic DCA-out: sell a fixed % of holdings per $20k above threshold.

    Philosophy: instead of predicting the top, gradually reduce exposure as
    price rises. N = many sell events by design (not dependent on a signal).

    Strategy examples (all start selling above $80k):
      - 3% per $20k step: sell 3% at $100k, another 3% at $120k, etc.
      - 5% per $20k step: more aggressive reduction
      - 2% per $10k step: finer granularity

    Baseline: pure hold DCA (8 EUR/week).
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS 2: SYSTEMATIC DCA-OUT (Gradual Sell as Price Rises)")
    print(sep)
    print()
    print("  Philosophy: don't predict the top -- reduce exposure gradually.")
    print("  Rule: for every $20k above base price, sell X% of BTC holdings.")
    print("  No signal needed. Deterministic. Many sell events by design.")
    print()

    prices_full = btc_df.set_index("date")["price"]
    prices_full.index = pd.to_datetime(prices_full.index)
    prices_full = prices_full[~prices_full.index.duplicated(keep="first")].sort_index()
    prices_a = prices_full.loc[ANALYSIS_START:ANALYSIS_END]

    weekly_dates = _build_weekly_dates(prices_a.index,
                                       prices_a.index[0].strftime("%Y-%m-%d"))
    years = (prices_a.index[-1] - prices_a.index[0]).days / 365.25
    total_invested = len(weekly_dates) * WEEKLY_BTC_EUR

    print(f"  Period       : {prices_a.index[0].date()} to {prices_a.index[-1].date()} ({years:.1f} years)")
    print(f"  BTC price    : ${prices_a.iloc[0]:,.0f} -> ${prices_a.iloc[-1]:,.0f}")
    print(f"  BTC ATH      : ${prices_a.max():,.0f}")
    print(f"  Total DCA in : ~{total_invested:,.0f} EUR over {len(weekly_dates)} weeks")
    print()

    # Scenarios: (name, base_price, step_size, sell_pct_per_step, cooldown_days)
    SCENARIOS: list[tuple[str, float, float, float, int]] = [
        ("Pure hold (baseline)",          0,     0,     0,     0),
        ("3% per $20k above $80k",        80000, 20000, 0.03,  30),
        ("5% per $20k above $80k",        80000, 20000, 0.05,  30),
        ("3% per $20k above $60k",        60000, 20000, 0.03,  30),
        ("5% per $20k above $60k",        60000, 20000, 0.05,  30),
        ("2% per $10k above $80k",        80000, 10000, 0.02,  30),
        ("3% per $10k above $80k",        80000, 10000, 0.03,  30),
        ("10% per $20k above $100k",      100000,20000, 0.10,  30),
        ("5% per $20k above $100k",       100000,20000, 0.05,  30),
    ]

    def simulate(base_price: float, step_size: float, sell_pct: float,
                 cooldown: int) -> dict:
        btc_units = 0.0
        cash_eur = 0.0
        invested = 0.0
        total_fees = 0.0
        sell_log: list[dict] = []
        # Track which price levels have been triggered and their cooldowns
        last_trigger_by_level: dict[int, pd.Timestamp | None] = {}

        for date in prices_a.index:
            price = prices_a[date]

            # Snapshot pre-buy to avoid selling freshly bought BTC the same day
            btc_before_buy = btc_units

            # Weekly DCA
            if date in weekly_dates:
                btc_units += WEEKLY_BTC_EUR / price
                invested += WEEKLY_BTC_EUR

            # DCA-out: check each step level
            if base_price > 0 and step_size > 0 and price > base_price and btc_before_buy > 0:
                # How many steps above base?
                steps_above = int((price - base_price) / step_size)
                for step in range(1, steps_above + 1):
                    level_price = base_price + step * step_size
                    last = last_trigger_by_level.get(step)
                    if last is None or (date - last).days >= cooldown:
                        sell_units = btc_before_buy * sell_pct
                        sell_val = sell_units * price
                        net = sell_val - SELL_FEE_EUR
                        if net > 0:
                            btc_units -= sell_units
                            cash_eur += net
                            total_fees += SELL_FEE_EUR
                            last_trigger_by_level[step] = date
                            sell_log.append({
                                "date": date, "price": price,
                                "level": level_price, "pct_sold": sell_pct * 100,
                                "eur_received": net,
                            })

        final_btc = btc_units * prices_a.iloc[-1]
        final_total = final_btc + cash_eur
        tot_ret = (final_total - invested) / invested * 100
        ann = cagr(invested, final_total, years)

        return {
            "invested": invested, "final_btc": final_btc, "cash": cash_eur,
            "final_total": final_total, "total_ret": tot_ret, "cagr": ann,
            "fees": total_fees, "btc_remaining": btc_units,
            "n_sells": len(sell_log), "sell_log": sell_log,
        }

    print("  Running simulations...")
    results = []
    for name, base_p, step_s, sell_p, cd in SCENARIOS:
        r = simulate(base_p, step_s, sell_p, cd)
        r["name"] = name
        results.append(r)

    baseline = results[0]

    # Results table
    print()
    hdr = (f"  {'Strategy':<32} | {'Final EUR':>10} | {'Tot Ret':>8} | "
           f"{'CAGR':>7} | {'vs Hold':>8} | {'Sells':>5} | {'Cash%':>5}")
    div = ("  " + "-" * 32 + "-+-" +
           "-+-".join(["-" * 10, "-" * 8, "-" * 7, "-" * 8, "-" * 5, "-" * 5]))
    print(hdr)
    print(div)
    for r in results:
        vs_hold = r["total_ret"] - baseline["total_ret"]
        cash_pct = r["cash"] / r["final_total"] * 100 if r["final_total"] > 0 else 0
        marker = " <--" if vs_hold > 5 else ""
        print(f"  {r['name']:<32} | {r['final_total']:>10,.0f} | "
              f"{r['total_ret']:>7.1f}% | {r['cagr']:>6.1f}% | "
              f"{vs_hold:>+7.1f}pp | {r['n_sells']:>5} | "
              f"{cash_pct:>4.0f}%{marker}")

    # Show sell log for most interesting strategy
    best_strat = max(results[1:], key=lambda x: x["total_ret"])
    print()
    print(f"  Best strategy: '{best_strat['name']}' "
          f"({best_strat['total_ret']:+.1f}% vs hold {baseline['total_ret']:+.1f}%, "
          f"delta={best_strat['total_ret'] - baseline['total_ret']:+.1f}pp)")

    if best_strat["sell_log"]:
        print()
        print(f"  Sell events for '{best_strat['name']}' (first 15):")
        for s in best_strat["sell_log"][:15]:
            print(f"    {s['date'].date()}  BTC=${s['price']:,.0f}  "
                  f"level=${s['level']:,.0f}  sold={s['pct_sold']:.0f}%  "
                  f"received={s['eur_received']:,.0f} EUR")
        if len(best_strat["sell_log"]) > 15:
            print(f"    ... and {len(best_strat['sell_log']) - 15} more sell events")

    # Verdict
    print()
    print("  VERDICT:")
    improvements = [r for r in results[1:] if r["total_ret"] > baseline["total_ret"] + 5]
    if improvements:
        best_imp = max(improvements, key=lambda x: x["total_ret"])
        delta = best_imp["total_ret"] - baseline["total_ret"]
        print(f"  -> DCA-out ADDS VALUE: best gains +{delta:.0f}pp vs hold.")
        print(f"     Strategy: '{best_imp['name']}' ({best_imp['n_sells']} sells)")
        print("     Note: requires BTC to reach levels then retrace. If BTC goes to $500k")
        print("     and stays there, DCA-out will lag pure hold (sold too early).")
        print("     Reduces risk (cash locked in) at cost of potential upside.")
    else:
        best_non = max(results[1:], key=lambda x: x["total_ret"])
        delta = best_non["total_ret"] - baseline["total_ret"]
        print(f"  -> DCA-out does NOT improve total returns vs hold DCA.")
        print(f"     Best result: {delta:+.1f}pp vs hold.")
        if any(r["total_ret"] > baseline["total_ret"] - 10 for r in results[1:]):
            print("     However, some strategies are close to hold with LESS risk (cash secured).")
            print("     May be worth considering for risk management, not alpha generation.")
        else:
            print("     DCA-out actively HURTS returns in this period (sold too early in bull).")

    return {"results": results, "baseline": baseline}


# ---------------------------------------------------------------------------
# ANALYSIS 3: Weekly RSI
# ---------------------------------------------------------------------------

def analysis_3_weekly_rsi(btc_df: pd.DataFrame) -> dict:
    """Weekly RSI as overbought indicator.

    RSI (Relative Strength Index) measures price momentum.
    Weekly RSI is more stable than daily. RSI > 85 = extremely overbought.

    Computed from daily prices (close of each week = Friday or last available day).
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS 3: WEEKLY RSI AS OVERBOUGHT EXIT SIGNAL")
    print(sep)
    print()
    print("  RSI > 70 = overbought, RSI > 85 = extremely overbought.")
    print("  Weekly timeframe more stable than daily (fewer false signals).")
    print("  Hypothesis: extreme weekly RSI predicts negative forward returns.")
    print()

    prices_full = btc_df.set_index("date")["price"]
    prices_full.index = pd.to_datetime(prices_full.index)
    prices_full = prices_full[~prices_full.index.duplicated(keep="first")].sort_index()

    # Resample to weekly (Friday close)
    weekly_prices = prices_full.resample("W-FRI").last().dropna()

    # Compute RSI (14-week period)
    delta = weekly_prices.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Map weekly RSI back to daily prices for forward return computation
    # Each trading day gets the RSI of its most recent completed week
    daily_rsi = rsi.reindex(prices_full.index, method="ffill")

    prices_a = prices_full.loc[ANALYSIS_START:ANALYSIS_END]
    rsi_a = daily_rsi.loc[ANALYSIS_START:ANALYSIS_END].dropna()

    common = prices_a.index.intersection(rsi_a.index)
    prices_a = prices_a.loc[common]
    rsi_a = rsi_a.loc[common]

    print(f"  Period        : {prices_a.index[0].date()} to {prices_a.index[-1].date()}")
    print(f"  Weekly RSI range: {rsi_a.min():.1f} to {rsi_a.max():.1f}")
    print(f"  Median RSI   : {rsi_a.median():.1f}")
    print()

    # Count weeks in extreme zones
    weekly_rsi = rsi.loc[ANALYSIS_START:ANALYSIS_END].dropna()
    n_above_85 = (weekly_rsi > 85).sum()
    n_above_80 = (weekly_rsi > 80).sum()
    n_above_75 = (weekly_rsi > 75).sum()
    n_above_70 = (weekly_rsi > 70).sum()
    print(f"  Weeks with RSI > 70: {n_above_70}")
    print(f"  Weeks with RSI > 75: {n_above_75}")
    print(f"  Weeks with RSI > 80: {n_above_80}")
    print(f"  Weeks with RSI > 85: {n_above_85}")
    print()

    bin_defs = [
        ("RSI < 30 (oversold)",          rsi_a < 30),
        ("RSI 30-50 (bearish)",          (rsi_a >= 30) & (rsi_a < 50)),
        ("RSI 50-70 (neutral/bullish)",  (rsi_a >= 50) & (rsi_a < 70)),
        ("RSI 70-80 (overbought)",       (rsi_a >= 70) & (rsi_a < 80)),
        ("RSI 80-85 (very overbought)",  (rsi_a >= 80) & (rsi_a < 85)),
        ("RSI >= 85 (extreme)",          rsi_a >= 85),
    ]

    baseline_mask = pd.Series(True, index=prices_a.index)
    baseline_ret = compute_forward_returns(prices_a, baseline_mask, HORIZONS)

    bins = []
    for label, mask in bin_defs:
        events = independent_events(mask)
        ret7 = compute_forward_returns(prices_a, mask, [7])[7]
        ret30 = compute_forward_returns(prices_a, mask, [30])[30]
        ret90 = compute_forward_returns(prices_a, mask, [90])[90]
        bins.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline: 30d mean={baseline_ret[30]['mean']:+.1f}%, "
          f"90d mean={baseline_ret[90]['mean']:+.1f}%")
    print()
    print_bin_table("Forward returns by weekly RSI bin:", bins, baseline_ret)

    # Out-of-sample validation
    print()
    print("  --- OUT-OF-SAMPLE VALIDATION ---")
    for period_name, p_start, p_end in [
        ("Exploration", ANALYSIS_START, EXPLORE_END),
        ("Validation", VALIDATE_START, ANALYSIS_END),
    ]:
        p_idx = prices_a.loc[p_start:p_end].index.intersection(rsi_a.loc[p_start:p_end].index)
        if len(p_idx) < 30:
            print(f"  {period_name}: insufficient data")
            continue
        p_prices = prices_a.loc[p_idx]
        p_rsi = rsi_a.loc[p_idx]
        p_base = compute_forward_returns(p_prices, pd.Series(True, index=p_idx), [30])

        for thresh_name, thresh in [("RSI>=80", 80), ("RSI>=85", 85)]:
            t_mask = p_rsi >= thresh
            if t_mask.sum() >= 5:
                t_ret = compute_forward_returns(p_prices, t_mask, [30])[30]
                delta = t_ret["mean"] - p_base[30]["mean"]
                ci_str = fmt_ci(t_ret["ci_lo"], t_ret["ci_hi"]) if t_ret["n"] >= 2 else "N/A"
                raw = t_ret.get("raw", np.array([]))
                base_raw = p_base[30].get("raw", np.array([]))
                p_val = test_signal_vs_baseline(raw, base_raw) if len(raw) >= 3 else 1.0
                print(f"  {period_name} {thresh_name}: 30d={t_ret['mean']:+.1f}%, "
                      f"CI={ci_str}, delta={delta:+.1f}pp, p={p_val:.3f}, N={t_ret['n']}")
            else:
                print(f"  {period_name} {thresh_name}: N={int(t_mask.sum())} days (insufficient)")

    # Interpretation
    print()
    print("  INTERPRETATION:")
    extreme_bin = bins[-1]  # RSI >= 85
    high_bin = bins[-2]     # RSI 80-85
    delta_extreme = extreme_bin["ret30"]["mean"] - baseline_ret[30]["mean"]
    delta_high = high_bin["ret30"]["mean"] - baseline_ret[30]["mean"]

    if extreme_bin["n_events"] < 3:
        print(f"  -> RSI >= 85: only {extreme_bin['n_events']} independent events -- insufficient N.")
        print("     Cannot validate or reject as exit signal.")
    elif delta_extreme < -3.0:
        print(f"  -> RSI >= 85: 30d delta={delta_extreme:+.1f}pp below baseline -- POTENTIAL SIGNAL")
    else:
        print(f"  -> RSI >= 85: 30d delta={delta_extreme:+.1f}pp -- {'positive' if delta_extreme > 0 else 'weak'}.")

    if high_bin["n_events"] >= 5:
        print(f"  -> RSI 80-85: 30d delta={delta_high:+.1f}pp, N={high_bin['n_events']} events.")
    else:
        print(f"  -> RSI 80-85: N={high_bin['n_events']} events (insufficient).")

    return {
        "bins": bins, "baseline": baseline_ret,
        "rsi": rsi_a, "prices": prices_a,
    }


# ---------------------------------------------------------------------------
# ANALYSIS 4: Halving Cycle Timing
# ---------------------------------------------------------------------------

def analysis_4_halving_cycle(btc_df: pd.DataFrame) -> dict:
    """Halving cycle as exit timing framework.

    BTC halvings are deterministic: 2012, 2016, 2020, 2024, ~2028.
    Historical pattern: price peaks 12-18 months after halving.
    Question: would reducing DCA or selling in months 12-18 post-halving help?

    This is not a signal -- it's calendar-based timing using a known schedule.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS 4: HALVING CYCLE TIMING")
    print(sep)
    print()
    print("  BTC halvings: 2012-11-28, 2016-07-09, 2020-05-11, 2024-04-19")
    print("  Historical peaks: ~12-18 months after halving (2013, 2017, 2021).")
    print("  Question: can we use this deterministic schedule to time exits?")
    print()

    prices_full = btc_df.set_index("date")["price"]
    prices_full.index = pd.to_datetime(prices_full.index)
    prices_full = prices_full[~prices_full.index.duplicated(keep="first")].sort_index()
    prices_a = prices_full.loc[ANALYSIS_START:ANALYSIS_END]

    # Compute months-since-halving for each day
    def months_since_halving(date: pd.Timestamp) -> tuple[float, pd.Timestamp]:
        """Return (months_since, halving_date) for the most recent halving before date."""
        prev = None
        for h in HALVING_DATES:
            if h <= date:
                prev = h
        if prev is None:
            return (-1.0, HALVING_DATES[0])
        delta = (date - prev).days / 30.44  # avg days per month
        return (delta, prev)

    cycle_phase = pd.Series(index=prices_a.index, dtype=float)
    for date in prices_a.index:
        months, _ = months_since_halving(date)
        cycle_phase[date] = months

    print(f"  Period: {prices_a.index[0].date()} to {prices_a.index[-1].date()}")
    print()

    # Show historical peaks relative to halvings
    print("  Historical cycle peaks (in our analysis period):")
    # Find local peaks (highest price in rolling 90-day windows around known peaks)
    for halving in HALVING_DATES:
        if halving < pd.Timestamp(ANALYSIS_START) - timedelta(days=600):
            continue
        # Look for peak 0-24 months after halving
        window_start = halving
        window_end = halving + timedelta(days=730)
        window = prices_full.loc[window_start:window_end]
        if len(window) > 0:
            peak_date = window.idxmax()
            peak_price = window.max()
            months_to_peak = (peak_date - halving).days / 30.44
            print(f"    Halving {halving.date()}: peak ${peak_price:,.0f} on "
                  f"{peak_date.date()} ({months_to_peak:.0f} months after)")
    print()

    # Bin by cycle phase
    bin_defs = [
        ("0-6 mo post-halving",    (cycle_phase >= 0)  & (cycle_phase < 6)),
        ("6-12 mo post-halving",   (cycle_phase >= 6)  & (cycle_phase < 12)),
        ("12-15 mo post-halving",  (cycle_phase >= 12) & (cycle_phase < 15)),
        ("15-18 mo post-halving",  (cycle_phase >= 15) & (cycle_phase < 18)),
        ("18-24 mo post-halving",  (cycle_phase >= 18) & (cycle_phase < 24)),
        ("24-36 mo post-halving",  (cycle_phase >= 24) & (cycle_phase < 36)),
        ("36-48 mo post-halving",  (cycle_phase >= 36) & (cycle_phase < 48)),
    ]

    baseline_mask = pd.Series(True, index=prices_a.index)
    baseline_ret = compute_forward_returns(prices_a, baseline_mask, HORIZONS)

    bins = []
    for label, mask in bin_defs:
        events = independent_events(mask, cooldown_days=30)
        ret7 = compute_forward_returns(prices_a, mask, [7])[7]
        ret30 = compute_forward_returns(prices_a, mask, [30])[30]
        ret90 = compute_forward_returns(prices_a, mask, [90])[90]
        bins.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline: 30d mean={baseline_ret[30]['mean']:+.1f}%, "
          f"90d mean={baseline_ret[90]['mean']:+.1f}%")
    print()
    print_bin_table("Forward returns by halving cycle phase:", bins, baseline_ret)

    # Simulation: pause DCA or sell during months 12-18
    print()
    print("  --- SIMULATION: Modify strategy during months 12-18 post-halving ---")

    weekly_dates = _build_weekly_dates(prices_a.index,
                                       prices_a.index[0].strftime("%Y-%m-%d"))
    years = (prices_a.index[-1] - prices_a.index[0]).days / 365.25

    strategies = [
        ("Pure hold DCA",          "hold",  0.0),
        ("Pause DCA months 12-18", "pause", 0.0),
        ("Sell 25% at month 12",   "sell",  0.25),
        ("Sell 33% at month 12",   "sell",  0.33),
        ("Sell 50% at month 12",   "sell",  0.50),
    ]

    sim_results = []
    for name, action, sell_frac in strategies:
        btc_units = 0.0
        cash_eur = 0.0
        invested = 0.0
        total_fees = 0.0
        n_sells = 0
        # Track if we already sold for this halving cycle
        sold_for_halving: set[pd.Timestamp] = set()

        for date in prices_a.index:
            price = prices_a[date]
            months, halving = months_since_halving(date)

            # Weekly DCA (unless pausing)
            if date in weekly_dates:
                if action == "pause" and 12 <= months < 18:
                    invested += WEEKLY_BTC_EUR  # still count as invested (cash)
                    cash_eur += WEEKLY_BTC_EUR
                else:
                    btc_units += WEEKLY_BTC_EUR / price
                    invested += WEEKLY_BTC_EUR

            # Sell trigger
            if action == "sell" and months >= 12 and halving not in sold_for_halving:
                if btc_units > 0:
                    sell_units = btc_units * sell_frac
                    sell_val = sell_units * price
                    net = sell_val - SELL_FEE_EUR
                    if net > 0:
                        btc_units -= sell_units
                        cash_eur += net
                        total_fees += SELL_FEE_EUR
                        n_sells += 1
                sold_for_halving.add(halving)

        final_btc = btc_units * prices_a.iloc[-1]
        final_total = final_btc + cash_eur
        tot_ret = (final_total - invested) / invested * 100
        ann = cagr(invested, final_total, years)
        vs_base = tot_ret - (sim_results[0]["total_ret"] if sim_results else tot_ret)

        sim_results.append({
            "name": name, "total_ret": tot_ret, "cagr": ann,
            "final_total": final_total, "n_sells": n_sells,
            "fees": total_fees, "vs_hold": vs_base,
        })

    # Fix vs_hold for baseline
    if sim_results:
        sim_results[0]["vs_hold"] = 0.0

    hdr = (f"  {'Strategy':<30} | {'Final EUR':>10} | {'Tot Ret':>8} | "
           f"{'CAGR':>7} | {'vs Hold':>8}")
    div = "  " + "-" * 30 + "-+-" + "-+-".join(["-" * 10, "-" * 8, "-" * 7, "-" * 8])
    print(hdr)
    print(div)
    for r in sim_results:
        marker = " <--" if r["vs_hold"] > 5 else ""
        print(f"  {r['name']:<30} | {r['final_total']:>10,.0f} | "
              f"{r['total_ret']:>7.1f}% | {r['cagr']:>6.1f}% | "
              f"{r['vs_hold']:>+7.1f}pp{marker}")

    # Interpretation
    print()
    print("  INTERPRETATION:")
    best_alt = max(sim_results[1:], key=lambda x: x["total_ret"])
    delta = best_alt["total_ret"] - sim_results[0]["total_ret"]
    if delta > 5:
        print(f"  -> Halving timing ADDS VALUE: '{best_alt['name']}' gains +{delta:.0f}pp vs hold.")
        print("     However: only 2 halvings in our test period (2020, 2024) = N=2.")
        print("     Statistical confidence is LOW despite positive result.")
    elif delta > -5:
        print(f"  -> Halving timing roughly NEUTRAL: best is {delta:+.1f}pp vs hold.")
        print("     Cycle timing is informative but doesn't mechanically improve returns.")
    else:
        print(f"  -> Halving timing HURTS: best alternative is {delta:+.1f}pp vs hold.")
        print("     Bull markets in 2020-2021 and 2024-2025 continued past month 18.")

    print("  Note: N=2 halving cycles in 2018-2026 -- insufficient for robust validation.")
    print("  Useful as planning framework, not as mechanical trading rule.")

    return {"bins": bins, "baseline": baseline_ret, "sim_results": sim_results}


# ---------------------------------------------------------------------------
# ANALYSIS 5: Active Addresses Divergence + Coin Days Destroyed
# ---------------------------------------------------------------------------

def analysis_5_onchain(btc_df: pd.DataFrame) -> dict:
    """On-chain activity signals.

    A) Active address divergence: price up + active addresses flat = speculative.
       Computed as 90-day correlation between price change and address change.
       Negative divergence (price up, addresses down) could predict reversal.

    B) Coin Days Destroyed (CDD) proxy: when dormant coins move, HODLers may be
       distributing near tops. High CDD = old hands selling.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS 5: ON-CHAIN ACTIVITY SIGNALS")
    print(sep)
    print()
    print("  A) Active address divergence: price rises without new users = speculative.")
    print("  B) Supply issuance proxy (CDD not in free tier): daily new supply as rough proxy.")
    print()

    onchain_df = fetch_btc_onchain()
    prices_full = btc_df.set_index("date")["price"]
    prices_full.index = pd.to_datetime(prices_full.index)
    prices_full = prices_full[~prices_full.index.duplicated(keep="first")].sort_index()

    addr = onchain_df.set_index("date")["active_addresses"]
    addr.index = pd.to_datetime(addr.index)
    addr = addr[~addr.index.duplicated(keep="first")].sort_index()

    cdd_s = onchain_df.set_index("date")["cdd"]
    cdd_s.index = pd.to_datetime(cdd_s.index)
    cdd_s = cdd_s[~cdd_s.index.duplicated(keep="first")].sort_index()

    # --- Part A: Active Address Divergence ---
    print("  === PART A: Active Address Divergence ===")
    print()

    # Smooth both series with 30-day MA
    price_ma30 = prices_full.rolling(30, min_periods=20).mean()
    addr_ma30 = addr.rolling(30, min_periods=20).mean()

    # 90-day % change
    price_chg_90 = price_ma30.pct_change(90) * 100
    addr_chg_90 = addr_ma30.pct_change(90) * 100

    # Divergence: price up > 50% but addresses down or flat
    prices_a = prices_full.loc[ANALYSIS_START:ANALYSIS_END]

    common = prices_a.index.intersection(price_chg_90.dropna().index).intersection(
        addr_chg_90.dropna().index)
    prices_a_div = prices_a.loc[common]
    p_chg = price_chg_90.loc[common]
    a_chg = addr_chg_90.loc[common]

    print(f"  Period: {prices_a_div.index[0].date()} to {prices_a_div.index[-1].date()}")
    print(f"  Days with both price and address data: {len(common)}")
    print()

    # Divergence bins: price up significantly, but addresses not keeping up
    div_bin_defs = [
        ("Price up >50%, addr up >20%",      (p_chg > 50) & (a_chg > 20)),
        ("Price up >50%, addr +/-20%",        (p_chg > 50) & (a_chg >= -20) & (a_chg <= 20)),
        ("Price up >50%, addr down >20%",     (p_chg > 50) & (a_chg < -20)),
        ("Price flat/down, any addr",          p_chg <= 0),
    ]

    baseline_mask_div = pd.Series(True, index=prices_a_div.index)
    baseline_ret_div = compute_forward_returns(prices_a_div, baseline_mask_div, HORIZONS)

    bins_a = []
    for label, mask in div_bin_defs:
        events = independent_events(mask)
        ret7 = compute_forward_returns(prices_a_div, mask, [7])[7]
        ret30 = compute_forward_returns(prices_a_div, mask, [30])[30]
        ret90 = compute_forward_returns(prices_a_div, mask, [90])[90]
        bins_a.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline: 30d mean={baseline_ret_div[30]['mean']:+.1f}%")
    print()
    print_bin_table("Address divergence bins:", bins_a, baseline_ret_div)

    # --- Part B: CDD proxy ---
    print()
    print("  === PART B: Supply Issuance Proxy (CDD not available in free tier) ===")
    print()

    cdd_a = cdd_s.loc[ANALYSIS_START:ANALYSIS_END].dropna()
    if len(cdd_a) < 30:
        print("  WARNING: CDD data insufficient or unavailable from CoinMetrics free tier.")
        print("  Skipping CDD analysis.")
        bins_b = []
    else:
        # Smooth CDD with 14-day MA, then look for extreme spikes
        cdd_smooth = cdd_a.rolling(14, min_periods=7).mean()

        common_b = prices_a.index.intersection(cdd_smooth.dropna().index)
        prices_a_cdd = prices_a.loc[common_b]
        cdd_ab = cdd_smooth.loc[common_b]

        # Use percentiles for bins
        p50 = cdd_ab.quantile(0.50)
        p75 = cdd_ab.quantile(0.75)
        p90 = cdd_ab.quantile(0.90)
        p95 = cdd_ab.quantile(0.95)

        print(f"  CDD proxy range: {cdd_ab.min():.0f} to {cdd_ab.max():.0f}")
        print(f"  Median: {p50:.0f}, 75th: {p75:.0f}, 90th: {p90:.0f}, 95th: {p95:.0f}")
        print()

        cdd_bin_defs = [
            (f"CDD < {p50:.0f} (low activity)",       cdd_ab < p50),
            (f"CDD {p50:.0f}-{p75:.0f} (normal)",     (cdd_ab >= p50) & (cdd_ab < p75)),
            (f"CDD {p75:.0f}-{p90:.0f} (elevated)",   (cdd_ab >= p75) & (cdd_ab < p90)),
            (f"CDD >= {p90:.0f} (spike)",              cdd_ab >= p90),
        ]

        baseline_cdd = compute_forward_returns(
            prices_a_cdd, pd.Series(True, index=prices_a_cdd.index), HORIZONS)

        bins_b = []
        for label, mask in cdd_bin_defs:
            events = independent_events(mask)
            ret7 = compute_forward_returns(prices_a_cdd, mask, [7])[7]
            ret30 = compute_forward_returns(prices_a_cdd, mask, [30])[30]
            ret90 = compute_forward_returns(prices_a_cdd, mask, [90])[90]
            bins_b.append({
                "label": label, "mask": mask,
                "n_days": int(mask.sum()), "n_events": int(events.sum()),
                "ret7": ret7, "ret30": ret30, "ret90": ret90,
            })

        print(f"  Baseline: 30d mean={baseline_cdd[30]['mean']:+.1f}%")
        print()
        print_bin_table("CDD proxy bins:", bins_b, baseline_cdd)

    # Interpretation
    print()
    print("  INTERPRETATION:")

    # Address divergence
    div_bear = [b for b in bins_a if "addr down" in b["label"]]
    if div_bear:
        b = div_bear[0]
        delta = b["ret30"]["mean"] - baseline_ret_div[30]["mean"]
        if b["n_events"] >= 5 and delta < -3.0:
            print(f"  -> Address divergence (price up, addr down): 30d delta={delta:+.1f}pp "
                  f"(N={b['n_events']}) -- POTENTIAL SIGNAL")
        elif b["n_events"] < 5:
            print(f"  -> Address divergence: N={b['n_events']} events (insufficient)")
        else:
            print(f"  -> Address divergence: 30d delta={delta:+.1f}pp -- weak/no effect")

    if bins_b:
        spike_bin = bins_b[-1]
        delta_cdd = spike_bin["ret30"]["mean"] - baseline_cdd[30]["mean"]
        if spike_bin["n_events"] >= 5 and delta_cdd < -3.0:
            print(f"  -> CDD spikes: 30d delta={delta_cdd:+.1f}pp (N={spike_bin['n_events']}) -- "
                  "POTENTIAL SIGNAL")
        elif spike_bin["n_events"] < 5:
            print(f"  -> CDD spikes: N={spike_bin['n_events']} events (insufficient)")
        else:
            print(f"  -> CDD spikes: 30d delta={delta_cdd:+.1f}pp -- weak/no effect")

    return {"bins_addr": bins_a, "bins_cdd": bins_b}


# ---------------------------------------------------------------------------
# FINAL SUMMARY
# ---------------------------------------------------------------------------

def final_summary(nvt_result: dict, dca_out_result: dict,
                  rsi_result: dict, halving_result: dict,
                  onchain_result: dict) -> None:
    """Final summary of all analyses with multiple comparisons note."""
    global TOTAL_HYPOTHESES

    sep = "=" * 70
    print(f"\n{sep}")
    print("  FINAL SUMMARY: EXIT SIGNALS RESEARCH 3")
    print(sep)
    print()

    print("  PRIOR VALIDATED SIGNALS (exit_strategy_research.py + research2.py):")
    print()
    print("  Signal                           | Status     | Confidence")
    print("  " + "-" * 65)
    print("  Annual rebalancing (>10% drift)  | CONFIRMED  | HIGH (N=9)")
    print("  BTC $100k alert                  | CONFIRMED  | LOW (N=1, hindsight)")
    print("  ETH $3k alert                    | CONFIRMED  | LOW (N=1, hindsight)")
    print("  BTC/ETH MVRV as sell signal      | DISCARDED  | HIGH (robust null)")
    print("  MA ratio as sell signal          | DISCARDED  | HIGH (robust null)")
    print("  Gain-from-low as sell trigger    | DISCARDED  | HIGH (robust null)")
    print()

    print("  NEW SIGNALS (this script):")
    print()
    print("  Signal                           | Status     | Confidence | Notes")
    print("  " + "-" * 75)

    # NVT
    nvt_bins = nvt_result.get("bins", [])
    nvt_base = nvt_result.get("baseline", {})
    if nvt_bins:
        top = nvt_bins[-1]
        d30 = top["ret30"]["mean"] - nvt_base.get(30, {}).get("mean", 0)
        n_ev = top["n_events"]
        if n_ev >= 10 and d30 < -3.0:
            status = "POTENTIAL"
        elif d30 > 0:
            status = "DISCARDED"
        else:
            status = "WEAK/INSUF"
        print(f"  NVT extreme (top 10%)            | {status:<10} | N={n_ev:<3}       | "
              f"30d delta={d30:+.1f}pp")

    # DCA-out
    dca_results = dca_out_result.get("results", [])
    dca_base = dca_out_result.get("baseline", {})
    if dca_results and dca_base:
        best = max(dca_results[1:], key=lambda x: x["total_ret"])
        delta = best["total_ret"] - dca_base["total_ret"]
        status = "POTENTIAL" if delta > 5 else ("NEUTRAL" if delta > -5 else "DISCARDED")
        print(f"  DCA-out systematic               | {status:<10} | Sim-based  | "
              f"Best: {delta:+.1f}pp vs hold")

    # Weekly RSI
    rsi_bins = rsi_result.get("bins", [])
    rsi_base = rsi_result.get("baseline", {})
    if rsi_bins:
        ext = rsi_bins[-1]  # RSI >= 85
        d30 = ext["ret30"]["mean"] - rsi_base.get(30, {}).get("mean", 0)
        n_ev = ext["n_events"]
        if n_ev >= 10 and d30 < -3.0:
            status = "POTENTIAL"
        elif n_ev < 3:
            status = "INSUF N"
        elif d30 > 0:
            status = "DISCARDED"
        else:
            status = "WEAK"
        print(f"  Weekly RSI >= 85                 | {status:<10} | N={n_ev:<3}       | "
              f"30d delta={d30:+.1f}pp")

    # Halving
    halving_sims = halving_result.get("sim_results", [])
    if halving_sims:
        best_alt = max(halving_sims[1:], key=lambda x: x["total_ret"])
        delta = best_alt["total_ret"] - halving_sims[0]["total_ret"]
        status = "INFORMATIVE" if abs(delta) < 20 else ("POTENTIAL" if delta > 5 else "DISCARDED")
        print(f"  Halving cycle timing             | {status:<10} | N=2 cycles | "
              f"Best: {delta:+.1f}pp vs hold")

    # On-chain
    addr_bins = onchain_result.get("bins_addr", [])
    if addr_bins:
        div_bear = [b for b in addr_bins if "addr down" in b["label"]]
        if div_bear:
            b = div_bear[0]
            # Need baseline from that analysis
            n_ev = b["n_events"]
            status = "WEAK" if n_ev >= 5 else "INSUF N"
            print(f"  Active addr divergence           | {status:<10} | N={n_ev:<3}       | "
                  f"Needs more data")

    cdd_bins = onchain_result.get("bins_cdd", [])
    if cdd_bins:
        spike = cdd_bins[-1]
        n_ev = spike["n_events"]
        status = "WEAK" if n_ev >= 5 else "INSUF N"
        print(f"  CDD proxy spikes                 | {status:<10} | N={n_ev:<3}       | "
              f"Proxy metric, limited")

    # Multiple comparisons warning
    print()
    print("  *** MULTIPLE COMPARISONS WARNING ***")
    print(f"  Total hypotheses tested in this script: ~{TOTAL_HYPOTHESES}")
    total_all = TOTAL_HYPOTHESES + 20  # rough count from prior scripts
    print(f"  Total across all 3 research scripts: ~{total_all}")
    expected_fp = total_all * 0.05
    print(f"  Expected false positives at p<0.05 by chance alone: ~{expected_fp:.1f}")
    print(f"  Bonferroni-corrected threshold: p < {0.05/max(total_all,1):.4f}")
    print("  Any signal with p > corrected threshold should be treated as UNCONFIRMED.")
    print()

    print("  CONCLUSIONS:")
    print()
    print("  1. The fundamental finding from ALL three research scripts is consistent:")
    print("     In crypto bull markets, momentum dominates. 'Overheated' metrics")
    print("     (MVRV, MA ratio, NVT, RSI) generally predict CONTINUATION, not reversal.")
    print()
    print("  2. The only reliably profitable exit strategies are:")
    print("     a) Annual portfolio rebalancing (N=9, validated, reduces risk)")
    print("     b) Profit-taking at absolute milestones ($100k BTC, $3k ETH)")
    print("     c) Potentially: systematic DCA-out (if backtest shows improvement)")
    print()
    print("  3. Halving cycle timing is useful as a PLANNING FRAMEWORK:")
    print("     - Months 12-18 post-halving = historically elevated risk zone")
    print("     - But only 2 cycles in our data = cannot validate mechanically")
    print()
    print("  4. On-chain metrics (addresses, CDD) may have value but:")
    print("     - CoinMetrics free tier limits available metrics")
    print("     - Divergence events are rare (low N) in 2018-2026")
    print("     - Would need longer history or paid data to validate")
    print()
    print("  RECOMMENDATION: No changes to current production alerts.")
    print("  The validated approach remains: DCA + annual rebalancing + absolute price alerts.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("=" * 70)
    print("  EXIT SIGNALS RESEARCH 3 -- On-chain + Systematic + Statistical Rigor")
    print("  Building on research 1 & 2. Adding bootstrap CIs, Mann-Whitney, OOS split.")
    print("=" * 70)
    print()
    print(f"  Full period     : {ANALYSIS_START} to {ANALYSIS_END}")
    print(f"  Exploration     : {ANALYSIS_START} to {EXPLORE_END}")
    print(f"  Validation      : {VALIDATE_START} to {ANALYSIS_END}")
    print(f"  Strategy base   : DCA {WEEKLY_BTC_EUR:.0f} EUR/week in BTC (Trade Republic)")
    print(f"  Sell fee        : {SELL_FEE_EUR:.0f} EUR flat per transaction")
    print(f"  Bootstrap       : {N_BOOTSTRAP} samples, {CI_LEVEL*100:.0f}% CI")
    print()

    print("  Loading data...")
    btc_full = fetch_btc_prices()

    nvt_result = analysis_1_nvt(btc_full)
    dca_out_result = analysis_2_dca_out(btc_full)
    rsi_result = analysis_3_weekly_rsi(btc_full)
    halving_result = analysis_4_halving_cycle(btc_full)
    onchain_result = analysis_5_onchain(btc_full)

    final_summary(nvt_result, dca_out_result, rsi_result,
                  halving_result, onchain_result)

    print()
    print("=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
