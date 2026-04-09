"""Deep research: 10 statistical analyses on real crypto data."""

import numpy as np
import pandas as pd
from scipy import stats
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from data.sentiment import SentimentCollector
from data.database import init_db

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
SINCE = "2020-01-01"


def load_all_data():
    """Load candles and sentiment."""
    init_db()
    data = {}
    for symbol in SYMBOLS:
        try:
            df = load_backtest_data(symbol, "1h", since=SINCE)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["return_1h"] = df["close"].pct_change()
            data[symbol] = df
        except ValueError:
            pass

    sent_collector = SentimentCollector()
    sentiment = sent_collector.load_sentiment()
    sentiment["timestamp"] = pd.to_datetime(sentiment["timestamp"], utc=True)
    return data, sentiment


# ══════════════════════════════════════════════════════════════
# 1. HOURLY AND DAY-OF-WEEK RETURNS
# ══════════════════════════════════════════════════════════════
def analysis_1_temporal_patterns(data: dict):
    print("=" * 70)
    print("  1. RETURN BY HOUR (UTC) AND DAY OF WEEK")
    print("     Question: Are there hours/days with consistent directional bias?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT"]:
        df = data[symbol].copy()
        df["hour"] = df["timestamp"].dt.hour
        df["dow"] = df["timestamp"].dt.dayofweek  # 0=Mon

        print(f"\n  {symbol} - Avg hourly return (%) by day of week:")
        print(f"  {'Hour':<6}", end="")
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for d in days:
            print(f" {d:>6}", end="")
        print()
        print(f"  {'-'*55}")

        # Top hours
        hourly = df.groupby("hour")["return_1h"].agg(["mean", "count"])
        hourly["annualized"] = hourly["mean"] * 8760 * 100

        best_hours = hourly.nlargest(3, "mean")
        worst_hours = hourly.nsmallest(3, "mean")

        print(f"\n  Best 3 hours:  ", end="")
        for h, row in best_hours.iterrows():
            t_stat = row["mean"] / (df[df["hour"] == h]["return_1h"].std() / np.sqrt(row["count"]))
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"{h:02d}UTC={row['mean']*100:+.03f}%{sig}  ", end="")
        print()
        print(f"  Worst 3 hours: ", end="")
        for h, row in worst_hours.iterrows():
            t_stat = row["mean"] / (df[df["hour"] == h]["return_1h"].std() / np.sqrt(row["count"]))
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"{h:02d}UTC={row['mean']*100:+.03f}%{sig}  ", end="")
        print()

        # Day of week
        dow = df.groupby("dow")["return_1h"].agg(["mean", "count", "std"])
        print(f"\n  Day-of-week avg return:")
        for i, d in enumerate(days):
            if i in dow.index:
                r = dow.loc[i]
                t_stat = r["mean"] / (r["std"] / np.sqrt(r["count"]))
                sig = "*" if abs(t_stat) > 1.96 else ""
                print(f"    {d}: {r['mean']*100:+.04f}% (n={r['count']:.0f}) {sig}")


# ══════════════════════════════════════════════════════════════
# 2. MONTH START/END EFFECT
# ══════════════════════════════════════════════════════════════
def analysis_2_month_effect(data: dict):
    print(f"\n{'='*70}")
    print("  2. MONTH START/END EFFECT")
    print("     Question: Do first/last 3 days of month have different returns?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        df = data[symbol].copy()
        df["day"] = df["timestamp"].dt.day
        df["days_in_month"] = df["timestamp"].dt.days_in_month

        # Last 3 days
        df["is_month_end"] = df["day"] >= (df["days_in_month"] - 2)
        # First 3 days
        df["is_month_start"] = df["day"] <= 3
        # Middle
        df["is_middle"] = ~df["is_month_end"] & ~df["is_month_start"]

        start_ret = df[df["is_month_start"]]["return_1h"].mean() * 72 * 100  # ~3 days
        end_ret = df[df["is_month_end"]]["return_1h"].mean() * 72 * 100
        mid_ret = df[df["is_middle"]]["return_1h"].mean() * 72 * 100

        print(f"\n  {symbol} - Avg 3-day return by position in month:")
        print(f"    First 3 days:  {start_ret:+.2f}%")
        print(f"    Middle days:   {mid_ret:+.2f}%")
        print(f"    Last 3 days:   {end_ret:+.2f}%")


# ══════════════════════════════════════════════════════════════
# 3. MEAN REVERSION AFTER CRASH
# ══════════════════════════════════════════════════════════════
def analysis_3_post_crash(data: dict):
    print(f"\n{'='*70}")
    print("  3. MEAN REVERSION AFTER CRASHES")
    print("     Question: What happens 1d/3d/7d after a 10%/15%/20% drop?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        df = data[symbol].copy()
        # Rolling 24h return
        df["ret_24h"] = df["close"].pct_change(24)

        for threshold in [-0.10, -0.15, -0.20]:
            crash_mask = df["ret_24h"] <= threshold
            crash_indices = df.index[crash_mask]

            # Deduplicate (keep first of consecutive crashes)
            deduped = []
            last = -100
            for idx in crash_indices:
                if idx - last > 24:
                    deduped.append(idx)
                    last = idx

            results = {"24h": [], "72h": [], "168h": []}
            for idx in deduped:
                for hours, key in [(24, "24h"), (72, "72h"), (168, "168h")]:
                    if idx + hours < len(df):
                        ret = (df.loc[idx + hours, "close"] / df.loc[idx, "close"] - 1) * 100
                        results[key].append(ret)

            n = len(deduped)
            if n < 3:
                continue

            print(f"\n  {symbol} after {threshold*100:.0f}% crash (n={n}):")
            for key in ["24h", "72h", "168h"]:
                rets = results[key]
                if rets:
                    avg = np.mean(rets)
                    med = np.median(rets)
                    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                    print(f"    {key}: avg={avg:+.1f}% median={med:+.1f}% win_rate={wr:.0f}% (n={len(rets)})")


# ══════════════════════════════════════════════════════════════
# 4. CONTINUATION AFTER RALLY
# ══════════════════════════════════════════════════════════════
def analysis_4_post_rally(data: dict):
    print(f"\n{'='*70}")
    print("  4. CONTINUATION AFTER RALLIES")
    print("     Question: Do 20%+ rallies in 7d continue or revert?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        df = data[symbol].copy()
        df["ret_7d"] = df["close"].pct_change(168)

        for threshold in [0.15, 0.20, 0.30]:
            rally_mask = df["ret_7d"] >= threshold
            rally_indices = df.index[rally_mask]

            deduped = []
            last = -200
            for idx in rally_indices:
                if idx - last > 168:
                    deduped.append(idx)
                    last = idx

            if len(deduped) < 3:
                continue

            results = {"24h": [], "72h": [], "168h": []}
            for idx in deduped:
                for hours, key in [(24, "24h"), (72, "72h"), (168, "168h")]:
                    if idx + hours < len(df):
                        ret = (df.loc[idx + hours, "close"] / df.loc[idx, "close"] - 1) * 100
                        results[key].append(ret)

            n = len(deduped)
            print(f"\n  {symbol} after +{threshold*100:.0f}% rally (n={n}):")
            for key in ["24h", "72h", "168h"]:
                rets = results[key]
                if rets:
                    avg = np.mean(rets)
                    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                    print(f"    {key}: avg={avg:+.1f}% win_rate={wr:.0f}%")


# ══════════════════════════════════════════════════════════════
# 5. ATR AS PREDICTOR
# ══════════════════════════════════════════════════════════════
def analysis_5_atr_predictor(data: dict):
    print(f"\n{'='*70}")
    print("  5. ATR (VOLATILITY) AS PREDICTOR")
    print("     Question: Does high/low ATR predict future direction or magnitude?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT"]:
        df = data[symbol].copy()
        # ATR-14 on hourly
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14).mean()

        # Percentile rank vs rolling 720h (30d)
        df["atr_pct"] = df["atr_14"].rolling(720).rank(pct=True)
        df["ret_48h"] = df["close"].pct_change(48).shift(-48)
        df["abs_ret_48h"] = df["ret_48h"].abs()

        df = df.dropna(subset=["atr_pct", "ret_48h"])
        df["atr_quintile"] = pd.qcut(df["atr_pct"], 5, labels=["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"])

        print(f"\n  {symbol} - 48h forward return by ATR quintile:")
        print(f"  {'Quintile':<12} {'Avg Ret':>8} {'Abs Ret':>8} {'Win%':>6} {'N':>6}")
        print(f"  {'-'*45}")

        for q in ["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"]:
            subset = df[df["atr_quintile"] == q]
            avg = subset["ret_48h"].mean() * 100
            abs_avg = subset["abs_ret_48h"].mean() * 100
            wr = (subset["ret_48h"] > 0).mean() * 100
            print(f"  {q:<12} {avg:>+7.2f}% {abs_avg:>7.2f}% {wr:>5.1f}% {len(subset):>6}")


# ══════════════════════════════════════════════════════════════
# 6. CORRELATION BREAKDOWN
# ══════════════════════════════════════════════════════════════
def analysis_6_correlation(data: dict):
    print(f"\n{'='*70}")
    print("  6. CORRELATION BREAKDOWN BETWEEN PAIRS")
    print("     Question: When BTC-altcoin correlation breaks, what happens next?")
    print("=" * 70)

    btc = data["BTC/USDT"][["timestamp", "return_1h"]].rename(columns={"return_1h": "btc_ret"})

    for alt_symbol in ["ETH/USDT", "SOL/USDT"]:
        alt = data[alt_symbol][["timestamp", "return_1h"]].rename(columns={"return_1h": "alt_ret"})
        merged = btc.merge(alt, on="timestamp")
        merged["corr_168h"] = merged["btc_ret"].rolling(168).corr(merged["alt_ret"])

        # Forward return of altcoin
        alt_prices = data[alt_symbol][["timestamp", "close"]].rename(columns={"close": "alt_close"})
        merged = merged.merge(alt_prices, on="timestamp")
        merged["alt_ret_72h"] = merged["alt_close"].pct_change(72).shift(-72) * 100

        merged = merged.dropna()

        # Correlation buckets
        bins = [(-1, 0.3, "Low (<0.3)"), (0.3, 0.6, "Medium"), (0.6, 0.85, "High"), (0.85, 1.01, "Very High")]

        print(f"\n  BTC vs {alt_symbol} - 72h alt return by correlation level:")
        print(f"  {'Correlation':<16} {'Avg Alt 72h':>12} {'Win%':>6} {'N':>6}")
        print(f"  {'-'*45}")

        for lo, hi, label in bins:
            mask = merged["corr_168h"].between(lo, hi)
            subset = merged[mask]
            if len(subset) < 20:
                continue
            avg = subset["alt_ret_72h"].mean()
            wr = (subset["alt_ret_72h"] > 0).mean() * 100
            print(f"  {label:<16} {avg:>+11.1f}% {wr:>5.1f}% {len(subset):>6}")


# ══════════════════════════════════════════════════════════════
# 7. VOLUME ANOMALY
# ══════════════════════════════════════════════════════════════
def analysis_7_volume_anomaly(data: dict):
    print(f"\n{'='*70}")
    print("  7. VOLUME ANOMALY AS SIGNAL")
    print("     Question: Does 3x+ volume predict directional moves?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        df = data[symbol].copy()
        df["vol_avg_168h"] = df["volume"].rolling(168).mean()
        df["vol_zscore"] = (df["volume"] - df["vol_avg_168h"]) / df["volume"].rolling(168).std()
        df["is_green"] = df["close"] > df["open"]
        df["ret_24h_fwd"] = df["close"].pct_change(24).shift(-24) * 100

        df = df.dropna(subset=["vol_zscore", "ret_24h_fwd"])

        # High volume events (z > 3)
        high_vol = df[df["vol_zscore"] > 3]
        green_hv = high_vol[high_vol["is_green"]]
        red_hv = high_vol[~high_vol["is_green"]]

        print(f"\n  {symbol} - 24h forward return after volume spike (z>3):")
        for label, subset in [("Green candle", green_hv), ("Red candle", red_hv)]:
            if len(subset) < 5:
                continue
            avg = subset["ret_24h_fwd"].mean()
            wr = (subset["ret_24h_fwd"] > 0).mean() * 100
            print(f"    {label}: avg={avg:+.2f}% win_rate={wr:.0f}% (n={len(subset)})")


# ══════════════════════════════════════════════════════════════
# 8. DISTANCE TO SMA-200D (4800h)
# ══════════════════════════════════════════════════════════════
def analysis_8_sma_distance(data: dict):
    print(f"\n{'='*70}")
    print("  8. DISTANCE TO SMA-200D AS BUY SIGNAL")
    print("     Question: Buying X% below SMA-200d, what returns?")
    print("=" * 70)

    for symbol in ["BTC/USDT", "ETH/USDT"]:
        df = data[symbol].copy()
        df["sma_4800"] = df["close"].rolling(4800).mean()
        df["pct_from_sma"] = (df["close"] / df["sma_4800"] - 1) * 100
        df["ret_30d_fwd"] = df["close"].pct_change(720).shift(-720) * 100

        df = df.dropna(subset=["pct_from_sma", "ret_30d_fwd"])

        buckets = [(-100, -20, "<-20%"), (-20, -10, "-20% to -10%"), (-10, 0, "-10% to 0%"),
                   (0, 10, "0% to +10%"), (10, 20, "+10% to +20%"), (20, 100, ">+20%")]

        print(f"\n  {symbol} - 30d forward return by distance from SMA-200d:")
        print(f"  {'Distance':<15} {'Avg 30d':>8} {'Med 30d':>8} {'Win%':>6} {'N':>6}")
        print(f"  {'-'*48}")

        for lo, hi, label in buckets:
            mask = df["pct_from_sma"].between(lo, hi)
            subset = df[mask]
            if len(subset) < 20:
                continue
            avg = subset["ret_30d_fwd"].mean()
            med = subset["ret_30d_fwd"].median()
            wr = (subset["ret_30d_fwd"] > 0).mean() * 100
            print(f"  {label:<15} {avg:>+7.1f}% {med:>+7.1f}% {wr:>5.1f}% {len(subset):>6}")


# ══════════════════════════════════════════════════════════════
# 9. COMBINED: F&G + SMA DISTANCE
# ══════════════════════════════════════════════════════════════
def analysis_9_combined_signal(data: dict, sentiment: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  9. COMBINED SIGNAL: Fear & Greed + Distance to SMA-200d")
    print("     Question: Does combining both filters produce better entries?")
    print("=" * 70)

    df = data["BTC/USDT"].copy()
    df["sma_4800"] = df["close"].rolling(4800).mean()
    df["pct_from_sma"] = (df["close"] / df["sma_4800"] - 1) * 100
    df["ret_30d_fwd"] = df["close"].pct_change(720).shift(-720) * 100
    df["date"] = df["timestamp"].dt.normalize()

    sent = sentiment.copy()
    sent["date"] = pd.to_datetime(sent["timestamp"], utc=True).dt.normalize()

    df = df.merge(sent[["date", "fear_greed_value"]], on="date", how="left")
    df["fear_greed_value"] = df["fear_greed_value"].ffill()
    df = df.dropna(subset=["pct_from_sma", "ret_30d_fwd", "fear_greed_value"])

    # Daily samples only (avoid overcounting)
    df = df.groupby("date").last().reset_index()

    signals = [
        ("F&G < 25 only", (df["fear_greed_value"] < 25)),
        ("Below SMA only", (df["pct_from_sma"] < 0)),
        ("F&G<25 + Below SMA", (df["fear_greed_value"] < 25) & (df["pct_from_sma"] < 0)),
        ("F&G<25 + >10% below SMA", (df["fear_greed_value"] < 25) & (df["pct_from_sma"] < -10)),
        ("F&G<15 + Below SMA", (df["fear_greed_value"] < 15) & (df["pct_from_sma"] < 0)),
        ("All days (baseline)", pd.Series(True, index=df.index)),
    ]

    print(f"\n  BTC/USDT - 30d forward return by combined signal:")
    print(f"  {'Signal':<28} {'Avg 30d':>8} {'Med 30d':>8} {'Win%':>6} {'N':>5}")
    print(f"  {'-'*58}")

    for label, mask in signals:
        subset = df[mask]
        if len(subset) < 5:
            print(f"  {label:<28} {'N/A':>8} (n={len(subset)})")
            continue
        avg = subset["ret_30d_fwd"].mean()
        med = subset["ret_30d_fwd"].median()
        wr = (subset["ret_30d_fwd"] > 0).mean() * 100
        print(f"  {label:<28} {avg:>+7.1f}% {med:>+7.1f}% {wr:>5.1f}% {len(subset):>5}")


# ══════════════════════════════════════════════════════════════
# 10. IN-SAMPLE vs OUT-OF-SAMPLE VALIDATION
# ══════════════════════════════════════════════════════════════
def analysis_10_robustness(data: dict, sentiment: pd.DataFrame):
    print(f"\n{'='*70}")
    print("  10. ROBUSTNESS CHECK: IN-SAMPLE (2023-2024) vs OUT-OF-SAMPLE (2025-26)")
    print("      Question: Do the patterns survive out-of-sample?")
    print("=" * 70)

    df = data["BTC/USDT"].copy()
    df["ret_24h"] = df["close"].pct_change(24)
    df["ret_7d_fwd"] = df["close"].pct_change(168).shift(-168) * 100
    df["sma_4800"] = df["close"].rolling(4800).mean()
    df["pct_from_sma"] = (df["close"] / df["sma_4800"] - 1) * 100
    df["date"] = df["timestamp"].dt.normalize()

    sent = sentiment.copy()
    sent["date"] = pd.to_datetime(sent["timestamp"], utc=True).dt.normalize()
    df = df.merge(sent[["date", "fear_greed_value"]], on="date", how="left")
    df["fear_greed_value"] = df["fear_greed_value"].ffill()
    df = df.dropna(subset=["ret_7d_fwd", "fear_greed_value"])

    split_date = pd.Timestamp("2025-01-01", tz="UTC")
    in_sample = df[df["timestamp"] < split_date]
    out_sample = df[df["timestamp"] >= split_date]

    patterns = [
        ("Buy after 10% crash (24h)", lambda d: d["ret_24h"] <= -0.10),
        ("Buy when F&G < 20", lambda d: d["fear_greed_value"] < 20),
        ("Buy when below SMA-200d", lambda d: d["pct_from_sma"] < 0),
        ("Buy when F&G<25 + below SMA", lambda d: (d["fear_greed_value"] < 25) & (d["pct_from_sma"] < 0)),
    ]

    print(f"\n  {'Pattern':<30} {'IS Avg 7d':>10} {'IS Win%':>8} {'IS N':>5} "
          f"{'OOS Avg 7d':>10} {'OOS Win%':>8} {'OOS N':>6} {'Stable?':>8}")
    print(f"  {'-'*90}")

    for label, filter_fn in patterns:
        is_mask = filter_fn(in_sample)
        oos_mask = filter_fn(out_sample)

        is_sub = in_sample[is_mask]
        oos_sub = out_sample[oos_mask]

        is_avg = is_sub["ret_7d_fwd"].mean() if len(is_sub) > 0 else 0
        is_wr = (is_sub["ret_7d_fwd"] > 0).mean() * 100 if len(is_sub) > 0 else 0
        oos_avg = oos_sub["ret_7d_fwd"].mean() if len(oos_sub) > 0 else 0
        oos_wr = (oos_sub["ret_7d_fwd"] > 0).mean() * 100 if len(oos_sub) > 0 else 0

        # Stable if both positive or sign matches
        same_sign = (is_avg > 0) == (oos_avg > 0)
        stable = "YES" if same_sign and len(oos_sub) >= 5 else "NO"

        print(f"  {label:<30} {is_avg:>+9.1f}% {is_wr:>7.1f}% {len(is_sub):>5} "
              f"{oos_avg:>+9.1f}% {oos_wr:>7.1f}% {len(oos_sub):>6} {stable:>8}")


def main():
    print("Loading all data...\n")
    data, sentiment = load_all_data()
    print(f"Loaded {len(data)} pairs, {len(sentiment)} days sentiment\n")

    analysis_1_temporal_patterns(data)
    analysis_2_month_effect(data)
    analysis_3_post_crash(data)
    analysis_4_post_rally(data)
    analysis_5_atr_predictor(data)
    analysis_6_correlation(data)
    analysis_7_volume_anomaly(data)
    analysis_8_sma_distance(data)
    analysis_9_combined_signal(data, sentiment)
    analysis_10_robustness(data, sentiment)


if __name__ == "__main__":
    main()
