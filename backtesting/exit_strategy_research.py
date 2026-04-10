"""Exit Strategy Research
=======================
Three analyses to decide whether exit/rebalancing rules add value:

  1. Portfolio rebalancing by % threshold (2018-2026)
     Does trimming over-weight crypto back to target improve risk-adjusted returns?

  2. BTC profit-taking at absolute price levels
     Would selling X% of holdings at $50k/$100k/... beat pure hold?

  3. BTC MVRV as pause/sell signal
     Unlike ETH MVRV, BTC MVRV historically reached 4-5 at cycle tops.
     Does it have predictive value?

Usage:
    pip install yfinance  (first time only, for Analysis 1)
    python backtesting/exit_strategy_research.py

Data sources (all free, no API key needed):
    - BTC/ETH prices  : CoinGecko public API
    - BTC MVRV        : CoinMetrics community API
    - SPY/SOXX/O/URA  : Yahoo Finance via yfinance
"""

from __future__ import annotations

import os
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

START_DATE = "2018-01-01"
END_DATE   = "2026-04-01"

# Weekly DCA amounts in EUR (from CLAUDE.md)
WEEKLY_EUR = {
    "btc":     8.0,   # BTC Sparplan
    "eth":     2.0,   # ETH Sparplan
    "sp500":  16.0,   # S&P 500
    "semis":   4.0,   # MSCI Global Semiconductors
    "reit":    4.0,   # Realty Income
    "uranium": 1.0,   # Uranium
}
TOTAL_WEEKLY = sum(WEEKLY_EUR.values())   # 35 EUR/week
TARGET_PCT   = {k: v / TOTAL_WEEKLY for k, v in WEEKLY_EUR.items()}

# Yahoo Finance tickers (best proxies for the ETFs available in Trade Republic)
YF_TICKERS = {
    "btc":     "BTC-USD",  # Bitcoin
    "eth":     "ETH-USD",  # Ethereum
    "sp500":   "SPY",      # S&P 500
    "semis":   "SOXX",     # PHLX Semiconductor (proxy for MSCI Global Semis)
    "reit":    "O",        # Realty Income Corp (direct)
    "uranium": "URA",      # Global X Uranium ETF
}
YF_TRAD_KEYS = {"sp500", "semis", "reit", "uranium"}

# Trade Republic fee model
CRYPTO_SELL_FEE_EUR = 1.0   # flat 1 EUR per crypto sell transaction
TRAD_SELL_FEE       = 0.0   # ETF sells also 0 fee at TR

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

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


def sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    """Returns max drawdown as a positive percentage."""
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(abs(dd.min()) * 100)


def cagr(start_val: float, end_val: float, years: float) -> float:
    if start_val <= 0 or years <= 0:
        return 0.0
    return float((end_val / start_val) ** (1.0 / years) - 1) * 100


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_crypto_coinmetrics(asset: str, key: str) -> pd.DataFrame:
    """Daily USD prices from CoinMetrics community API. Returns DataFrame(date, price)."""
    cache = CACHE_DIR / f"{key}_cm.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    {key}: {len(cached)} days from cache (CoinMetrics)")
        return cached

    print(f"    {key}: fetching prices from CoinMetrics...")
    all_rows: list[dict] = []
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params: dict = {
        "assets": asset,
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
        raise ValueError(f"CoinMetrics returned no price data for {asset}")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df["price"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    df = df[["date", "price"]].dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    _save_cache(df, cache)
    print(f"    {key}: {len(df)} days fetched and cached")
    return df


def fetch_yfinance(ticker: str, key: str) -> pd.DataFrame:
    """Daily closing prices from Yahoo Finance. Returns DataFrame(date, price)."""
    cache = CACHE_DIR / f"{key}_yf.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    {key} ({ticker}): {len(cached)} days from cache")
        return cached

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance not installed. Run: pip install yfinance")

    print(f"    {key} ({ticker}): fetching from Yahoo Finance...")
    t = yf.Ticker(ticker)
    hist = t.history(start=START_DATE, end=END_DATE, auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No Yahoo Finance data for {ticker}")

    df = hist[["Close"]].reset_index()
    df.columns = ["date", "price"]
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    _save_cache(df, cache)
    print(f"    {key} ({ticker}): {len(df)} days fetched and cached")
    return df


def fetch_btc_mvrv() -> pd.DataFrame:
    """BTC MVRV from CoinMetrics community API. Returns DataFrame(date, mvrv)."""
    cache = CACHE_DIR / "btc_mvrv.csv"
    cached = _load_cache(cache)
    if cached is not None:
        print(f"    BTC MVRV: {len(cached)} days from cache")
        return cached

    print("    BTC MVRV: fetching from CoinMetrics...")
    all_rows: list[dict] = []
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params: dict = {
        "assets": "btc",
        "metrics": "CapMVRVCur",
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
        # Parse next_page_url into params
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(next_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        time.sleep(0.5)

    if not all_rows:
        raise ValueError("CoinMetrics returned no BTC MVRV data")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df["mvrv"] = pd.to_numeric(df["CapMVRVCur"], errors="coerce")
    df = df[["date", "mvrv"]].dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    _save_cache(df, cache)
    print(f"    BTC MVRV: {len(df)} days fetched and cached")
    return df


def _build_weekly_dates(index: pd.DatetimeIndex, start: str) -> set:
    """Every ~7 calendar days, find nearest available trading day."""
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
# ANALYSIS 1 -- Portfolio rebalancing
# ---------------------------------------------------------------------------

def analysis_rebalancing(all_prices: dict[str, pd.DataFrame]) -> None:
    sep = "=" * 70

    print(f"\n{sep}")
    print("  ANALYSIS 1: PORTFOLIO REBALANCING (2018-2026)")
    print(sep)
    print()
    print("  Target allocation (Trade Republic Sparplan):")
    for k, pct in TARGET_PCT.items():
        print(f"    {k:<10}: {pct*100:5.1f}%  ({WEEKLY_EUR[k]:.0f} EUR/week)")
    print(f"    Total DCA  : 35 EUR/week = ~{35*52/12:.0f} EUR/month")
    print()
    print("  Fee model:")
    print("    Crypto sells  : 1 EUR flat per transaction (Trade Republic)")
    print("    Trad ETF sells: 0 EUR (Trade Republic: no fee)")
    print("    New buys      : 0 EUR (via existing Sparplan)")
    print()

    # --- Build unified daily price table ---
    series = {}
    for key, df in all_prices.items():
        s = df.set_index("date")["price"]
        s.index = pd.to_datetime(s.index)
        series[key] = s

    combined = pd.DataFrame(series)
    combined = combined.loc[START_DATE:END_DATE].ffill().dropna()
    combined.index = pd.to_datetime(combined.index)

    print(f"  Data: {len(combined)} trading days "
          f"({combined.index[0].date()} to {combined.index[-1].date()})")

    assets = list(WEEKLY_EUR.keys())
    weekly_dates = _build_weekly_dates(combined.index, combined.index[0].strftime("%Y-%m-%d"))
    years = (combined.index[-1] - combined.index[0]).days / 365.25

    # --- Simulation core ---
    def simulate(threshold: float | None, calendar_months: int | None) -> dict:
        """
        threshold      : rebalance if any asset deviates > X from target (0.15 = 15%)
        calendar_months: rebalance every N months regardless
        Set both to None for "never rebalance".
        """
        units       = {k: 0.0 for k in assets}
        total_fees  = 0.0
        n_rebalance = 0
        last_rebal  = None
        equity_vals = []

        for date, row in combined.iterrows():
            # Weekly DCA (no fee)
            if date in weekly_dates:
                for asset in assets:
                    units[asset] += WEEKLY_EUR[asset] / row[asset]

            # Portfolio value
            vals = {k: units[k] * row[k] for k in assets}
            port = sum(vals.values())
            equity_vals.append(port)

            if port == 0:
                continue

            # Rebalancing trigger
            do_rebal = False
            if threshold is not None:
                for k in assets:
                    if abs(vals[k] / port - TARGET_PCT[k]) > threshold:
                        do_rebal = True
                        break
            if calendar_months is not None:
                if last_rebal is None or (date - last_rebal).days >= calendar_months * 30:
                    do_rebal = True

            # 30-day cooldown to avoid thrashing
            if last_rebal is not None and (date - last_rebal).days < 30:
                do_rebal = False

            if do_rebal:
                target_vals = {k: port * TARGET_PCT[k] for k in assets}
                sells = {k: vals[k] - target_vals[k] for k in assets if vals[k] > target_vals[k]}
                buys  = {k: target_vals[k] - vals[k] for k in assets if vals[k] < target_vals[k]}

                proceeds = 0.0
                for asset, sell_val in sells.items():
                    # Trade Republic: 1 EUR flat per crypto sell, 0 for ETFs
                    fee = CRYPTO_SELL_FEE_EUR if asset in ("btc", "eth") else TRAD_SELL_FEE
                    net = sell_val - fee
                    total_fees += fee
                    units[asset] -= sell_val / row[asset]
                    proceeds += net

                total_buy = sum(buys.values())
                if total_buy > 0 and proceeds > 0:
                    for asset, buy_val in buys.items():
                        alloc = buy_val / total_buy * proceeds
                        units[asset] += alloc / row[asset]

                n_rebalance += 1
                last_rebal = date

        # Final state
        last_row   = combined.iloc[-1]
        invested   = len(weekly_dates) * TOTAL_WEEKLY   # approx total invested
        final_port = sum(units[k] * last_row[k] for k in assets)
        final_alloc = {k: units[k] * last_row[k] / final_port * 100 for k in assets}

        equity = pd.Series(equity_vals, index=combined.index)
        daily_ret = equity.pct_change().dropna()

        total_ret = (final_port - invested) / invested * 100
        ann_ret   = cagr(invested, final_port, years)
        sh        = sharpe(daily_ret)
        mdd       = max_drawdown(equity)
        calmar    = ann_ret / mdd if mdd > 0 else 0.0

        return {
            "invested": invested, "final": final_port,
            "total_ret": total_ret, "cagr": ann_ret,
            "sharpe": sh, "max_dd": mdd, "calmar": calmar,
            "fees": total_fees, "rebalances": n_rebalance,
            "final_alloc": final_alloc,
        }

    strategies = [
        ("Never rebalance   ", None,  None),
        ("Rebal >10% drift  ", 0.10,  None),
        ("Rebal >15% drift  ", 0.15,  None),
        ("Rebal >20% drift  ", 0.20,  None),
        ("Rebal >25% drift  ", 0.25,  None),
        ("Rebal quarterly   ", None,  3),
        ("Rebal annually    ", None,  12),
    ]

    print("  Running simulations...")
    results = []
    for name, thr, cal in strategies:
        r = simulate(thr, cal)
        r["name"] = name
        results.append(r)

    # --- Results table ---
    print()
    hdr = (f"  {'Strategy':<22}"
           f" | {'Final EUR':>10}"
           f" | {'Total Ret':>9}"
           f" | {'CAGR':>7}"
           f" | {'Sharpe':>7}"
           f" | {'MaxDD':>7}"
           f" | {'Calmar':>7}"
           f" | {'Rebal':>6}"
           f" | {'Fees EUR':>9}")
    div = "  " + "-"*22 + "-+-" + "-+-".join(["-"*10, "-"*9, "-"*7, "-"*7, "-"*7, "-"*7, "-"*6, "-"*9])
    print(hdr)
    print(div)
    for r in results:
        print(f"  {r['name']:<22}"
              f" | {r['final']:>10,.0f}"
              f" | {r['total_ret']:>8.1f}%"
              f" | {r['cagr']:>6.1f}%"
              f" | {r['sharpe']:>7.2f}"
              f" | {r['max_dd']:>6.1f}%"
              f" | {r['calmar']:>7.2f}"
              f" | {r['rebalances']:>6}"
              f" | {r['fees']:>9.2f}")

    # Final allocation drift (never-rebalance case)
    drift = results[0]
    print()
    print("  Final allocation drift (Never rebalance):")
    for k, pct in drift["final_alloc"].items():
        target = TARGET_PCT[k] * 100
        bar = "+" if pct > target else "-"
        print(f"    {k:<10}: {pct:5.1f}%  (target {target:.1f}%,  drift {pct-target:+.1f}%)")

    # --- Verdict ---
    baseline = results[0]
    best_risk_adj = max(results[1:], key=lambda x: x["calmar"])
    best_abs      = max(results[1:], key=lambda x: x["total_ret"])

    print()
    print("  VERDICT:")
    improvement = best_risk_adj["calmar"] - baseline["calmar"]
    if improvement > 0.05 * abs(baseline["calmar"]):
        print(f"  -> Rebalancing HELPS risk-adjusted returns.")
        print(f"     Best: '{best_risk_adj['name'].strip()}' "
              f"Calmar={best_risk_adj['calmar']:.2f} vs baseline {baseline['calmar']:.2f}")
    else:
        print(f"  -> Rebalancing does NOT significantly improve risk-adjusted returns.")
        print(f"     Best Calmar: {best_risk_adj['calmar']:.2f} vs baseline {baseline['calmar']:.2f}")

    if best_abs["total_ret"] > baseline["total_ret"]:
        print(f"  -> '{best_abs['name'].strip()}' ALSO beats pure DCA on absolute return!")
        print(f"     {best_abs['total_ret']:+.1f}% vs {baseline['total_ret']:+.1f}%")
    else:
        print(f"  -> No rebalancing strategy beats pure DCA on absolute return.")
        print(f"     (Selling outperforming crypto to buy laggards reduces total return.)")
        print(f"     Cost range: {baseline['total_ret'] - best_abs['total_ret']:.1f}% less than hold.")


# ---------------------------------------------------------------------------
# ANALYSIS 2 -- BTC profit-taking at absolute price levels
# ---------------------------------------------------------------------------

def analysis_profit_taking(btc_prices: pd.DataFrame) -> None:
    sep = "=" * 70

    print(f"\n{sep}")
    print("  ANALYSIS 2: BTC PROFIT-TAKING AT ABSOLUTE PRICE LEVELS")
    print(sep)
    print()
    print(f"  Base strategy: DCA {WEEKLY_EUR['btc']:.0f} EUR/week into BTC since {START_DATE}")
    print(f"  Sell proceeds : kept as cash (not reinvested)")
    print(f"  Fee per sell  : 1 EUR flat (Trade Republic crypto)")
    print()

    prices = btc_prices.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices.loc[START_DATE:END_DATE].dropna().sort_index()
    prices = prices[~prices.index.duplicated(keep="first")]

    weekly_dates = _build_weekly_dates(prices.index, prices.index[0].strftime("%Y-%m-%d"))
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    total_weeks = len(weekly_dates)
    total_invested = total_weeks * WEEKLY_EUR["btc"]

    print(f"  Period        : {prices.index[0].date()} to {prices.index[-1].date()} ({years:.1f} years)")
    print(f"  BTC price     : ${prices.iloc[0]:,.0f} -> ${prices.iloc[-1]:,.0f}  "
          f"(peak: ${prices.max():,.0f})")
    print(f"  Total invested: ~{total_invested:,.0f} EUR over {total_weeks} weeks")
    print()

    # Scenarios: list of (price_usd, sell_fraction) tuples, fired once each
    SCENARIOS: list[tuple[str, list[tuple[float, float]]]] = [
        ("Pure hold (baseline)",                       []),
        ("Sell 25% at $69k  (2021 peak area)",         [(69_000,  0.25)]),
        ("Sell 20% at $100k",                          [(100_000, 0.20)]),
        ("Sell 25% at $100k, 25% at $200k",            [(100_000, 0.25), (200_000, 0.25)]),
        ("Sell 33% at $100k",                          [(100_000, 0.33)]),
        ("Sell 25% at $75k, 25% at $150k",             [(75_000,  0.25), (150_000, 0.25)]),
        ("Sell 20% at $50k, 20% at $100k, 20% at $200k",
                                                       [(50_000, 0.20), (100_000, 0.20), (200_000, 0.20)]),
        ("Sell 15% at $30k, 15% at $60k, 15% at $100k",
                                                       [(30_000, 0.15), (60_000,  0.15), (100_000, 0.15)]),
        ("Sell 50% at $20k  (2017 peak, lucky timing)", [(20_000, 0.50)]),
    ]

    def simulate_btc(levels: list[tuple[float, float]]) -> dict:
        btc_units   = 0.0
        cash        = 0.0
        invested    = 0.0
        total_fees  = 0.0
        sell_log: list[dict] = []
        triggered: set[float] = set()

        for date, price in prices.items():
            if date in weekly_dates:
                btc_units += WEEKLY_EUR["btc"] / price
                invested  += WEEKLY_EUR["btc"]

            for level, frac in levels:
                if level not in triggered and price >= level:
                    sell_units = btc_units * frac
                    sell_val   = sell_units * price
                    fee        = CRYPTO_SELL_FEE_EUR   # 1 EUR flat per TR transaction
                    net        = sell_val - fee
                    btc_units -= sell_units
                    cash      += net
                    total_fees += fee
                    triggered.add(level)
                    sell_log.append({
                        "date": date, "price": price,
                        "pct_sold": frac * 100, "eur_received": net,
                    })

        final_btc   = btc_units * prices.iloc[-1]
        final_total = final_btc + cash
        tot_ret     = (final_total - invested) / invested * 100
        ann         = cagr(invested, final_total, years)

        return {
            "invested": invested, "final_btc": final_btc, "cash": cash,
            "final_total": final_total, "total_ret": tot_ret, "cagr": ann,
            "fees": total_fees, "btc_remaining": btc_units, "sell_log": sell_log,
        }

    results = []
    for name, levels in SCENARIOS:
        r = simulate_btc(levels)
        r["name"] = name
        results.append(r)

    baseline = results[0]

    # --- Results table ---
    hdr = (f"  {'Strategy':<50}"
           f" | {'Final EUR':>10}"
           f" | {'Total Ret':>9}"
           f" | {'CAGR':>7}"
           f" | {'vs Hold':>8}"
           f" | {'Fees':>7}")
    div = "  " + "-"*50 + "-+-" + "-+-".join(["-"*10, "-"*9, "-"*7, "-"*8, "-"*7])
    print(hdr)
    print(div)
    for r in results:
        diff = r["total_ret"] - baseline["total_ret"]
        print(f"  {r['name']:<50}"
              f" | {r['final_total']:>10,.0f}"
              f" | {r['total_ret']:>8.1f}%"
              f" | {r['cagr']:>6.1f}%"
              f" | {diff:>+7.1f}%"
              f" | {r['fees']:>7.2f}")

    # --- Sell event detail ---
    print()
    print("  Sell events by scenario:")
    for r in results[1:]:
        if not r["sell_log"]:
            print(f"    [{r['name'][:40]}] : no sells triggered (price never reached)")
        else:
            print(f"    [{r['name'][:50]}]")
            for s in r["sell_log"]:
                print(f"      {s['date'].date()} @ ${s['price']:>8,.0f} : "
                      f"sold {s['pct_sold']:.0f}% -> {s['eur_received']:,.0f} EUR")

    # --- Key observation: cycle-aware analysis ---
    print()
    print("  Cycle breakdown (approximate BTC price peaks):")
    cycle_data = [
        ("2017 peak (~$19k)",  "2017-12-17", 19_000),
        ("2021 peak (~$69k)",  "2021-11-10", 69_000),
        ("2024+ cycle (>$100k)", "2024-12-17", 108_000),
    ]
    for label, date_str, peak in cycle_data:
        d = pd.Timestamp(date_str)
        if d in prices.index or (prices.index.searchsorted(d) < len(prices)):
            idx = prices.index.searchsorted(d)
            actual = prices.iloc[min(idx, len(prices)-1)]
            print(f"    {label}: actual data ${actual:,.0f}")
        else:
            print(f"    {label}: ${peak:,.0f} (approximate)")

    # --- Verdict ---
    better = [r for r in results[1:] if r["total_ret"] > baseline["total_ret"]]
    worse  = [r for r in results[1:] if r["total_ret"] < baseline["total_ret"]]

    print()
    print("  VERDICT:")
    if better:
        best = max(better, key=lambda x: x["total_ret"])
        print(f"  -> Some strategies beat pure hold:")
        print(f"     Best: '{best['name'][:50]}' -> {best['total_ret']:+.1f}% vs hold {baseline['total_ret']:+.1f}%")
        print(f"     This requires PERFECT timing (selling near actual tops).")
    else:
        print(f"  -> Pure hold beats ALL profit-taking strategies over this period.")

    if worse:
        worst = min(worse, key=lambda x: x["total_ret"])
        opp_cost = baseline["total_ret"] - worst["total_ret"]
        print(f"  -> Worst case opportunity cost: -{opp_cost:.1f}% vs hold")
        print(f"     '{worst['name'][:50]}'")

    print(f"  -> Key risk: BTC continued higher after most 'logical' sell levels.")
    print(f"     Selling at $20k-$100k would have looked smart for months,")
    print(f"     then painful as price kept climbing.")


# ---------------------------------------------------------------------------
# ANALYSIS 3 -- BTC MVRV as pause/sell signal
# ---------------------------------------------------------------------------

def analysis_btc_mvrv(btc_prices: pd.DataFrame, btc_mvrv: pd.DataFrame) -> None:
    sep = "=" * 70

    print(f"\n{sep}")
    print("  ANALYSIS 3: BTC MVRV AS PAUSE/SELL SIGNAL")
    print(sep)
    print()
    print("  Context: ETH MVRV > 3.0 was DISCARDED (never occurred since 2017).")
    print("  BTC MVRV historically reached 4-5 at 2013/2017 tops.")
    print("  Question: does BTC MVRV predict negative forward returns reliably?")
    print()

    # --- Merge prices and MVRV ---
    prices = btc_prices.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices[~prices.index.duplicated(keep="first")]

    mvrv = btc_mvrv.set_index("date")["mvrv"]
    mvrv.index = pd.to_datetime(mvrv.index)
    mvrv = mvrv[~mvrv.index.duplicated(keep="first")]

    merged = pd.DataFrame({"price": prices, "mvrv": mvrv}).dropna().sort_index()

    print(f"  MVRV data: {merged.index[0].date()} to {merged.index[-1].date()} ({len(merged)} days)")
    print()
    print("  MVRV distribution:")
    q = merged["mvrv"].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    print(f"    Min/Max : {merged['mvrv'].min():.2f} / {merged['mvrv'].max():.2f}")
    print(f"    Mean    : {merged['mvrv'].mean():.2f}  (Median: {merged['mvrv'].median():.2f})")
    print(f"    P90     : {q[0.9]:.2f}   P95: {q[0.95]:.2f}   P99: {q[0.99]:.2f}")

    # Historical peaks
    print()
    print("  Top 15 MVRV readings (all-time):")
    top = merged.nlargest(15, "mvrv")
    for date, row in top.iterrows():
        print(f"    {date.date()}  MVRV={row['mvrv']:.2f}  BTC=${row['price']:>10,.0f}")

    # Cycle MVRV peaks
    print()
    print("  Cycle MVRV peaks:")
    cycles = {
        "2013 cycle": ("2012-01-01", "2014-01-01"),
        "2017 cycle": ("2016-01-01", "2018-06-01"),
        "2021 cycle": ("2020-01-01", "2022-06-01"),
        "2024 cycle": ("2023-01-01", "2026-04-01"),
    }
    for label, (start, end) in cycles.items():
        window = merged.loc[start:end]
        if window.empty:
            print(f"    {label}: no data")
            continue
        peak_idx = window["mvrv"].idxmax()
        peak_row = window.loc[peak_idx]
        print(f"    {label}: peak MVRV={peak_row['mvrv']:.2f} on {peak_idx.date()} "
              f" (BTC=${peak_row['price']:>9,.0f})")

    # --- Forward return analysis ---
    HORIZONS   = [30, 90, 180, 365]
    THRESHOLDS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]

    def fwd_returns(mask: pd.Series) -> dict[int, dict]:
        out = {}
        for h in HORIZONS:
            rets = []
            for date in merged[mask].index:
                future = date + timedelta(days=h)
                pos = merged.index.searchsorted(future)
                if pos >= len(merged):
                    continue
                r = (merged["price"].iloc[pos] - merged.loc[date, "price"]) / merged.loc[date, "price"] * 100
                rets.append(r)
            if rets:
                arr = np.array(rets)
                out[h] = {"mean": float(np.mean(arr)), "median": float(np.median(arr)),
                           "win": float((arr > 0).mean() * 100), "n": len(arr)}
            else:
                out[h] = {"mean": 0.0, "median": 0.0, "win": 0.0, "n": 0}
        return out

    all_mask = pd.Series(True, index=merged.index)
    baseline = fwd_returns(all_mask)

    print()
    print("  Forward return analysis by MVRV threshold:")
    print("  (When MVRV >= X, what happens to BTC over the next N days?)")
    print()

    # Header
    h_parts = [f"  {'Condition':<18}", f"{'N days':>7}"]
    for h in HORIZONS:
        h_parts.append(f"  {h}d mean   win ")
    print(" | ".join(h_parts))
    print("  " + "-"*18 + "-+-" + "-"*7 + "-+-" + "-+-".join("-"*16 for _ in HORIZONS))

    # Baseline row
    r_parts = [f"  {'ALL DAYS':<18}", f"{len(merged):>7}"]
    for h in HORIZONS:
        b = baseline[h]
        r_parts.append(f"  {b['mean']:>+7.1f}%  {b['win']:>4.0f}%")
    print(" | ".join(r_parts))

    thresh_results = []
    for thr in THRESHOLDS:
        mask = merged["mvrv"] >= thr
        n = int(mask.sum())
        if n < 3:
            print(f"  {'MVRV >= '+str(thr):<18} | {n:>7} | (fewer than 3 occurrences, skip)")
            continue
        fwd = fwd_returns(mask)
        r_parts = [f"  {'MVRV >= '+str(thr):<18}", f"{n:>7}"]
        for h in HORIZONS:
            f = fwd[h]
            r_parts.append(f"  {f['mean']:>+7.1f}%  {f['win']:>4.0f}%")
        print(" | ".join(r_parts))
        thresh_results.append({"threshold": thr, "n": n, "fwd": fwd})

    # --- Pause DCA simulation (from 2018 onward where we have full data) ---
    print()
    print("  Pause DCA simulation (pause weekly BTC buy when MVRV >= threshold):")
    print("  Resume: always resume when MVRV drops back below threshold.")
    print("  Cash from paused weeks is kept, not deployed elsewhere.")
    print()

    sim_data = merged.loc[START_DATE:END_DATE].dropna()
    sim_weeks = _build_weekly_dates(sim_data.index, sim_data.index[0].strftime("%Y-%m-%d"))
    sim_years = (sim_data.index[-1] - sim_data.index[0]).days / 365.25

    def sim_pause(pause_thr: float) -> dict:
        btc_units   = 0.0
        cash_saved  = 0.0
        invested    = 0.0
        paused_wks  = 0
        active_wks  = 0

        for date, row in sim_data.iterrows():
            if date not in sim_weeks:
                continue
            if row["mvrv"] >= pause_thr:
                cash_saved += WEEKLY_EUR["btc"]
                invested   += WEEKLY_EUR["btc"]
                paused_wks += 1
            else:
                btc_units += WEEKLY_EUR["btc"] / row["price"]
                invested  += WEEKLY_EUR["btc"]
                active_wks += 1

        last_price   = sim_data["price"].iloc[-1]
        final_btc    = btc_units * last_price
        final_total  = final_btc + cash_saved
        tot_ret      = (final_total - invested) / invested * 100
        ann          = cagr(invested, final_total, sim_years)
        return {
            "final": final_total, "total_ret": tot_ret, "cagr": ann,
            "paused": paused_wks, "active": active_wks,
            "cash": cash_saved,
        }

    # Baseline: always DCA
    bl_units = 0.0
    bl_inv   = 0.0
    for date, row in sim_data.iterrows():
        if date in sim_weeks:
            bl_units += WEEKLY_EUR["btc"] / row["price"]
            bl_inv   += WEEKLY_EUR["btc"]
    bl_final  = bl_units * sim_data["price"].iloc[-1]
    bl_return = (bl_final - bl_inv) / bl_inv * 100
    bl_cagr   = cagr(bl_inv, bl_final, sim_years)

    hdr = (f"  {'Strategy':<35}"
           f" | {'Final EUR':>10}"
           f" | {'Total Ret':>9}"
           f" | {'CAGR':>7}"
           f" | {'vs DCA':>8}"
           f" | {'Paused wks':>11}"
           f" | {'Cash saved':>11}")
    print(hdr)
    print("  " + "-"*35 + "-+-" + "-+-".join(["-"*10, "-"*9, "-"*7, "-"*8, "-"*11, "-"*11]))
    print(f"  {'Always DCA (baseline)':<35}"
          f" | {bl_final:>10,.0f}"
          f" | {bl_return:>8.1f}%"
          f" | {bl_cagr:>6.1f}%"
          f" | {'--':>8}"
          f" | {'--':>11}"
          f" | {'--':>11}")

    pause_results = []
    for thr in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        r = sim_pause(thr)
        vs = r["total_ret"] - bl_return
        print(f"  {'Pause DCA when MVRV >= '+str(thr):<35}"
              f" | {r['final']:>10,.0f}"
              f" | {r['total_ret']:>8.1f}%"
              f" | {r['cagr']:>6.1f}%"
              f" | {vs:>+7.1f}%"
              f" | {r['paused']:>11}"
              f" | {r['cash']:>11,.0f}")
        pause_results.append({**r, "threshold": thr, "vs": vs})

    # Current MVRV
    current_mvrv  = merged["mvrv"].iloc[-1]
    current_date  = merged.index[-1]
    current_price = merged["price"].iloc[-1]

    print()
    print(f"  Current status  ({current_date.date()}):")
    print(f"    BTC price     : ${current_price:,.0f}")
    print(f"    BTC MVRV      : {current_mvrv:.2f}")

    # --- Verdict ---
    print()
    print("  VERDICT:")

    # Check if MVRV > 3 predicts below-baseline returns
    mvrv3 = next((x for x in thresh_results if x["threshold"] == 3.0), None)
    if mvrv3:
        f30  = mvrv3["fwd"][30]
        f180 = mvrv3["fwd"][180]
        b30  = baseline[30]
        b180 = baseline[180]
        delta_30  = f30["mean"]  - b30["mean"]
        delta_180 = f180["mean"] - b180["mean"]

        if f30["win"] < 50 and f30["mean"] < 0:
            print(f"  -> MVRV > 3.0 predicts NEGATIVE 30d returns: "
                  f"{f30['mean']:+.1f}% (win rate {f30['win']:.0f}%)")
            print(f"     vs baseline 30d: {b30['mean']:+.1f}% (win rate {b30['win']:.0f}%)")
        elif delta_30 < -10 and delta_180 < -20:
            print(f"  -> MVRV > 3.0 predicts significantly LOWER returns:")
            print(f"     30d:  {f30['mean']:+.1f}% vs baseline {b30['mean']:+.1f}%  (delta {delta_30:+.1f}%)")
            print(f"     180d: {f180['mean']:+.1f}% vs baseline {b180['mean']:+.1f}%  (delta {delta_180:+.1f}%)")
        else:
            print(f"  -> MVRV > 3.0 does NOT reliably predict underperformance:")
            print(f"     30d:  {f30['mean']:+.1f}% (win {f30['win']:.0f}%) vs baseline {b30['mean']:+.1f}% (win {b30['win']:.0f}%)")
            print(f"     180d: {f180['mean']:+.1f}% (win {f180['win']:.0f}%) vs baseline {b180['mean']:+.1f}% (win {b180['win']:.0f}%)")

    # Pause simulation verdict
    best_pause = max(pause_results, key=lambda x: x["total_ret"])
    if best_pause["vs"] > 2.0:
        print(f"  -> Pausing DCA at MVRV >= {best_pause['threshold']} would have HELPED: "
              f"{best_pause['vs']:+.1f}% vs always-DCA")
    else:
        print(f"  -> Pausing DCA adds minimal value even at best threshold "
              f"({best_pause['vs']:+.1f}% at MVRV >= {best_pause['threshold']})")
        print(f"     Leaving cash idle (not redeployed) costs more than being overexposed at peaks.")

    # Context vs ETH MVRV finding
    print()
    mvrv_max_hist = merged.loc[:"2022-01-01"]["mvrv"].max()
    mvrv_2021     = merged.loc["2020-01-01":"2022-06-01"]["mvrv"].max()
    print(f"  Additional context:")
    print(f"    BTC MVRV peak (pre-2022): {mvrv_max_hist:.2f}")
    print(f"    BTC MVRV peak (2021 bull): {mvrv_2021:.2f}")
    print(f"    ETH MVRV peak (2021 bull): ~2.0  (reason ETH signal was discarded)")
    print(f"    -> BTC MVRV reaches higher extremes, so if signal exists, it is at higher thresholds.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sep = "=" * 70

    print(sep)
    print("  EXIT STRATEGY RESEARCH -- CryptoTrader Advisor")
    print(sep)
    print(f"  Run date : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Period   : {START_DATE} to {END_DATE}")
    print(f"  Cache dir: {CACHE_DIR}")
    print()

    # --- Check yfinance ---
    try:
        import yfinance as yf  # noqa: F401
        yf_ok = True
    except ImportError:
        yf_ok = False
        print("  WARNING: yfinance not installed. Analysis 1 will be skipped.")
        print("  Fix: .venv/Scripts/pip install yfinance")
        print()

    # --- Fetch data ---
    print("  Loading data...")

    # Crypto prices from CoinMetrics (no auth needed, same source as MVRV)
    btc_prices = fetch_crypto_coinmetrics("btc", "btc")
    time.sleep(0.8)
    eth_prices = fetch_crypto_coinmetrics("eth", "eth")
    time.sleep(0.8)
    btc_mvrv   = fetch_btc_mvrv()

    # Traditional asset prices + crypto via Yahoo Finance (for Analysis 1)
    all_prices: dict[str, pd.DataFrame] = {}
    if yf_ok:
        for key, ticker in YF_TICKERS.items():
            try:
                all_prices[key] = fetch_yfinance(ticker, key)
                time.sleep(0.3)
            except Exception as exc:
                print(f"    WARNING: could not fetch {ticker}: {exc}")

    print()

    # --- Run analyses ---

    trad_ok = all(k in all_prices for k in YF_TRAD_KEYS)
    if yf_ok and "btc" in all_prices and "eth" in all_prices and trad_ok:
        analysis_rebalancing(all_prices)
    else:
        print(f"\n  Analysis 1 SKIPPED (traditional asset data unavailable)")

    analysis_profit_taking(btc_prices)

    analysis_btc_mvrv(btc_prices, btc_mvrv)

    print(f"\n{sep}")
    print("  Research complete.")
    print(sep)
    print()
    print("  To clear cache and re-fetch fresh data:")
    print(f"    del {CACHE_DIR}\\*.csv   (Windows)")
    print(f"    rm {CACHE_DIR}/*.csv    (Linux/Mac)")


if __name__ == "__main__":
    main()
