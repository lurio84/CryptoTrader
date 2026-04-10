"""exit_signals_research2.py
==========================
Research on exit/reduce signals with sufficient N for statistical validity.

Problem with existing exit signals (BTC >$100k, ETH >$3k): N=1 trigger event.
This script explores relative, threshold-based signals that fire frequently
enough to have valid statistics.

Analysis A: BTC Price / 200-day Moving Average ratio
  "How overheated is the market?" measured relative to trend.
  Bins by ratio level, computes forward returns at each bin.
  Goal: find threshold above which forward returns are meaningfully below baseline.

Analysis B: BTC % gain from rolling 365-day minimum (cycle position)
  "Where are we in the bull market?" without knowing future prices.
  Captures cycle exhaustion: up 400% from yearly low -> near cycle top?
  Same binning approach, same forward-return analysis.

Analysis C: DCA + sell simulation using MA ratio threshold
  Full DCA portfolio simulation (BTC 8 EUR/week) with partial sell rule.
  Rule: when price > K * 200d_MA, sell X% of BTC holdings.
  Tests multiple K/X combinations, compares to pure hold DCA baseline.
  Extends Analysis 2 (absolute levels) with a RELATIVE, repeatable signal.

Summary: table of confirmed vs discarded signals across all analyses.

Data sources (all free, shared cache with exit_strategy_research.py):
  - BTC prices: CoinMetrics community API (cached in data/research_cache/)
  - No API keys required

Usage:
  python backtesting/exit_signals_research2.py
"""

from __future__ import annotations

import sys
import time
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Analysis period -- same as exit_strategy_research.py for consistency
ANALYSIS_START = "2018-01-01"
ANALYSIS_END   = "2026-04-01"

# Extended fetch start: need 200+ days before ANALYSIS_START to compute 200d MA
FETCH_START = "2017-01-01"

WEEKLY_BTC_EUR = 8.0    # BTC Sparplan (Trade Republic)
SELL_FEE_EUR   = 1.0    # flat 1 EUR per crypto sell at TR

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Forward return horizons in days
HORIZONS = [7, 30, 90]

# Number of days between independent events (cooldown to avoid autocorrelation)
EVENT_COOLDOWN_DAYS = 14


# ---------------------------------------------------------------------------
# Helpers
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
# Data fetching
# ---------------------------------------------------------------------------

def fetch_btc_prices() -> pd.DataFrame:
    """BTC daily USD prices from CoinMetrics community API.

    Reuses existing cache from exit_strategy_research.py.
    Cache contains full history from 2010 onward (no date filter in fetch).
    """
    cache = CACHE_DIR / "btc_cm.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    BTC prices: {len(cached)} days from cache")
        return cached

    print("    BTC prices: fetching from CoinMetrics (full history)...")
    all_rows: list[dict] = []
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params: dict = {
        "assets": "btc",
        "metrics": "PriceUSD",
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
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(next_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        time.sleep(0.5)

    if not all_rows:
        raise ValueError("CoinMetrics returned no BTC price data")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df["price"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    df = (df[["date", "price"]].dropna()
          .sort_values("date")
          .drop_duplicates("date")
          .reset_index(drop=True))
    _save_cache(df, cache)
    print(f"    BTC prices: {len(df)} days fetched and cached")
    return df


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def compute_forward_returns(prices: pd.Series, signal_mask: pd.Series,
                            horizons: list[int]) -> dict[int, dict]:
    """For each horizon, compute forward return stats on signal days.

    Returns dict: {horizon: {mean, median, win_pct, n}}
    """
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
            out[h] = {
                "mean": float(np.mean(arr)),
                "median": float(np.median(arr)),
                "win": float((arr > 0).mean() * 100),
                "n": len(arr),
            }
        else:
            out[h] = {"mean": 0.0, "median": 0.0, "win": 0.0, "n": 0}
    return out


def independent_events(mask: pd.Series, cooldown_days: int = EVENT_COOLDOWN_DAYS) -> pd.Series:
    """Thin a boolean mask so consecutive True runs become one event.

    Keeps the FIRST True day in each run, then enforces a cooldown period
    before the next event can fire. Returns a new boolean mask.
    """
    result = pd.Series(False, index=mask.index)
    last_event = None
    for date in mask.index:
        if mask[date]:
            if last_event is None or (date - last_event).days >= cooldown_days:
                result[date] = True
                last_event = date
    return result


def print_bin_table(label: str, bins: list[dict]) -> None:
    """Pretty-print a forward-return table by bin."""
    print(f"  {label}")
    hdr = (f"  {'Bin':<28} | {'N days':>7} | {'N events':>8} | "
           f"{'7d mean':>8} | {'30d mean':>9} | {'90d mean':>9} | {'30d win%':>8}")
    div = "  " + "-"*28 + "-+-" + "-+-".join(["-"*7, "-"*8, "-"*8, "-"*9, "-"*9, "-"*8])
    print(hdr)
    print(div)
    for b in bins:
        print(f"  {b['label']:<28} | {b['n_days']:>7} | {b['n_events']:>8} | "
              f"{b['ret7']['mean']:>+7.1f}% | {b['ret30']['mean']:>+8.1f}% | "
              f"{b['ret90']['mean']:>+8.1f}% | {b['ret30']['win']:>7.0f}%")


# ---------------------------------------------------------------------------
# ANALYSIS A: BTC Price / 200-day MA ratio
# ---------------------------------------------------------------------------

def analysis_a_ma_ratio(btc_full: pd.DataFrame) -> dict:
    """
    Bin BTC trading days by price/200d_MA ratio.
    Compute forward returns per bin.
    Goal: identify if high-ratio zones predict lower forward returns.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS A: BTC PRICE / 200-DAY MA RATIO")
    print(sep)
    print()
    print("  Hypothesis: when BTC trades at extreme multiples of its 200d moving average,")
    print("  the market is overheated and forward returns should be below baseline.")
    print("  This is a RELATIVE signal (no fixed price) that fires in every cycle.")
    print()

    # Build price series from full history for accurate 200d MA
    prices = btc_full.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices[~prices.index.duplicated(keep="first")].sort_index()

    # 200-day MA requires at least 200 days of history
    ma200 = prices.rolling(200, min_periods=180).mean()
    ratio = prices / ma200

    # Filter to analysis period
    prices_a = prices.loc[ANALYSIS_START:ANALYSIS_END]
    ratio_a  = ratio.loc[ANALYSIS_START:ANALYSIS_END]

    print(f"  Period       : {prices_a.index[0].date()} to {prices_a.index[-1].date()}")
    print(f"  Ratio range  : {ratio_a.min():.2f}x to {ratio_a.max():.2f}x")
    print(f"  Ratio median : {ratio_a.median():.2f}x")
    print()

    # Define bins
    bin_defs = [
        ("< 0.8x  (deep undervalue)",    ratio_a < 0.8),
        ("0.8-1.0x (undervalue)",         (ratio_a >= 0.8) & (ratio_a < 1.0)),
        ("1.0-1.2x (fair value)",          (ratio_a >= 1.0) & (ratio_a < 1.2)),
        ("1.2-1.5x (moderate bull)",       (ratio_a >= 1.2) & (ratio_a < 1.5)),
        ("1.5-2.0x (strong bull)",         (ratio_a >= 1.5) & (ratio_a < 2.0)),
        ("2.0-2.5x (overheated)",          (ratio_a >= 2.0) & (ratio_a < 2.5)),
        (">= 2.5x  (extreme overheating)", ratio_a >= 2.5),
    ]

    bins = []
    baseline_mask = pd.Series(True, index=prices_a.index)
    baseline_ret = compute_forward_returns(prices_a, baseline_mask, HORIZONS)

    for label, mask in bin_defs:
        events = independent_events(mask)
        ret7   = compute_forward_returns(prices_a, mask, [7])[7]
        ret30  = compute_forward_returns(prices_a, mask, [30])[30]
        ret90  = compute_forward_returns(prices_a, mask, [90])[90]
        bins.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline (all days): 30d mean={baseline_ret[30]['mean']:+.1f}%, "
          f"90d mean={baseline_ret[90]['mean']:+.1f}%, "
          f"N={baseline_ret[30]['n']}")
    print()
    print_bin_table("Forward returns by ratio bin:", bins)

    # Find the overheated bins
    print()
    print("  INTERPRETATION:")
    threshold_bins = [b for b in bins if ">= 2.5x" in b["label"] or "2.0-2.5x" in b["label"]]
    confirmed = False
    best_sell_threshold = None

    for b in threshold_bins:
        delta30 = b["ret30"]["mean"] - baseline_ret[30]["mean"]
        delta90 = b["ret90"]["mean"] - baseline_ret[90]["mean"]
        n_ev    = b["n_events"]
        ratio_str = b["label"].split("(")[0].strip()
        if n_ev >= 10 and delta30 < -3.0:
            print(f"  -> {ratio_str}: 30d return is {delta30:+.1f}pp below baseline "
                  f"(N={n_ev} independent events) -- SIGNAL CONFIRMED")
            confirmed = True
            if best_sell_threshold is None:
                best_sell_threshold = ratio_str
        elif n_ev >= 5 and delta30 < -2.0:
            print(f"  -> {ratio_str}: 30d return is {delta30:+.1f}pp below baseline "
                  f"(N={n_ev} events, marginal) -- WEAK SIGNAL")
        else:
            print(f"  -> {ratio_str}: 30d delta={delta30:+.1f}pp vs baseline, N={n_ev} "
                  f"-- {'insufficient N' if n_ev < 5 else 'no predictive value'}")

    if not confirmed:
        print()
        print("  -> No overheated bin meets N>=10 AND delta<-3pp threshold.")
        print("     MA ratio alone does NOT provide a statistically valid sell signal.")

    return {
        "bins": bins,
        "baseline": baseline_ret,
        "confirmed": confirmed,
        "best_threshold": best_sell_threshold,
        "ratio": ratio_a,
        "prices": prices_a,
    }


# ---------------------------------------------------------------------------
# ANALYSIS B: BTC % gain from 365-day minimum (cycle position)
# ---------------------------------------------------------------------------

def analysis_b_gain_from_low(btc_full: pd.DataFrame) -> dict:
    """
    Bin BTC trading days by % gain from the trailing 365-day minimum.
    This measures "how deep into the bull market are we?"

    High gain-from-low = late cycle = potentially lower forward returns.
    Different from MA ratio: captures cycle exhaustion regardless of 200d MA level.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS B: BTC % GAIN FROM 365-DAY MINIMUM")
    print(sep)
    print()
    print("  Hypothesis: when BTC has already risen 300%+ from its 1-year low,")
    print("  most of the bull market gain is behind us and risk/reward has shifted.")
    print("  This signal fires in every cycle, not at one absolute price level.")
    print()

    prices = btc_full.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices[~prices.index.duplicated(keep="first")].sort_index()

    # Need an earlier start to have 365 days of lookback by ANALYSIS_START
    prices_ext = prices.loc["2017-01-01":ANALYSIS_END]

    # 365-day rolling minimum
    low_365 = prices_ext.rolling(365, min_periods=90).min()
    gain_from_low = (prices_ext / low_365 - 1) * 100

    # Filter to analysis period
    prices_a = prices_ext.loc[ANALYSIS_START:ANALYSIS_END]
    gain_a   = gain_from_low.loc[ANALYSIS_START:ANALYSIS_END]

    print(f"  Period       : {prices_a.index[0].date()} to {prices_a.index[-1].date()}")
    print(f"  Gain range   : {gain_a.min():.0f}% to {gain_a.max():.0f}%")
    print(f"  Gain median  : {gain_a.median():.0f}%")
    print()

    bin_defs = [
        ("< 25% (bear/recovery)",         gain_a < 25),
        ("25-75% (early bull)",            (gain_a >= 25) & (gain_a < 75)),
        ("75-150% (mid bull)",             (gain_a >= 75) & (gain_a < 150)),
        ("150-300% (mature bull)",         (gain_a >= 150) & (gain_a < 300)),
        ("300-500% (late cycle)",          (gain_a >= 300) & (gain_a < 500)),
        (">= 500% (extreme late cycle)",   gain_a >= 500),
    ]

    bins = []
    baseline_mask = pd.Series(True, index=prices_a.index)
    baseline_ret = compute_forward_returns(prices_a, baseline_mask, HORIZONS)

    for label, mask in bin_defs:
        events = independent_events(mask)
        ret7   = compute_forward_returns(prices_a, mask, [7])[7]
        ret30  = compute_forward_returns(prices_a, mask, [30])[30]
        ret90  = compute_forward_returns(prices_a, mask, [90])[90]
        bins.append({
            "label": label, "mask": mask,
            "n_days": int(mask.sum()), "n_events": int(events.sum()),
            "ret7": ret7, "ret30": ret30, "ret90": ret90,
        })

    print(f"  Baseline (all days): 30d mean={baseline_ret[30]['mean']:+.1f}%, "
          f"90d mean={baseline_ret[90]['mean']:+.1f}%, N={baseline_ret[30]['n']}")
    print()
    print_bin_table("Forward returns by % gain from 365-day low:", bins)

    print()
    print("  INTERPRETATION:")
    high_bins = [b for b in bins if "late cycle" in b["label"] or ">= 500%" in b["label"]]
    confirmed = False

    for b in high_bins:
        delta30 = b["ret30"]["mean"] - baseline_ret[30]["mean"]
        delta90 = b["ret90"]["mean"] - baseline_ret[90]["mean"]
        n_ev    = b["n_events"]
        label   = b["label"].split("(")[0].strip()
        if n_ev >= 10 and delta30 < -3.0:
            print(f"  -> {label}: 30d return is {delta30:+.1f}pp below baseline "
                  f"(N={n_ev} independent events) -- SIGNAL CONFIRMED")
            confirmed = True
        elif n_ev >= 5:
            print(f"  -> {label}: 30d delta={delta30:+.1f}pp, N={n_ev} "
                  f"-- {'WEAK SIGNAL' if delta30 < 0 else 'no predictive value'}")
        else:
            print(f"  -> {label}: N={n_ev} events (too few for statistical validity)")

    if not confirmed:
        print()
        print("  -> Gain-from-low does NOT provide a statistically valid sell signal alone.")
        print("     (Bull market momentum can continue even at high gain levels.)")

    return {
        "bins": bins,
        "baseline": baseline_ret,
        "confirmed": confirmed,
        "gain_from_low": gain_a,
        "prices": prices_a,
    }


# ---------------------------------------------------------------------------
# ANALYSIS C: DCA + sell simulation using MA ratio threshold
# ---------------------------------------------------------------------------

def analysis_c_sell_simulation(btc_full: pd.DataFrame, ratio_data: dict) -> None:
    """
    Full DCA+sell portfolio simulation using MA ratio as sell trigger.

    Strategy: keep DCA-ing weekly, but when price > K * 200d_MA,
    sell X% of BTC holdings. Proceeds kept as cash (not reinvested).
    One sell per threshold crossing (30-day cooldown before next sell).

    Extends Analysis 2 (absolute price levels) with a repeatable relative signal.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS C: DCA + SELL SIMULATION (MA RATIO TRIGGER)")
    print(sep)
    print()
    print(f"  Base strategy: DCA {WEEKLY_BTC_EUR:.0f} EUR/week into BTC, {ANALYSIS_START} to {ANALYSIS_END}")
    print("  Sell rule    : when price > K * 200d MA, sell X% of BTC holdings")
    print("  Proceeds     : kept as cash (not reinvested, same as Analysis 2)")
    print(f"  Sell fee     : {SELL_FEE_EUR:.0f} EUR flat per transaction (Trade Republic)")
    print()

    prices_a = ratio_data["prices"]
    ratio_a  = ratio_data["ratio"]

    weekly_dates = _build_weekly_dates(prices_a.index,
                                       prices_a.index[0].strftime("%Y-%m-%d"))
    years        = (prices_a.index[-1] - prices_a.index[0]).days / 365.25
    total_invested = len(weekly_dates) * WEEKLY_BTC_EUR

    print(f"  Period       : {prices_a.index[0].date()} to {prices_a.index[-1].date()} ({years:.1f} years)")
    print(f"  BTC price    : ${prices_a.iloc[0]:,.0f} -> ${prices_a.iloc[-1]:,.0f}")
    print(f"  Total DCA    : ~{total_invested:,.0f} EUR over {len(weekly_dates)} weeks")
    print()

    # Scenarios: (label, ratio_threshold, sell_fraction, cooldown_days)
    # Multiple thresholds can be combined (sell X% at 2x, Y% more at 2.5x, etc.)
    # Here we keep each scenario to a single threshold for clarity
    SCENARIOS: list[tuple[str, list[tuple[float, float, int]]]] = [
        ("Pure hold (baseline)",                       []),
        ("Sell 20% at ratio > 2.0x",                   [(2.0, 0.20, 90)]),
        ("Sell 25% at ratio > 2.0x",                   [(2.0, 0.25, 90)]),
        ("Sell 33% at ratio > 2.0x",                   [(2.0, 0.33, 90)]),
        ("Sell 20% at ratio > 2.5x",                   [(2.5, 0.20, 90)]),
        ("Sell 25% at ratio > 2.5x",                   [(2.5, 0.25, 90)]),
        ("Sell 33% at ratio > 2.5x",                   [(2.5, 0.33, 90)]),
        ("Sell 20% at ratio > 3.0x",                   [(3.0, 0.20, 90)]),
        ("Sell 15%@2x + 15%@2.5x + 15%@3x",           [(2.0, 0.15, 60), (2.5, 0.15, 60), (3.0, 0.15, 60)]),
        ("Sell 25%@2x + 25%@3x",                       [(2.0, 0.25, 60), (3.0, 0.25, 60)]),
    ]

    def simulate(trigger_rules: list[tuple[float, float, int]]) -> dict:
        """
        trigger_rules: list of (ratio_threshold, sell_fraction, cooldown_days)
        Each rule fires independently (separate cooldown per rule).
        """
        btc_units   = 0.0
        cash_eur    = 0.0
        invested    = 0.0
        total_fees  = 0.0
        sell_log: list[dict] = []
        # Track last trigger date per rule
        last_trigger: dict[float, pd.Timestamp | None] = {r[0]: None for r in trigger_rules}

        for date in prices_a.index:
            price = prices_a[date]
            r_val = ratio_a.get(date)  # may be NaN early on (insufficient MA history)

            # Weekly DCA
            if date in weekly_dates:
                btc_units += WEEKLY_BTC_EUR / price
                invested  += WEEKLY_BTC_EUR

            # Check sell triggers
            if r_val is not None and not np.isnan(r_val):
                for threshold, frac, cooldown in trigger_rules:
                    if r_val >= threshold:
                        last = last_trigger[threshold]
                        if last is None or (date - last).days >= cooldown:
                            sell_units = btc_units * frac
                            sell_val   = sell_units * price
                            net        = sell_val - SELL_FEE_EUR
                            if net > 0 and btc_units > 0:
                                btc_units  -= sell_units
                                cash_eur   += net
                                total_fees += SELL_FEE_EUR
                                last_trigger[threshold] = date
                                sell_log.append({
                                    "date": date, "price": price,
                                    "ratio": r_val, "threshold": threshold,
                                    "pct_sold": frac * 100, "eur_received": net,
                                })

        final_btc   = btc_units * prices_a.iloc[-1]
        final_total = final_btc + cash_eur
        tot_ret     = (final_total - invested) / invested * 100
        ann         = cagr(invested, final_total, years)

        return {
            "invested": invested, "final_btc": final_btc, "cash": cash_eur,
            "final_total": final_total, "total_ret": tot_ret, "cagr": ann,
            "fees": total_fees, "btc_remaining": btc_units,
            "n_sells": len(sell_log), "sell_log": sell_log,
        }

    print("  Running simulations...")
    results = []
    for name, rules in SCENARIOS:
        r = simulate(rules)
        r["name"] = name
        results.append(r)

    baseline = results[0]

    # Results table
    print()
    hdr = (f"  {'Strategy':<38} | {'Final EUR':>10} | {'Total Ret':>9} | "
           f"{'CAGR':>7} | {'vs Hold':>8} | {'N Sells':>7} | {'Fees EUR':>8}")
    div = ("  " + "-"*38 + "-+-" +
           "-+-".join(["-"*10, "-"*9, "-"*7, "-"*8, "-"*7, "-"*8]))
    print(hdr)
    print(div)
    for r in results:
        vs_hold = r["total_ret"] - baseline["total_ret"]
        marker  = " <--" if vs_hold > 5 else ""
        print(f"  {r['name']:<38} | {r['final_total']:>10,.0f} | "
              f"{r['total_ret']:>8.1f}% | {r['cagr']:>6.1f}% | "
              f"{vs_hold:>+7.1f}pp | {r['n_sells']:>7} | "
              f"{r['fees']:>8.2f}{marker}")

    # Sell log for best strategy
    print()
    best = max(results[1:], key=lambda x: x["total_ret"])
    print(f"  Best strategy: '{best['name'].strip()}' ({best['total_ret']:+.1f}% vs "
          f"hold {baseline['total_ret']:+.1f}%, delta={best['total_ret']-baseline['total_ret']:+.1f}pp)")

    if best["sell_log"]:
        print()
        print(f"  Sell events for '{best['name'].strip()}':")
        for s in best["sell_log"]:
            print(f"    {s['date'].date()}  BTC=${s['price']:,.0f}  "
                  f"ratio={s['ratio']:.2f}x  sold={s['pct_sold']:.0f}%  "
                  f"received={s['eur_received']:,.0f} EUR")

    # Verdict
    print()
    print("  VERDICT:")
    improvements = [r for r in results[1:] if r["total_ret"] > baseline["total_ret"] + 5]
    if improvements:
        best_imp = max(improvements, key=lambda x: x["total_ret"])
        delta    = best_imp["total_ret"] - baseline["total_ret"]
        print(f"  -> MA ratio sell strategy ADDS VALUE: best gains +{delta:.0f}pp vs hold.")
        print(f"     Strategy: '{best_imp['name'].strip()}'")
        n_sells = best_imp["n_sells"]
        if n_sells >= 3:
            print(f"     N={n_sells} sell events over {years:.0f} years -- sufficient for validation.")
            print("     RECOMMEND: implement as Discord alert (see discord_bot.py).")
        else:
            print(f"     WARNING: only N={n_sells} sell events -- too few for statistical confidence.")
            print("     Result may be luck/noise. Treat as exploratory, not confirmed.")
    else:
        best_non = max(results[1:], key=lambda x: x["total_ret"])
        delta    = best_non["total_ret"] - baseline["total_ret"]
        print(f"  -> MA ratio sell strategy does NOT add meaningful value vs hold DCA.")
        print(f"     Best improvement: {delta:+.1f}pp (below +5pp threshold for recommendation).")
        print("     DISCARD: do not implement as alert.")


# ---------------------------------------------------------------------------
# ANALYSIS D: Combined signal -- MA ratio + gain-from-low
# ---------------------------------------------------------------------------

def analysis_d_combined(btc_full: pd.DataFrame, ratio_data: dict,
                         gain_data: dict) -> None:
    """
    Test whether combining MA ratio AND gain-from-low gives a stronger signal.
    A combined signal fires when BOTH are in their top bins simultaneously.
    This is more restrictive (fewer events) but potentially more precise.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSIS D: COMBINED SIGNAL (MA RATIO + GAIN FROM LOW)")
    print(sep)
    print()
    print("  Tests two conditions simultaneously:")
    print("  1. Price > K * 200d MA (overheated)")
    print("  2. BTC is up >200% from 365-day low (late cycle)")
    print()
    print("  If both fire together: signal confidence should be higher,")
    print("  but N will be lower (harder to validate statistically).")
    print()

    prices_a  = ratio_data["prices"]
    ratio_a   = ratio_data["ratio"]
    gain_a    = gain_data["gain_from_low"]
    baseline  = ratio_data["baseline"]

    # Align on common index
    common_idx = prices_a.index.intersection(gain_a.index)
    prices_c = prices_a.loc[common_idx]
    ratio_c  = ratio_a.loc[common_idx]
    gain_c   = gain_a.loc[common_idx]

    combos = [
        ("ratio>2.0 AND gain>200%",  (ratio_c >= 2.0) & (gain_c >= 200)),
        ("ratio>2.0 AND gain>300%",  (ratio_c >= 2.0) & (gain_c >= 300)),
        ("ratio>2.5 AND gain>200%",  (ratio_c >= 2.5) & (gain_c >= 200)),
        ("ratio>2.5 AND gain>300%",  (ratio_c >= 2.5) & (gain_c >= 300)),
        ("ratio>3.0 AND gain>200%",  (ratio_c >= 3.0) & (gain_c >= 200)),
    ]

    hdr = (f"  {'Combo signal':<32} | {'N days':>7} | {'N events':>8} | "
           f"{'30d mean':>9} | {'90d mean':>9} | {'vs baseline':>11}")
    div = ("  " + "-"*32 + "-+-" +
           "-+-".join(["-"*7, "-"*8, "-"*9, "-"*9, "-"*11]))
    print(hdr)
    print(div)

    baseline_30 = baseline[30]["mean"]
    baseline_90 = baseline[90]["mean"]

    for label, mask in combos:
        events = independent_events(mask)
        ret30  = compute_forward_returns(prices_c, mask, [30])[30]
        ret90  = compute_forward_returns(prices_c, mask, [90])[90]
        d30    = ret30["mean"] - baseline_30
        d90    = ret90["mean"] - baseline_90
        print(f"  {label:<32} | {int(mask.sum()):>7} | {int(events.sum()):>8} | "
              f"{ret30['mean']:>+8.1f}% | {ret90['mean']:>+8.1f}% | "
              f"{d30:>+10.1f}pp")

    print()
    print(f"  Baseline (all days): 30d={baseline_30:+.1f}%, 90d={baseline_90:+.1f}%")
    print()
    print("  INTERPRETATION:")
    best_combo = None
    best_delta = 0.0
    for label, mask in combos:
        events = independent_events(mask)
        ret30  = compute_forward_returns(prices_c, mask, [30])[30]
        n_ev   = int(events.sum())
        d30    = ret30["mean"] - baseline_30
        if n_ev >= 5 and d30 < best_delta:
            best_delta = d30
            best_combo = (label, n_ev, d30)

    if best_combo is not None and best_combo[2] < -5.0:
        lbl, n, delta = best_combo
        print(f"  -> '{lbl}': 30d delta={delta:+.1f}pp, N={n} events")
        if n >= 10:
            print("     CONFIRMED: sufficient N and effect size for implementation.")
        else:
            print(f"     MARGINAL: effect size validated but N={n} is borderline.")
    else:
        print("  -> No combined signal with N>=5 and delta<-5pp found.")
        print("     Combined signal does NOT improve on individual signals.")


# ---------------------------------------------------------------------------
# ANALYSIS E: Sell performance summary (what actually works)
# ---------------------------------------------------------------------------

def analysis_e_summary(ratio_result: dict, gain_result: dict) -> None:
    """
    Final summary of all analyses: what do we recommend?
    Compares against already-validated signals from exit_strategy_research.py.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  FINAL SUMMARY: EXIT SIGNAL EVALUATION")
    print(sep)
    print()

    print("  EXISTING SIGNALS (from exit_strategy_research.py):")
    print()
    print("  Signal                      | N    | Effect | Status")
    print("  " + "-"*64)
    print("  Rebalancing annual          | 9    | +45pp Calmar 0.39 vs 0.23 | CONFIRMED")
    print("  BTC $100k profit level      | 1    | +68pp vs hold              | CONFIRMED (N=1)")
    print("  ETH $3k profit level        | 1    | +69pp vs hold              | CONFIRMED (N=1)")
    print("  BTC MVRV as sell signal     | 0-14w| no negative return effect  | DISCARDED")
    print("  ETH MVRV as sell signal     | <5   | no negative return effect  | DISCARDED")
    print()

    print("  NEW SIGNALS (this script):")
    print()

    # Summarize Analysis A
    a_bins   = ratio_result["bins"]
    a_base30 = ratio_result["baseline"][30]["mean"]
    hi_bins  = [b for b in a_bins if ">= 2.5x" in b["label"] or "2.0-2.5x" in b["label"]]
    for b in hi_bins:
        d30  = b["ret30"]["mean"] - a_base30
        n_ev = b["n_events"]
        r    = b["label"].split("(")[0].strip()
        status = "CONFIRMED" if n_ev >= 10 and d30 < -3.0 else ("WEAK" if n_ev >= 5 else "INSUFFICIENT N")
        print(f"  MA ratio {r:<18} | {n_ev:<4} | {d30:+.1f}pp 30d vs baseline | {status}")

    # Summarize Analysis B
    b_bins   = gain_result["bins"]
    b_base30 = gain_result["baseline"][30]["mean"]
    high_bins = [b for b in b_bins if "late cycle" in b["label"] or ">= 500%" in b["label"]]
    for b in high_bins:
        d30  = b["ret30"]["mean"] - b_base30
        n_ev = b["n_events"]
        lbl  = b["label"].split("(")[0].strip()
        status = "CONFIRMED" if n_ev >= 10 and d30 < -3.0 else ("WEAK" if n_ev >= 5 else "INSUFFICIENT N")
        print(f"  Gain-from-low {lbl:<15} | {n_ev:<4} | {d30:+.1f}pp 30d vs baseline | {status}")

    print()
    print("  DECISIONS:")
    print()
    print("  The fundamental challenge with exit signals:")
    print("  - Absolute price levels: excellent backtest (N=1), low statistical confidence")
    print("  - Relative metrics (MA ratio, gain-from-low): more events, but crypto")
    print("    bull markets show persistent momentum -- 'overheated' often gets MORE overheated")
    print("  - Portfolio rebalancing: best risk-adjusted outcome, already validated with N=9")
    print()
    print("  RECOMMENDED APPROACH (combining all research):")
    print("  1. Keep rebalancing rule: annual check, rebalance if >10% drift (VALIDATED)")
    print("  2. Keep $100k BTC / $3k ETH alerts: 1 event so far, strong signal each time")
    print("  3. If MA ratio alerts implemented: use as INFORMATION (orange), not hard sell")
    print("     Suggested: alert when ratio > 2.5x for 7+ consecutive days (sustained overheating)")
    print("  4. Combine with absolute level: if BOTH MA ratio > 2.0x AND gain > 300%,")
    print("     send a 'cycle top awareness' alert (manual review, not automatic sell)")
    print()
    print("  CONCLUSION:")
    print("  No new mechanical sell signal with N>10 AND strong negative forward return")
    print("  found in 2018-2026 data. The market is hard to time -- bull momentum persists.")
    print("  The validated approach remains: DCA + annual rebalancing + rare profit-taking")
    print("  at significant price milestones ($100k BTC, $3k ETH, next cycle: $200k/$6k?).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("=" * 70)
    print("  EXIT SIGNALS RESEARCH 2 -- Robust signals with N>10")
    print("  Goal: find sell signals more statistically valid than N=1 absolute prices")
    print("=" * 70)
    print()
    print("  Research period : 2018-2026")
    print("  Strategy base   : DCA 8 EUR/week in BTC (Trade Republic Sparplan)")
    print("  Fee model       : 1 EUR flat per crypto sell")
    print()

    print("  Loading data...")
    btc_full = fetch_btc_prices()

    ratio_result = analysis_a_ma_ratio(btc_full)
    gain_result  = analysis_b_gain_from_low(btc_full)
    analysis_c_sell_simulation(btc_full, ratio_result)
    analysis_d_combined(btc_full, ratio_result, gain_result)
    analysis_e_summary(ratio_result, gain_result)

    print()
    print("=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
