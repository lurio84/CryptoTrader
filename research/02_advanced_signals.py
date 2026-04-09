"""Advanced research: Funding rates, liquidation proxies, and DCA sell signals."""

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from data.sentiment import SentimentCollector
from data.database import init_db

SINCE = "2020-01-01"


def load_btc():
    df = load_backtest_data("BTC/USDT", "1h", since=SINCE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


# ══════════════════════════════════════════════════════════════
# 1. FUNDING RATE AS STANDALONE SIGNAL
# ══════════════════════════════════════════════════════════════
def analysis_funding_signal(df: pd.DataFrame, sentiment: pd.DataFrame):
    print("=" * 70)
    print("  1. FUNDING RATE AS STANDALONE BUY/SELL SIGNAL (BTC)")
    print("     Extreme negative funding = short squeeze = buy opportunity?")
    print("     Extreme positive funding = overleveraged longs = sell signal?")
    print("=" * 70)

    daily = df.set_index("timestamp").resample("D").agg({"close": "last"}).dropna().reset_index()
    daily["date"] = daily["timestamp"].dt.normalize()
    daily["ret_7d"] = daily["close"].pct_change(7).shift(-7) * 100
    daily["ret_30d"] = daily["close"].pct_change(30).shift(-30) * 100

    sent = sentiment.copy()
    sent["timestamp"] = pd.to_datetime(sent["timestamp"], utc=True)
    sent["date"] = sent["timestamp"].dt.normalize()

    merged = daily.merge(sent[["date", "funding_rate_btc"]], on="date", how="left")
    merged = merged.dropna(subset=["funding_rate_btc", "ret_7d"])

    if len(merged) < 50:
        print("  Not enough funding rate data")
        return

    # Bucket funding rates
    buckets = [
        ("Very Negative (<-0.01%)", merged["funding_rate_btc"] < -0.0001),
        ("Slightly Negative", (merged["funding_rate_btc"] >= -0.0001) & (merged["funding_rate_btc"] < 0)),
        ("Low Positive (0-0.01%)", (merged["funding_rate_btc"] >= 0) & (merged["funding_rate_btc"] < 0.0001)),
        ("Normal (0.01-0.03%)", (merged["funding_rate_btc"] >= 0.0001) & (merged["funding_rate_btc"] < 0.0003)),
        ("High (0.03-0.05%)", (merged["funding_rate_btc"] >= 0.0003) & (merged["funding_rate_btc"] < 0.0005)),
        ("Very High (>0.05%)", merged["funding_rate_btc"] >= 0.0005),
    ]

    print(f"\n  {'Funding Bucket':<28} {'N':>5} {'7d Ret':>8} {'7d Win':>7} {'30d Ret':>8} {'30d Win':>8}")
    print(f"  {'-'*68}")

    for label, mask in buckets:
        subset = merged[mask]
        if len(subset) < 5:
            continue
        r7 = subset["ret_7d"].mean()
        w7 = (subset["ret_7d"] > 0).mean() * 100
        r30 = subset["ret_30d"].dropna().mean()
        w30 = (subset["ret_30d"].dropna() > 0).mean() * 100
        print(f"  {label:<28} {len(subset):>5} {r7:>+7.1f}% {w7:>6.0f}% {r30:>+7.1f}% {w30:>7.0f}%")


# ══════════════════════════════════════════════════════════════
# 2. LIQUIDATION PROXY (volume spike + large red candle)
# ══════════════════════════════════════════════════════════════
def analysis_liquidation_proxy(df: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  2. LIQUIDATION CASCADE PROXY")
    print("     Large red candle + extreme volume = forced liquidations")
    print("     Proxy: hourly drop >3% with volume >3x average")
    print("=" * 70)

    df = df.copy()
    df["ret_1h"] = df["close"].pct_change()
    df["vol_avg"] = df["volume"].rolling(168).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"]

    # Liquidation proxy: big red candle + high volume
    thresholds = [
        ("Drop >3% + Vol >3x", (df["ret_1h"] < -0.03) & (df["vol_ratio"] > 3)),
        ("Drop >5% + Vol >3x", (df["ret_1h"] < -0.05) & (df["vol_ratio"] > 3)),
        ("Drop >3% + Vol >5x", (df["ret_1h"] < -0.03) & (df["vol_ratio"] > 5)),
        ("Drop >5% + Vol >5x", (df["ret_1h"] < -0.05) & (df["vol_ratio"] > 5)),
        ("Any drop >5% (no vol filter)", df["ret_1h"] < -0.05),
    ]

    for label, mask in thresholds:
        indices = df.index[mask]

        # Deduplicate (keep first in 24h window)
        deduped = []
        last = -100
        for idx in indices:
            if idx - last > 24:
                deduped.append(idx)
                last = idx

        if len(deduped) < 3:
            print(f"\n  {label}: only {len(deduped)} events, skipping")
            continue

        results = {}
        for hours in [1, 4, 24, 72, 168]:
            rets = []
            for idx in deduped:
                if idx + hours < len(df):
                    ret = (df.loc[idx + hours, "close"] / df.loc[idx, "close"] - 1) * 100
                    rets.append(ret)
            results[hours] = rets

        print(f"\n  {label} (n={len(deduped)}):")
        print(f"    {'Window':<8} {'Avg Ret':>8} {'Median':>8} {'Win%':>6}")
        print(f"    {'-'*35}")
        for hours in [1, 4, 24, 72, 168]:
            rets = results[hours]
            if rets:
                print(f"    {hours}h{'':<5} {np.mean(rets):>+7.1f}% {np.median(rets):>+7.1f}% "
                      f"{sum(1 for r in rets if r>0)/len(rets)*100:>5.0f}%")


# ══════════════════════════════════════════════════════════════
# 3. DCA SELL SIGNAL (when to take profits)
# ══════════════════════════════════════════════════════════════
def analysis_dca_sell(df: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  3. DCA SELL SIGNALS - WHEN TO TAKE PROFITS")
    print("     After a rally, does selling a portion improve total return?")
    print("=" * 70)

    df = df.copy()
    daily = df.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily["ret_30d"] = daily["close"].pct_change(30)
    daily["ret_60d"] = daily["close"].pct_change(60)
    daily["ret_90d"] = daily["close"].pct_change(90)

    # After selling: what happens next 30/60/90 days?
    daily["fwd_30d"] = daily["close"].pct_change(30).shift(-30) * 100
    daily["fwd_60d"] = daily["close"].pct_change(60).shift(-60) * 100

    sell_signals = [
        ("+50% in 30d", daily["ret_30d"] >= 0.50),
        ("+80% in 60d", daily["ret_60d"] >= 0.80),
        ("+100% in 90d", daily["ret_90d"] >= 1.00),
        ("+30% in 30d", daily["ret_30d"] >= 0.30),
        ("+50% in 60d", daily["ret_60d"] >= 0.50),
    ]

    print(f"\n  If you sell when this happens, what return in the NEXT 30/60 days?")
    print(f"  (Negative = you were right to sell, Positive = should have held)\n")
    print(f"  {'Sell Signal':<20} {'N':>5} {'Next 30d':>9} {'30d Win':>8} {'Next 60d':>9} {'60d Win':>8}")
    print(f"  {'-'*65}")

    for label, mask in sell_signals:
        subset = daily[mask].dropna(subset=["fwd_30d"])
        if len(subset) < 3:
            continue
        r30 = subset["fwd_30d"].mean()
        w30 = (subset["fwd_30d"] > 0).mean() * 100
        r60 = subset["fwd_60d"].dropna().mean()
        w60 = (subset["fwd_60d"].dropna() > 0).mean() * 100
        print(f"  {label:<20} {len(subset):>5} {r30:>+8.1f}% {w30:>7.0f}% {r60:>+8.1f}% {w60:>7.0f}%")


# ══════════════════════════════════════════════════════════════
# 4. HALVING CYCLE ANALYSIS
# ══════════════════════════════════════════════════════════════
def analysis_halving_cycle(df: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  4. HALVING CYCLE POSITION AS SIGNAL")
    print("     BTC halving dates: 2020-05-11, 2024-04-19")
    print("     Historically: 12-18 months post-halving = strongest period")
    print("=" * 70)

    halvings = [
        pd.Timestamp("2020-05-11", tz="UTC"),
        pd.Timestamp("2024-04-19", tz="UTC"),
    ]

    daily = df.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()

    for halving in halvings:
        print(f"\n  Halving: {halving.date()}")
        print(f"  {'Period':<25} {'Return':>8}")
        print(f"  {'-'*35}")

        intervals = [
            ("3m before", -90, 0),
            ("0-3m after", 0, 90),
            ("3-6m after", 90, 180),
            ("6-12m after", 180, 365),
            ("12-18m after", 365, 548),
            ("18-24m after", 548, 730),
        ]

        for label, d_start, d_end in intervals:
            start = halving + pd.Timedelta(days=d_start)
            end = halving + pd.Timedelta(days=d_end)

            mask = (daily["timestamp"] >= start) & (daily["timestamp"] <= end)
            period = daily[mask]
            if len(period) < 10:
                continue
            ret = (period["close"].iloc[-1] / period["close"].iloc[0] - 1) * 100
            print(f"  {label:<25} {ret:>+7.1f}%")


# ══════════════════════════════════════════════════════════════
# 5. COMBINED: CRASH DCA + BEST NEW SIGNALS
# ══════════════════════════════════════════════════════════════
def analysis_combined_signals(df: pd.DataFrame, sentiment: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  5. TESTING COMBINED SIGNALS")
    print("     Crash (-15%) + Funding negative + Volume spike")
    print("     Does combining improve the crash signal?")
    print("=" * 70)

    df = df.copy()
    df["ret_24h"] = df["close"].pct_change(24)
    df["vol_avg"] = df["volume"].rolling(168).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"]
    df["date"] = df["timestamp"].dt.normalize()

    # Add funding
    sent = sentiment.copy()
    sent["timestamp"] = pd.to_datetime(sent["timestamp"], utc=True)
    sent["date"] = sent["timestamp"].dt.normalize()
    df = df.merge(sent[["date", "funding_rate_btc"]], on="date", how="left")
    df["funding_rate_btc"] = df["funding_rate_btc"].ffill()

    # Forward returns
    df["fwd_7d"] = df["close"].pct_change(168).shift(-168) * 100
    df["fwd_30d"] = df["close"].pct_change(720).shift(-720) * 100

    signals = [
        ("Crash -10% only", df["ret_24h"] <= -0.10),
        ("Crash -10% + high volume (>2x)", (df["ret_24h"] <= -0.10) & (df["vol_ratio"] > 2)),
        ("Crash -10% + neg funding", (df["ret_24h"] <= -0.10) & (df["funding_rate_btc"] < 0)),
        ("Crash -10% + high vol + neg fund", (df["ret_24h"] <= -0.10) & (df["vol_ratio"] > 2) & (df["funding_rate_btc"] < 0)),
        ("Crash -15% only", df["ret_24h"] <= -0.15),
        ("Crash -15% + high volume (>2x)", (df["ret_24h"] <= -0.15) & (df["vol_ratio"] > 2)),
    ]

    print(f"\n  {'Signal':<35} {'N':>5} {'7d Ret':>8} {'7d Win':>7} {'30d Ret':>8} {'30d Win':>7}")
    print(f"  {'-'*73}")

    for label, mask in signals:
        # Deduplicate
        indices = df.index[mask]
        deduped = []
        last = -100
        for idx in indices:
            if idx - last > 24:
                deduped.append(idx)
                last = idx

        rets_7d = [df.loc[i, "fwd_7d"] for i in deduped if i < len(df) and pd.notna(df.loc[i, "fwd_7d"])]
        rets_30d = [df.loc[i, "fwd_30d"] for i in deduped if i < len(df) and pd.notna(df.loc[i, "fwd_30d"])]

        if len(rets_7d) < 3:
            print(f"  {label:<35} {len(deduped):>5}  too few events")
            continue

        r7 = np.mean(rets_7d)
        w7 = sum(1 for r in rets_7d if r > 0) / len(rets_7d) * 100
        r30 = np.mean(rets_30d) if rets_30d else 0
        w30 = (sum(1 for r in rets_30d if r > 0) / len(rets_30d) * 100) if rets_30d else 0

        print(f"  {label:<35} {len(deduped):>5} {r7:>+7.1f}% {w7:>6.0f}% {r30:>+7.1f}% {w30:>6.0f}%")


def main():
    init_db()
    sent_collector = SentimentCollector()
    sentiment = sent_collector.load_sentiment()
    df = load_btc()

    print(f"Loaded {len(df)} candles, {len(sentiment)} days sentiment\n")

    analysis_funding_signal(df, sentiment)
    analysis_liquidation_proxy(df)
    analysis_dca_sell(df)
    analysis_halving_cycle(df)
    analysis_combined_signals(df, sentiment)


if __name__ == "__main__":
    main()
