"""funding_negative_research.py
================================
Research 12: BTC negative funding rate as a buy signal.

Motivation
----------
The production alert `funding_negative` (threshold -0.01% on OKX BTC-USD-SWAP)
is the only signal in `alerts/discord_bot.py` without a formal backtest. It
violates the repo methodology (IS/OOS + Mann-Whitney + bootstrap CI). This
script closes that gap.

Hypothesis
----------
When BTC perpetual funding turns significantly negative, shorts are paying
longs, which historically precedes short squeezes. A daily signal based on
the minimum 8h funding of the day should produce a positive forward return
delta vs baseline at 7d / 14d / 30d horizons.

Signal
------
- Daily series: min of the three 8h fundings that day (Binance BTCUSDT perp)
- Signal day: daily_min < threshold
- Thresholds tested: -0.005%, -0.01%, -0.02%, -0.03%, -0.05%
- Cooldown: 1 day (matches 24h production dedup)
- Persistence variant: also tested with "2 consecutive 8h fundings negative
  below threshold within the day"

Data
----
- Funding: Binance fapi `/fundingRate?symbol=BTCUSDT` (available since 2019-10)
- Prices: yfinance BTC-USD daily
- Period: 2019-10-01 to 2026-04-01
- IS: <2023-01-01 (~50% of history)  -- earlier than other scripts because
      funding data starts in late 2019
- OOS: >=2023-01-01

Stats
-----
- Forward horizons: 7d, 14d, 30d
- Mann-Whitney U (alternative="greater")
- Bootstrap 95% CI (N=10,000)
- Verdict per threshold following same rules as Research 11

Run
---
    python research/funding_negative_research.py

Output
------
Table + CONCLUSION, saved to data/research_cache/funding_negative_results.txt
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FETCH_START = "2019-10-01"
END_DATE    = "2026-04-01"
IS_END      = "2023-01-01"
OOS_START   = "2023-01-01"

THRESHOLDS_PCT = [-0.005, -0.01, -0.02, -0.03, -0.05]  # percent
HORIZONS_D     = [7, 14, 30]
COOLDOWN_D     = 1
N_BOOTSTRAP    = 10_000
MIN_N          = 3

BINANCE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_LIMIT  = 1000

CACHE_DIR     = Path(__file__).parent.parent / "data" / "research_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
FUNDING_CACHE = CACHE_DIR / "btc_funding_binance.csv"
BTC_CACHE     = CACHE_DIR / "btc_daily_funding_research.csv"
RESULTS_FILE  = CACHE_DIR / "funding_negative_results.txt"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _http_get_json(url: str) -> list | dict:
    req = Request(url, headers={"User-Agent": "CryptoTrader-Research/1.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_binance_funding() -> pd.DataFrame:
    """Download full BTCUSDT perp funding history from Binance, cache to CSV.

    Paginates forward from FETCH_START using startTime + limit=1000.
    """
    if FUNDING_CACHE.exists():
        print(f"  [cache] Loading funding from {FUNDING_CACHE}")
        df = pd.read_csv(FUNDING_CACHE, parse_dates=["funding_time"])
        return df

    print("  [download] Fetching BTCUSDT funding from Binance (paginated)...")
    start_ms = int(pd.Timestamp(FETCH_START, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(END_DATE, tz="UTC").timestamp() * 1000)

    all_rows: list[dict] = []
    cursor = start_ms
    seen_last = None
    while cursor < end_ms:
        url = (f"{BINANCE_URL}?symbol={BINANCE_SYMBOL}"
               f"&startTime={cursor}&limit={BINANCE_LIMIT}")
        try:
            rows = _http_get_json(url)
        except Exception as e:
            print(f"ERROR fetching funding: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(rows, list) or not rows:
            break
        all_rows.extend(rows)
        last_time = rows[-1]["fundingTime"]
        if seen_last == last_time:
            break
        seen_last = last_time
        cursor = last_time + 1
        print(f"    ... {len(all_rows)} rows, cursor={datetime.fromtimestamp(cursor/1000, tz=timezone.utc)}")
        time.sleep(0.25)

    if not all_rows:
        print("ERROR: Binance returned no funding data", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df["funding_time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df = df[["funding_time", "funding_rate"]].drop_duplicates("funding_time")
    df = df.sort_values("funding_time").reset_index(drop=True)
    df.to_csv(FUNDING_CACHE, index=False)
    print(f"  [cache] Saved {len(df)} rows to {FUNDING_CACHE}")
    return df


def load_btc_daily() -> pd.DataFrame:
    if BTC_CACHE.exists():
        print(f"  [cache] Loading BTC daily from {BTC_CACHE}")
        return pd.read_csv(BTC_CACHE, index_col=0, parse_dates=True)

    print("  [download] Fetching BTC-USD daily from yfinance...")
    import yfinance as yf
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=FETCH_START, end=END_DATE, interval="1d")
    if df.empty:
        print("ERROR: yfinance returned empty BTC data", file=sys.stderr)
        sys.exit(1)
    df = df[["Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.to_csv(BTC_CACHE)
    print(f"  [cache] Saved {len(df)} rows to {BTC_CACHE}")
    return df


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_daily_funding(funding_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 8h fundings to daily metrics: min, mean, count<thr helpers."""
    f = funding_df.copy()
    f["date"] = f["funding_time"].dt.tz_convert("UTC").dt.normalize().dt.tz_localize(None)
    daily = f.groupby("date").agg(
        funding_min=("funding_rate", "min"),
        funding_mean=("funding_rate", "mean"),
        funding_n=("funding_rate", "size"),
        funding_neg_count=("funding_rate", lambda s: int((s < 0).sum())),
    )
    return daily


def build_signals(
    daily_funding: pd.DataFrame,
    threshold: float,
    persistence: bool = False,
) -> pd.DatetimeIndex:
    """Build signal dates for a given threshold.

    - persistence=False: daily_min < threshold
    - persistence=True:  daily_min < threshold AND funding_neg_count >= 2
    """
    thr_decimal = threshold / 100.0  # percent -> decimal
    mask = daily_funding["funding_min"] < thr_decimal
    if persistence:
        mask = mask & (daily_funding["funding_neg_count"] >= 2)

    candidates = daily_funding.index[mask]
    signals = []
    last = None
    for d in sorted(candidates):
        if last is not None and (d - last).days < COOLDOWN_D:
            continue
        signals.append(d)
        last = d
    return pd.DatetimeIndex(signals)


# ---------------------------------------------------------------------------
# Stats (shared pattern with Research 11)
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


def analyse(
    prices: pd.Series,
    signal_dates: pd.DatetimeIndex,
    non_signal_dates: pd.Index,
    horizon: int,
) -> dict:
    fwd = [forward_return(prices, d, horizon) for d in signal_dates]
    fwd = [r for r in fwd if r is not None]

    baseline = [forward_return(prices, d, horizon) for d in non_signal_dates]
    baseline = [r for r in baseline if r is not None]

    is_split = pd.Timestamp(IS_END)
    is_fwd  = [forward_return(prices, d, horizon) for d in signal_dates if d <  is_split]
    oos_fwd = [forward_return(prices, d, horizon) for d in signal_dates if d >= is_split]
    is_fwd  = [r for r in is_fwd  if r is not None]
    oos_fwd = [r for r in oos_fwd if r is not None]

    mean_ret  = float(np.mean(fwd)) if fwd else float("nan")
    base_mean = float(np.mean(baseline)) if baseline else float("nan")
    delta     = mean_ret - base_mean if not (np.isnan(mean_ret) or np.isnan(base_mean)) else float("nan")
    win_rate  = float(np.mean([r > 0 for r in fwd])) if fwd else float("nan")
    ci_lo, ci_hi = bootstrap_mean_ci(np.array(fwd)) if fwd else (float("nan"), float("nan"))

    p_value = float("nan")
    if len(fwd) >= MIN_N and len(baseline) >= MIN_N:
        _, p_value = stats.mannwhitneyu(fwd, baseline, alternative="greater")

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


def verdict_row(res_by_h: dict[int, dict]) -> str:
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
    print("BTC NEGATIVE FUNDING RATE RESEARCH (Research 12)")
    print("=" * 65)
    print(f"  Period: {FETCH_START} - {END_DATE}")
    print(f"  IS: <{IS_END}  /  OOS: >={OOS_START}")
    print(f"  Thresholds: {THRESHOLDS_PCT}%  |  Cooldown: {COOLDOWN_D}d")
    print(f"  Bootstrap: N={N_BOOTSTRAP:,}  |  Horizons: {HORIZONS_D}d")
    print()

    funding_df = fetch_binance_funding()
    daily_funding = build_daily_funding(funding_df)
    print(f"  Funding daily rows: {len(daily_funding)}  "
          f"(first={daily_funding.index.min().date()}, last={daily_funding.index.max().date()})")
    print(f"  8h funding events: {int(daily_funding['funding_n'].sum())}")
    neg_share = (daily_funding['funding_min'] < 0).mean()
    print(f"  Days with ANY negative 8h funding: {neg_share*100:.1f}%")
    print()

    btc = load_btc_daily()
    btc = btc[(btc.index >= FETCH_START) & (btc.index < END_DATE)]
    prices = btc["Close"]
    prices.index = pd.to_datetime(prices.index).normalize()

    # Restrict funding to dates where we also have BTC prices
    daily_funding = daily_funding[daily_funding.index.isin(prices.index)]
    print(f"  Aligned date range: {daily_funding.index.min().date()} -> {daily_funding.index.max().date()}")
    print()

    results_table: list[dict] = []
    variants = [("plain", False), ("persist>=2", True)]

    for variant_name, persistence in variants:
        for thr in THRESHOLDS_PCT:
            signals = build_signals(daily_funding, thr, persistence=persistence)
            non_signal = prices.index.difference(signals)

            res_by_h: dict[int, dict] = {}
            for h in HORIZONS_D:
                res_by_h[h] = analyse(prices, signals, non_signal, h)

            results_table.append({
                "variant": variant_name,
                "thr": thr,
                "res": res_by_h,
                "verdict": verdict_row(res_by_h),
            })

    # -----------------------------------------------------------------------
    # Print + save table
    # -----------------------------------------------------------------------

    header = (f"  {'variant':<10} {'thr':>7}  {'N':>4}  {'N_IS':>4}  {'N_OOS':>5}  "
              f"{'D_7d':>7}  {'p_7d':>6}  {'WR_7':>6}  {'IS_7':>6}  {'OOS_7':>6}  "
              f"{'D_30d':>7}  {'OOS_30':>6}  Verdict")
    sep = "  " + "-" * 110

    out = ["BTC NEGATIVE FUNDING RATE RESEARCH (Research 12)",
           "=" * 65,
           header, sep]
    print(header); print(sep)

    def fp(v, d=1):
        return f"{v*100:+.{d}f}%" if not (v is None or np.isnan(v)) else "  -  "
    def fpv(v):
        return f"{v:.3f}" if not (v is None or np.isnan(v)) else "  -  "

    for row in results_table:
        r7, r30 = row["res"][7], row["res"][30]
        line = (f"  {row['variant']:<10} {row['thr']:>6.3f}%  {r7['n']:>4}  {r7['n_is']:>4}  {r7['n_oos']:>5}  "
                f"{fp(r7['delta']):>7}  {fpv(r7['p_value']):>6}  {fp(r7['win_rate']):>6}  "
                f"{fp(r7['is_mean']):>6}  {fp(r7['oos_mean']):>6}  "
                f"{fp(r30['delta']):>7}  {fp(r30['oos_mean']):>6}  {row['verdict']}")
        print(line); out.append(line)

    print(); out.append("")

    # Conclusion
    red    = [r for r in results_table if r["verdict"].startswith("RED")]
    orange = [r for r in results_table if r["verdict"].startswith("ORANGE")]

    conclusion = ["CONCLUSION", "=========="]
    if red:
        conclusion.append(f"  {len(red)} combo(s) with RED edge:")
        for r in red:
            r7 = r["res"][7]
            conclusion.append(
                f"    {r['variant']} thr={r['thr']:.3f}%  N={r7['n']}  "
                f"d7={r7['delta']*100:+.1f}pp  p={r7['p_value']:.3f}  "
                f"IS={r7['is_mean']*100:+.1f}%  OOS={r7['oos_mean']*100:+.1f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: RED -- production threshold candidate identified.")
        conclusion.append("  ACCION: ajustar FUNDING_RATE_THRESHOLD en alerts/discord_bot.py al mejor combo.")
    elif orange:
        conclusion.append(f"  {len(orange)} combo(s) with ORANGE edge (marginal):")
        for r in orange:
            r7 = r["res"][7]
            conclusion.append(
                f"    {r['variant']} thr={r['thr']:.3f}%  N={r7['n']}  "
                f"d7={r7['delta']*100:+.1f}pp  p={r7['p_value']:.3f}  "
                f"IS={r7['is_mean']*100:+.1f}%  OOS={r7['oos_mean']*100:+.1f}%"
            )
        conclusion.append("")
        conclusion.append("  VERDICT: ORANGE -- evidence weak. Consider downgrading alert to digest-only.")
    else:
        conclusion.append("  All (variant, threshold) combinations: DISCARD.")
        conclusion.append("  VERDICT: DISCARD -- negative funding has no measurable forward edge at these horizons.")
        conclusion.append("  ACCION: eliminar alert funding_negative de discord_bot.py o moverla a digest informativa.")

    for line in conclusion:
        print(line)
    out.extend(conclusion)

    RESULTS_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
