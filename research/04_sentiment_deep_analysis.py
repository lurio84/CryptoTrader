"""Deep analysis of sentiment data and its relationship with price."""

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from backtesting.dca_engine import DCABacktestEngine
from config.settings import DCASettings
from data.sentiment import SentimentCollector
from data.database import init_db

SINCE = "2023-01-01"


def analyze_sentiment_distribution(df_sentiment: pd.DataFrame):
    """How often is the market in each sentiment zone?"""
    print("=" * 65)
    print("  1. SENTIMENT DISTRIBUTION (how often each zone occurs)")
    print("=" * 65)

    bins = [(0, 15, "Extreme Fear"), (16, 30, "Fear"), (31, 50, "Neutral"),
            (51, 75, "Greed"), (76, 100, "Extreme Greed")]

    total = len(df_sentiment)
    print(f"\n  Total days: {total}\n")
    print(f"  {'Zone':<16} {'Days':>6} {'%':>7} {'Avg Duration':>14} {'Longest Streak':>15}")
    print(f"  {'-'*60}")

    for lo, hi, label in bins:
        mask = df_sentiment["fear_greed_value"].between(lo, hi)
        days = mask.sum()
        pct = days / total * 100

        # Calculate streaks
        streaks = []
        current = 0
        for val in mask:
            if val:
                current += 1
            else:
                if current > 0:
                    streaks.append(current)
                current = 0
        if current > 0:
            streaks.append(current)

        avg_streak = np.mean(streaks) if streaks else 0
        max_streak = max(streaks) if streaks else 0

        print(f"  {label:<16} {days:>6} {pct:>6.1f}% {avg_streak:>12.1f}d {max_streak:>14}d")

    print(f"\n  Mean F&G: {df_sentiment['fear_greed_value'].mean():.1f}")
    print(f"  Median F&G: {df_sentiment['fear_greed_value'].median():.0f}")


def analyze_price_after_sentiment(df_candles: pd.DataFrame, df_sentiment: pd.DataFrame, symbol: str):
    """What happens to price AFTER each sentiment zone?"""
    print(f"\n{'='*65}")
    print(f"  2. PRICE PERFORMANCE AFTER SENTIMENT ({symbol})")
    print(f"     'If you buy on day X, what return do you get after N days?'")
    print(f"{'='*65}")

    # Daily prices
    df_candles = df_candles.copy()
    df_candles["timestamp"] = pd.to_datetime(df_candles["timestamp"], utc=True)
    daily = df_candles.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily["date"] = daily["timestamp"].dt.normalize()

    df_sentiment = df_sentiment.copy()
    df_sentiment["timestamp"] = pd.to_datetime(df_sentiment["timestamp"], utc=True)
    df_sentiment["date"] = df_sentiment["timestamp"].dt.normalize()

    merged = daily.merge(df_sentiment[["date", "fear_greed_value"]], on="date", how="inner")

    bins = [(0, 15, "Extreme Fear"), (16, 30, "Fear"), (31, 50, "Neutral"),
            (51, 75, "Greed"), (76, 100, "Extreme Greed")]
    horizons = [7, 14, 30, 60, 90]

    print(f"\n  Average return after buying in each sentiment zone:")
    print(f"\n  {'Zone':<16} {'N':>4}", end="")
    for h in horizons:
        print(f"  {h}d", end="")
    print(f"  {'Win% 30d':>9}")
    print(f"  {'-'*70}")

    for lo, hi, label in bins:
        mask = merged["fear_greed_value"].between(lo, hi)
        indices = merged.index[mask]

        returns_by_horizon = {}
        for h in horizons:
            rets = []
            for idx in indices:
                if idx + h < len(merged):
                    buy_price = merged.loc[idx, "close"]
                    future_price = merged.loc[idx + h, "close"]
                    ret = (future_price - buy_price) / buy_price * 100
                    rets.append(ret)
            returns_by_horizon[h] = rets

        n = len(indices)
        print(f"  {label:<16} {n:>4}", end="")
        for h in horizons:
            rets = returns_by_horizon[h]
            avg = np.mean(rets) if rets else 0
            print(f"  {avg:>+5.1f}%", end="")

        # Win rate at 30d
        rets_30 = returns_by_horizon[30]
        win_pct = sum(1 for r in rets_30 if r > 0) / len(rets_30) * 100 if rets_30 else 0
        print(f"  {win_pct:>8.1f}%")


def analyze_funding_correlation(df_sentiment: pd.DataFrame, df_candles: pd.DataFrame, symbol: str):
    """How does funding rate correlate with future returns?"""
    print(f"\n{'='*65}")
    print(f"  3. FUNDING RATE ANALYSIS ({symbol})")
    print(f"{'='*65}")

    df_candles = df_candles.copy()
    df_candles["timestamp"] = pd.to_datetime(df_candles["timestamp"], utc=True)
    daily = df_candles.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily["date"] = daily["timestamp"].dt.normalize()

    df_s = df_sentiment.copy()
    df_s["timestamp"] = pd.to_datetime(df_s["timestamp"], utc=True)
    df_s["date"] = df_s["timestamp"].dt.normalize()

    merged = daily.merge(df_s[["date", "funding_rate_btc"]], on="date", how="inner")
    merged = merged.dropna(subset=["funding_rate_btc"])

    if merged.empty or len(merged) < 30:
        print("  Not enough funding rate data for analysis")
        return

    # 30-day forward return
    merged["return_30d"] = merged["close"].shift(-30) / merged["close"] - 1

    # Bucket funding rates
    merged["funding_bucket"] = pd.cut(
        merged["funding_rate_btc"],
        bins=[-np.inf, -0.0001, 0, 0.0002, 0.0005, np.inf],
        labels=["Very Negative", "Slightly Neg", "Low Positive", "Medium Pos", "High Positive"],
    )

    print(f"\n  Funding rate vs 30-day forward return:")
    print(f"\n  {'Funding Bucket':<16} {'Days':>6} {'Avg 30d Ret':>12} {'Win% 30d':>10} {'Avg Funding':>12}")
    print(f"  {'-'*60}")

    for bucket in ["Very Negative", "Slightly Neg", "Low Positive", "Medium Pos", "High Positive"]:
        mask = merged["funding_bucket"] == bucket
        subset = merged[mask].dropna(subset=["return_30d"])
        if len(subset) < 3:
            continue
        avg_ret = subset["return_30d"].mean() * 100
        win_pct = (subset["return_30d"] > 0).mean() * 100
        avg_fund = subset["funding_rate_btc"].mean() * 100
        print(f"  {bucket:<16} {len(subset):>6} {avg_ret:>+11.1f}% {win_pct:>9.1f}% {avg_fund:>11.4f}%")


def analyze_optimal_strategy(df_candles: pd.DataFrame, df_sentiment: pd.DataFrame, symbol: str):
    """Test many DCA variants to find what actually works."""
    print(f"\n{'='*65}")
    print(f"  4. DCA STRATEGY COMPARISON ({symbol})")
    print(f"{'='*65}")

    strategies = [
        ("Fixed DCA (50/week)", DCASettings(
            multiplier_extreme_fear=1.0, multiplier_fear=1.0,
            multiplier_neutral=1.0, multiplier_greed=1.0, multiplier_extreme_greed=1.0,
        )),
        ("Default Smart DCA", DCASettings()),
        ("Aggressive contrarian", DCASettings(
            multiplier_extreme_fear=3.0, multiplier_fear=1.5,
            multiplier_neutral=0.5, multiplier_greed=0.0, multiplier_extreme_greed=0.0,
        )),
        ("Mild contrarian", DCASettings(
            multiplier_extreme_fear=1.5, multiplier_fear=1.25,
            multiplier_neutral=1.0, multiplier_greed=0.75, multiplier_extreme_greed=0.5,
        )),
        ("Fear-only buyer", DCASettings(
            multiplier_extreme_fear=2.0, multiplier_fear=1.5,
            multiplier_neutral=0.0, multiplier_greed=0.0, multiplier_extreme_greed=0.0,
        )),
        ("Skip extreme greed only", DCASettings(
            multiplier_extreme_fear=1.5, multiplier_fear=1.2,
            multiplier_neutral=1.0, multiplier_greed=1.0, multiplier_extreme_greed=0.0,
        )),
    ]

    print(f"\n  {'Strategy':<25} {'Return':>8} {'Invested':>10} {'FinalVal':>10} "
          f"{'AvgPrice':>10} {'Buys':>5}")
    print(f"  {'-'*72}")

    for name, dca_settings in strategies:
        engine = DCABacktestEngine(dca_settings=dca_settings)
        try:
            result = engine.run(df_candles, df_sentiment, symbol)
            print(f"  {name:<25} {result.smart_return_pct:>+7.1f}% "
                  f"{result.smart_total_invested:>10.0f} {result.smart_final_value:>10.0f} "
                  f"{result.smart_avg_buy_price:>10.0f} {result.smart_total_buys:>5}")
        except (ValueError, ZeroDivisionError):
            print(f"  {name:<25} {'ERROR':>8}")


def analyze_buy_timing(df_candles: pd.DataFrame, df_sentiment: pd.DataFrame, symbol: str):
    """When did Smart DCA buy vs Fixed DCA, and at what prices?"""
    print(f"\n{'='*65}")
    print(f"  5. BUY TIMING ANALYSIS ({symbol})")
    print(f"     Smart DCA (default) vs what a fixed DCA would have done")
    print(f"{'='*65}")

    engine = DCABacktestEngine()
    result = engine.run(df_candles, df_sentiment, symbol)

    if result.buy_log.empty:
        print("  No buys to analyze")
        return

    log = result.buy_log.copy()

    # Monthly breakdown
    log["month"] = pd.to_datetime(log["date"]).dt.to_period("M")
    monthly = log.groupby("month").agg(
        buys=("amount_usdt", "count"),
        invested=("amount_usdt", "sum"),
        avg_fg=("fear_greed", "mean"),
        avg_mult=("multiplier", "mean"),
        avg_price=("price", "mean"),
    )

    print(f"\n  Monthly breakdown:")
    print(f"  {'Month':<10} {'Buys':>5} {'Invested':>10} {'Avg F&G':>8} {'AvgMult':>8} {'AvgPrice':>10}")
    print(f"  {'-'*55}")

    for period, row in monthly.iterrows():
        print(f"  {str(period):<10} {row['buys']:>5.0f} {row['invested']:>10.0f} "
              f"{row['avg_fg']:>8.0f} {row['avg_mult']:>7.2f}x {row['avg_price']:>10.0f}")

    # Price percentile analysis
    print(f"\n  Price analysis:")
    all_prices = df_candles.set_index(
        pd.to_datetime(df_candles["timestamp"], utc=True)
    ).resample("D")["close"].last().dropna()

    smart_avg = log["price"].mean()
    overall_avg = all_prices.mean()
    pct = (all_prices < smart_avg).mean() * 100

    print(f"    Smart DCA avg buy price:  {smart_avg:,.0f}")
    print(f"    Overall avg daily price:  {overall_avg:,.0f}")
    print(f"    Price percentile of buys: {pct:.0f}th (lower = bought cheaper)")
    print(f"    Savings vs avg price:     {(1 - smart_avg/overall_avg)*100:+.1f}%")


def main():
    init_db()
    sent_collector = SentimentCollector()
    df_sentiment = sent_collector.load_sentiment()
    print(f"Loaded {len(df_sentiment)} days of sentiment data\n")

    # Analysis on BTC
    df_btc = load_backtest_data("BTC/USDT", "1h", since=SINCE)

    analyze_sentiment_distribution(df_sentiment)
    analyze_price_after_sentiment(df_btc, df_sentiment, "BTC/USDT")
    analyze_funding_correlation(df_sentiment, df_btc, "BTC/USDT")
    analyze_optimal_strategy(df_btc, df_sentiment, "BTC/USDT")
    analyze_buy_timing(df_btc, df_sentiment, "BTC/USDT")

    # Repeat key analyses for ETH
    print(f"\n\n{'#'*65}")
    print(f"  REPEATING KEY ANALYSES FOR ETH/USDT")
    print(f"{'#'*65}")

    df_eth = load_backtest_data("ETH/USDT", "1h", since=SINCE)
    analyze_price_after_sentiment(df_eth, df_sentiment, "ETH/USDT")
    analyze_optimal_strategy(df_eth, df_sentiment, "ETH/USDT")


if __name__ == "__main__":
    main()
