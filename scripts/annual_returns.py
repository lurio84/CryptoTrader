"""Calculate annual returns for Crash DCA vs Fixed DCA vs Buy & Hold."""

import numpy as np
from backtesting.data_loader import load_backtest_data
from backtesting.crash_dca_engine import CrashDCAEngine, CrashDCASettings
from data.database import init_db

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# Best config from optimization
BEST_CONFIG = CrashDCASettings(
    crash_threshold_1=-0.15, crash_threshold_2=-0.20, crash_threshold_3=-0.30,
    crash_multiplier_1=5.0, crash_multiplier_2=8.0, crash_multiplier_3=10.0,
)

YEARS = [
    ("2020-01-01", "2020-12-31", "2020"),
    ("2021-01-01", "2021-12-31", "2021"),
    ("2022-01-01", "2022-12-31", "2022"),
    ("2023-01-01", "2023-12-31", "2023"),
    ("2024-01-01", "2024-12-31", "2024"),
    ("2025-01-01", "2026-04-08", "2025-26"),
]


def main():
    init_db()
    engine = CrashDCAEngine(crash_settings=BEST_CONFIG)

    for symbol in SYMBOLS:
        print(f"\n{'='*75}")
        print(f"  ANNUAL RETURNS: {symbol} (Best config: -15%+ crashes, 5x multiplier)")
        print(f"{'='*75}")

        print(f"\n  {'Year':<10} {'CrashDCA':>9} {'FixedDCA':>9} {'B&H':>9} "
              f"{'vs Fixed':>9} {'Crashes':>8} {'Invested':>10} {'Value':>10}")
        print(f"  {'-'*80}")

        crash_returns = []
        fixed_returns = []
        bh_returns = []

        for since, until, label in YEARS:
            try:
                df = load_backtest_data(symbol, "1h", since=since, until=until)
            except ValueError:
                continue

            result = engine.run(df, symbol)
            crash_returns.append(result.return_pct)
            fixed_returns.append(result.fixed_return_pct)
            bh_returns.append(result.bh_return_pct)

            print(f"  {label:<10} {result.return_pct:>+8.1f}% {result.fixed_return_pct:>+8.1f}% "
                  f"{result.bh_return_pct:>+8.1f}% {result.vs_fixed_pct:>+8.1f}% "
                  f"{result.crash_buys:>8} {result.total_invested:>10,.0f} {result.final_value:>10,.0f}")

        print(f"  {'-'*80}")
        print(f"  {'AVERAGE':<10} {np.mean(crash_returns):>+8.1f}% {np.mean(fixed_returns):>+8.1f}% "
              f"{np.mean(bh_returns):>+8.1f}% {np.mean(crash_returns)-np.mean(fixed_returns):>+8.1f}%")
        print(f"  {'MEDIAN':<10} {np.median(crash_returns):>+8.1f}% {np.median(fixed_returns):>+8.1f}% "
              f"{np.median(bh_returns):>+8.1f}%")

        # Worst year
        worst_idx = np.argmin(crash_returns)
        print(f"  {'WORST':<10} {min(crash_returns):>+8.1f}% ({YEARS[worst_idx][2]})")
        print(f"  {'BEST':<10} {max(crash_returns):>+8.1f}% ({YEARS[np.argmax(crash_returns)][2]})")

        # Win rate vs fixed
        wins = sum(1 for c, f in zip(crash_returns, fixed_returns) if c > f)
        print(f"\n  Beats Fixed DCA: {wins}/{len(crash_returns)} years")

    # ── Summary with 50€/week scenario ──
    print(f"\n\n{'='*75}")
    print(f"  SCENARIO: 50 EUR/week for each year (what you'd actually earn)")
    print(f"{'='*75}")

    for symbol in SYMBOLS:
        print(f"\n  {symbol}:")
        print(f"  {'Year':<10} {'Invested':>10} {'CrashDCA':>12} {'Profit':>10} {'FixedDCA':>12} {'Profit':>10}")
        print(f"  {'-'*70}")

        for since, until, label in YEARS:
            try:
                df = load_backtest_data(symbol, "1h", since=since, until=until)
            except ValueError:
                continue

            result = engine.run(df, symbol)

            crash_profit = result.final_value - result.total_invested
            fixed_profit = result.fixed_final_value - result.fixed_invested

            print(f"  {label:<10} {result.total_invested:>10,.0f} {result.final_value:>12,.0f} "
                  f"{crash_profit:>+9,.0f} {result.fixed_final_value:>12,.0f} {fixed_profit:>+9,.0f}")


if __name__ == "__main__":
    main()
