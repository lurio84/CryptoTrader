"""DCA multiplier optimization + multi-pair multi-period validation."""

import itertools
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from backtesting.dca_engine import DCABacktestEngine
from config.settings import DCASettings
from data.sentiment import SentimentCollector
from data.database import init_db

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
SINCE = "2023-01-01"


def optimize_multipliers(df_candles: pd.DataFrame, df_sentiment: pd.DataFrame, symbol: str):
    """Grid search over DCA multiplier combinations."""

    param_grid = {
        "multiplier_extreme_fear": [1.5, 2.0, 2.5, 3.0],
        "multiplier_fear": [1.0, 1.25, 1.5, 2.0],
        "multiplier_neutral": [0.5, 0.75, 1.0],
        "multiplier_greed": [0.0, 0.25, 0.5],
        "multiplier_extreme_greed": [0.0],
    }

    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))

    # Walk-forward: train 60%, validate 40%
    n_days_candle = len(df_candles) // 24
    split = int(len(df_candles) * 0.6)
    train_candles = df_candles.iloc[:split].reset_index(drop=True)
    val_candles = df_candles.iloc[split:].reset_index(drop=True)

    print(f"  Testing {len(combos)} combinations (walk-forward 60/40)...")

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        dca_settings = DCASettings(**params)
        engine = DCABacktestEngine(dca_settings=dca_settings)

        # Train
        try:
            train_result = engine.run(train_candles, df_sentiment, symbol)
        except (ValueError, ZeroDivisionError):
            continue

        if train_result.smart_total_buys < 5:
            continue

        # Validate on out-of-sample
        try:
            val_result = engine.run(val_candles, df_sentiment, symbol)
        except (ValueError, ZeroDivisionError):
            continue

        results.append({
            **params,
            "train_return": train_result.smart_return_pct,
            "train_vs_fixed": train_result.smart_vs_fixed_pct,
            "val_return": val_result.smart_return_pct,
            "val_vs_fixed": val_result.smart_vs_fixed_pct,
            "val_buys": val_result.smart_total_buys,
            "val_invested": val_result.smart_total_invested,
            "val_avg_price": val_result.smart_avg_buy_price,
        })

    df_results = pd.DataFrame(results)
    if df_results.empty:
        return df_results

    # Sort by validation excess over fixed DCA
    df_results = df_results.sort_values("val_vs_fixed", ascending=False)
    return df_results


def main():
    init_db()
    sent_collector = SentimentCollector()

    # Fetch max sentiment data
    print("Loading sentiment data...")
    # Try to get as much as possible
    sent_collector.collect_all(days=1500)
    df_sentiment = sent_collector.load_sentiment()
    print(f"  {len(df_sentiment)} days of sentiment data\n")

    # ── PHASE 1: Optimize on BTC ──
    print("=" * 65)
    print("  PHASE 1: OPTIMIZE MULTIPLIERS ON BTC/USDT")
    print("=" * 65)

    df_btc = load_backtest_data("BTC/USDT", "1h", since=SINCE)
    print(f"  {len(df_btc)} candles loaded")

    opt_results = optimize_multipliers(df_btc, df_sentiment, "BTC/USDT")

    if opt_results.empty:
        print("  No valid results!")
        return

    print(f"\n  TOP 10 PARAMETER COMBINATIONS (ranked by val_vs_fixed):")
    print(f"  {'ExFear':>7} {'Fear':>6} {'Neut':>6} {'Greed':>6} "
          f"{'Train%':>8} {'TvsFix':>8} {'Val%':>8} {'VvsFix':>8} {'Buys':>5}")
    print(f"  {'-'*72}")

    for _, row in opt_results.head(10).iterrows():
        print(f"  {row['multiplier_extreme_fear']:>7.1f} {row['multiplier_fear']:>6.2f} "
              f"{row['multiplier_neutral']:>6.2f} {row['multiplier_greed']:>6.2f} "
              f"{row['train_return']:>+7.1f}% {row['train_vs_fixed']:>+7.1f}% "
              f"{row['val_return']:>+7.1f}% {row['val_vs_fixed']:>+7.1f}% "
              f"{row['val_buys']:>5.0f}")

    # Best params
    best = opt_results.iloc[0]
    best_params = {
        "multiplier_extreme_fear": best["multiplier_extreme_fear"],
        "multiplier_fear": best["multiplier_fear"],
        "multiplier_neutral": best["multiplier_neutral"],
        "multiplier_greed": best["multiplier_greed"],
        "multiplier_extreme_greed": best["multiplier_extreme_greed"],
    }

    print(f"\n  BEST PARAMS: {best_params}")

    # ── PHASE 2: Validate on ALL pairs ──
    print(f"\n{'='*65}")
    print(f"  PHASE 2: VALIDATE BEST PARAMS ON ALL PAIRS")
    print(f"{'='*65}")

    best_dca = DCASettings(**best_params)
    default_dca = DCASettings()  # default multipliers

    print(f"\n  {'Symbol':<12} {'Smart%':>8} {'Fixed%':>8} {'SvsFix':>8} "
          f"{'Default%':>9} {'DvsFix':>8} {'Invested':>10} {'Buys':>5}")
    print(f"  {'-'*75}")

    smart_excess_list = []
    default_excess_list = []

    for symbol in SYMBOLS:
        try:
            df = load_backtest_data(symbol, "1h", since=SINCE)
        except ValueError:
            continue

        # Optimized
        engine_opt = DCABacktestEngine(dca_settings=best_dca)
        try:
            result_opt = engine_opt.run(df, df_sentiment, symbol)
        except (ValueError, ZeroDivisionError):
            continue

        # Default
        engine_def = DCABacktestEngine(dca_settings=default_dca)
        try:
            result_def = engine_def.run(df, df_sentiment, symbol)
        except (ValueError, ZeroDivisionError):
            continue

        smart_excess_list.append(result_opt.smart_vs_fixed_pct)
        default_excess_list.append(result_def.smart_vs_fixed_pct)

        print(f"  {symbol:<12} {result_opt.smart_return_pct:>+7.1f}% "
              f"{result_opt.fixed_return_pct:>+7.1f}% {result_opt.smart_vs_fixed_pct:>+7.1f}% "
              f"{result_def.smart_return_pct:>+8.1f}% {result_def.smart_vs_fixed_pct:>+7.1f}% "
              f"{result_opt.smart_total_invested:>10.0f} {result_opt.smart_total_buys:>5}")

    print(f"  {'-'*75}")
    print(f"  {'AVERAGE':<12} {'':>8} {'':>8} {np.mean(smart_excess_list):>+7.1f}% "
          f"{'':>9} {np.mean(default_excess_list):>+7.1f}%")
    print(f"  {'MEDIAN':<12} {'':>8} {'':>8} {np.median(smart_excess_list):>+7.1f}% "
          f"{'':>9} {np.median(default_excess_list):>+7.1f}%")

    wins_opt = sum(1 for x in smart_excess_list if x > 0)
    wins_def = sum(1 for x in default_excess_list if x > 0)
    print(f"\n  Optimized beats Fixed DCA: {wins_opt}/{len(smart_excess_list)} pairs")
    print(f"  Default beats Fixed DCA:   {wins_def}/{len(default_excess_list)} pairs")

    # ── PHASE 3: Period-by-period analysis ──
    print(f"\n{'='*65}")
    print(f"  PHASE 3: YEARLY BREAKDOWN (BTC/USDT, optimized params)")
    print(f"{'='*65}")

    periods = [
        ("2023-01-01", "2023-12-31", "2023"),
        ("2024-01-01", "2024-12-31", "2024"),
        ("2025-01-01", "2026-04-08", "2025-26"),
    ]

    engine_opt = DCABacktestEngine(dca_settings=best_dca)

    print(f"\n  {'Period':<10} {'Smart%':>8} {'Fixed%':>8} {'SvsFix':>8} {'B&H%':>8} {'Buys':>5}")
    print(f"  {'-'*50}")

    for start, end, label in periods:
        try:
            df = load_backtest_data("BTC/USDT", "1h", since=start, until=end)
            result = engine_opt.run(df, df_sentiment, "BTC/USDT")
            print(f"  {label:<10} {result.smart_return_pct:>+7.1f}% {result.fixed_return_pct:>+7.1f}% "
                  f"{result.smart_vs_fixed_pct:>+7.1f}% {result.bh_return_pct:>+7.1f}% "
                  f"{result.smart_total_buys:>5}")
        except (ValueError, ZeroDivisionError) as e:
            print(f"  {label:<10} Error: {e}")


if __name__ == "__main__":
    main()
