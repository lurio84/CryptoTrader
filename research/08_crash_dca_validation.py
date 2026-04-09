"""Comprehensive validation of Crash DCA strategy."""

import numpy as np
import pandas as pd

from backtesting.data_loader import load_backtest_data
from backtesting.crash_dca_engine import CrashDCAEngine, CrashDCASettings
from data.database import init_db

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]


def phase_1_multi_pair():
    """Test on all pairs with full data (2020-2026)."""
    print("=" * 65)
    print("  PHASE 1: CRASH DCA ON ALL PAIRS (2020-2026)")
    print("=" * 65)

    engine = CrashDCAEngine()

    print(f"\n  {'Symbol':<12} {'CrashDCA':>9} {'FixedDCA':>9} {'B&H':>9} "
          f"{'vs Fixed':>9} {'vs B&H':>9} {'Crashes':>8} {'CrashInv':>9}")
    print(f"  {'-'*80}")

    all_vs_fixed = []
    all_vs_bh = []

    for symbol in SYMBOLS:
        try:
            df = load_backtest_data(symbol, "1h", since="2020-01-01")
        except ValueError:
            continue

        result = engine.run(df, symbol)
        all_vs_fixed.append(result.vs_fixed_pct)
        all_vs_bh.append(result.vs_bh_pct)

        print(f"  {symbol:<12} {result.return_pct:>+8.1f}% {result.fixed_return_pct:>+8.1f}% "
              f"{result.bh_return_pct:>+8.1f}% {result.vs_fixed_pct:>+8.1f}% "
              f"{result.vs_bh_pct:>+8.1f}% {result.crash_buys:>8} "
              f"{result.crash_invested:>9,.0f}")

    print(f"  {'-'*80}")
    wins_fixed = sum(1 for x in all_vs_fixed if x > 0)
    wins_bh = sum(1 for x in all_vs_bh if x > 0)
    print(f"  {'AVERAGE':<12} {'':>9} {'':>9} {'':>9} "
          f"{np.mean(all_vs_fixed):>+8.1f}% {np.mean(all_vs_bh):>+8.1f}%")
    print(f"  Beats Fixed DCA: {wins_fixed}/{len(all_vs_fixed)} | "
          f"Beats B&H: {wins_bh}/{len(all_vs_bh)}")


def phase_2_walk_forward():
    """Walk-forward: train 2020-2022, validate 2023-2024, test 2025-2026."""
    print(f"\n{'='*65}")
    print("  PHASE 2: WALK-FORWARD VALIDATION")
    print("  Train: 2020-2022 | Val: 2023-2024 | Test: 2025-2026")
    print("=" * 65)

    engine = CrashDCAEngine()

    periods = [
        ("2020-01-01", "2022-12-31", "2020-22 (Train)"),
        ("2023-01-01", "2024-12-31", "2023-24 (Val)"),
        ("2025-01-01", None, "2025-26 (Test)"),
    ]

    print(f"\n  {'Symbol':<12} {'Period':<18} {'CrashDCA':>9} {'Fixed':>9} {'vs Fixed':>9} {'Crashes':>8}")
    print(f"  {'-'*70}")

    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        for since, until, label in periods:
            try:
                df = load_backtest_data(symbol, "1h", since=since, until=until)
            except ValueError:
                continue

            result = engine.run(df, symbol)
            print(f"  {symbol:<12} {label:<18} {result.return_pct:>+8.1f}% "
                  f"{result.fixed_return_pct:>+8.1f}% {result.vs_fixed_pct:>+8.1f}% "
                  f"{result.crash_buys:>8}")
        print()


def phase_3_parameter_sensitivity():
    """Test different crash thresholds and multipliers."""
    print(f"\n{'='*65}")
    print("  PHASE 3: PARAMETER SENSITIVITY (BTC/USDT 2020-2026)")
    print("=" * 65)

    df = load_backtest_data("BTC/USDT", "1h", since="2020-01-01")

    configs = [
        ("Default (10%/15%/20%, 2x/4x/6x)", CrashDCASettings()),
        ("Conservative (15%/20%/-, 2x/3x/-)", CrashDCASettings(
            crash_threshold_1=-0.15, crash_threshold_2=-0.20, crash_threshold_3=-0.30,
            crash_multiplier_1=2.0, crash_multiplier_2=3.0, crash_multiplier_3=5.0,
        )),
        ("Aggressive (5%/10%/15%, 1x/2x/4x)", CrashDCASettings(
            crash_threshold_1=-0.05, crash_threshold_2=-0.10, crash_threshold_3=-0.15,
            crash_multiplier_1=1.0, crash_multiplier_2=2.0, crash_multiplier_3=4.0,
        )),
        ("Only big crashes (15%+, 5x)", CrashDCASettings(
            crash_threshold_1=-0.15, crash_threshold_2=-0.20, crash_threshold_3=-0.30,
            crash_multiplier_1=5.0, crash_multiplier_2=8.0, crash_multiplier_3=10.0,
        )),
        ("Small extra (10%/15%, 1x/2x)", CrashDCASettings(
            crash_threshold_1=-0.10, crash_threshold_2=-0.15, crash_threshold_3=-0.25,
            crash_multiplier_1=1.0, crash_multiplier_2=2.0, crash_multiplier_3=3.0,
        )),
        ("48h cooldown -> 72h", CrashDCASettings(crash_cooldown_hours=72)),
        ("48h cooldown -> 24h", CrashDCASettings(crash_cooldown_hours=24)),
        ("No crash buys (pure DCA)", CrashDCASettings(
            crash_threshold_1=-0.99, crash_threshold_2=-0.99, crash_threshold_3=-0.99,
        )),
    ]

    print(f"\n  {'Config':<40} {'Return':>8} {'Fixed':>8} {'vsFix':>8} "
          f"{'Crashes':>8} {'ExtraInv':>9} {'AvgPrice':>9}")
    print(f"  {'-'*95}")

    for name, cfg in configs:
        engine = CrashDCAEngine(crash_settings=cfg)
        result = engine.run(df, "BTC/USDT")
        print(f"  {name:<40} {result.return_pct:>+7.1f}% {result.fixed_return_pct:>+7.1f}% "
              f"{result.vs_fixed_pct:>+7.1f}% {result.crash_buys:>8} "
              f"{result.crash_invested:>9,.0f} {result.avg_buy_price:>9,.0f}")


def phase_4_detailed_crash_log():
    """Show each crash buy event and its outcome."""
    print(f"\n{'='*65}")
    print("  PHASE 4: CRASH BUY LOG WITH OUTCOMES (BTC/USDT)")
    print("=" * 65)

    df_full = load_backtest_data("BTC/USDT", "1h", since="2020-01-01")
    engine = CrashDCAEngine()
    result = engine.run(df_full, "BTC/USDT")

    crash_log = result.buy_log[result.buy_log["type"] == "crash"].copy()
    if crash_log.empty:
        print("  No crash buys")
        return

    # Calculate outcome: price 7d and 30d after each crash buy
    daily = df_full.copy()
    daily["timestamp"] = pd.to_datetime(daily["timestamp"], utc=True)
    daily_close = daily.set_index("timestamp").resample("D")["close"].last().dropna()

    print(f"\n  {'Date':<12} {'Price':>10} {'Drop':>7} {'Mult':>5} {'Invested':>9} "
          f"{'7d After':>9} {'7d Ret':>7} {'30d After':>10} {'30d Ret':>8}")
    print(f"  {'-'*90}")

    total_7d_ret = []
    total_30d_ret = []

    for _, row in crash_log.iterrows():
        date = pd.Timestamp(row["date"])
        price = row["price"]
        crash_ret = row["crash_ret"]

        # Find prices 7d and 30d later
        future_7d = daily_close[date + pd.Timedelta(days=7):].head(1)
        future_30d = daily_close[date + pd.Timedelta(days=30):].head(1)

        ret_7d = ((future_7d.iloc[0] / price - 1) * 100) if len(future_7d) > 0 else None
        ret_30d = ((future_30d.iloc[0] / price - 1) * 100) if len(future_30d) > 0 else None

        if ret_7d is not None:
            total_7d_ret.append(ret_7d)
        if ret_30d is not None:
            total_30d_ret.append(ret_30d)

        p7 = f"{future_7d.iloc[0]:>9,.0f}" if len(future_7d) > 0 else "     N/A"
        r7 = f"{ret_7d:>+6.1f}%" if ret_7d is not None else "    N/A"
        p30 = f"{future_30d.iloc[0]:>10,.0f}" if len(future_30d) > 0 else "      N/A"
        r30 = f"{ret_30d:>+7.1f}%" if ret_30d is not None else "     N/A"

        print(f"  {str(date.date()):<12} {price:>10,.0f} {crash_ret:>+6.1%} "
              f"{row['multiplier']:>4.0f}x {row['amount_usdt']:>9,.0f} "
              f"{p7} {r7} {p30} {r30}")

    print(f"  {'-'*90}")
    if total_7d_ret:
        wr_7d = sum(1 for r in total_7d_ret if r > 0) / len(total_7d_ret) * 100
        print(f"  7d:  avg={np.mean(total_7d_ret):+.1f}% median={np.median(total_7d_ret):+.1f}% "
              f"win_rate={wr_7d:.0f}% (n={len(total_7d_ret)})")
    if total_30d_ret:
        wr_30d = sum(1 for r in total_30d_ret if r > 0) / len(total_30d_ret) * 100
        print(f"  30d: avg={np.mean(total_30d_ret):+.1f}% median={np.median(total_30d_ret):+.1f}% "
              f"win_rate={wr_30d:.0f}% (n={len(total_30d_ret)})")


def main():
    init_db()
    phase_1_multi_pair()
    phase_2_walk_forward()
    phase_3_parameter_sensitivity()
    phase_4_detailed_crash_log()


if __name__ == "__main__":
    main()
