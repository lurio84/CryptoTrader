"""Risk-adjusted comparison: Crash DCA crypto vs S&P 500 DCA."""

import numpy as np
from backtesting.data_loader import load_backtest_data
from backtesting.crash_dca_engine import CrashDCAEngine, CrashDCASettings
from data.database import init_db

BEST_CONFIG = CrashDCASettings(
    crash_threshold_1=-0.15, crash_threshold_2=-0.20, crash_threshold_3=-0.30,
    crash_multiplier_1=5.0, crash_multiplier_2=8.0, crash_multiplier_3=10.0,
)

# S&P 500 annual returns (real data, total return with dividends)
SP500_ANNUAL = {
    "2020": 18.4,
    "2021": 28.7,
    "2022": -18.1,
    "2023": 26.3,
    "2024": 25.0,
    "2025-26": -5.0,  # estimate YTD (partial year, tariffs impact)
}

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

    print("=" * 80)
    print("  RISK-ADJUSTED COMPARISON: Crash DCA (BTC) vs S&P 500 DCA vs Fixed DCA (BTC)")
    print("=" * 80)

    crash_rets = []
    fixed_rets = []
    sp500_rets = []
    crash_drawdowns = []

    print(f"\n  {'Year':<10} {'CrashDCA':>9} {'FixedDCA':>9} {'S&P500':>8} "
          f"{'Crash-SP':>9} {'Fixed-SP':>9}")
    print(f"  {'-'*60}")

    for since, until, label in YEARS:
        df = load_backtest_data("BTC/USDT", "1h", since=since, until=until)
        result = engine.run(df, "BTC/USDT")

        sp = SP500_ANNUAL[label]
        crash_rets.append(result.return_pct)
        fixed_rets.append(result.fixed_return_pct)
        sp500_rets.append(sp)

        diff_crash = result.return_pct - sp
        diff_fixed = result.fixed_return_pct - sp

        print(f"  {label:<10} {result.return_pct:>+8.1f}% {result.fixed_return_pct:>+8.1f}% "
              f"{sp:>+7.1f}% {diff_crash:>+8.1f}% {diff_fixed:>+8.1f}%")

    print(f"  {'-'*60}")
    print(f"  {'AVERAGE':<10} {np.mean(crash_rets):>+8.1f}% {np.mean(fixed_rets):>+8.1f}% "
          f"{np.mean(sp500_rets):>+7.1f}% {np.mean(crash_rets)-np.mean(sp500_rets):>+8.1f}% "
          f"{np.mean(fixed_rets)-np.mean(sp500_rets):>+8.1f}%")
    print(f"  {'MEDIAN':<10} {np.median(crash_rets):>+8.1f}% {np.median(fixed_rets):>+8.1f}% "
          f"{np.median(sp500_rets):>+7.1f}%")

    # ── Risk metrics ──
    print(f"\n{'='*80}")
    print(f"  RISK METRICS")
    print(f"{'='*80}")

    crash_std = np.std(crash_rets)
    fixed_std = np.std(fixed_rets)
    sp_std = np.std(sp500_rets)

    crash_sharpe = np.mean(crash_rets) / crash_std if crash_std > 0 else 0
    fixed_sharpe = np.mean(fixed_rets) / fixed_std if fixed_std > 0 else 0
    sp_sharpe = np.mean(sp500_rets) / sp_std if sp_std > 0 else 0

    print(f"\n  {'Metric':<30} {'CrashDCA':>12} {'FixedDCA':>12} {'S&P500':>12}")
    print(f"  {'-'*68}")
    print(f"  {'Avg Annual Return':<30} {np.mean(crash_rets):>+11.1f}% {np.mean(fixed_rets):>+11.1f}% {np.mean(sp500_rets):>+11.1f}%")
    print(f"  {'Median Annual Return':<30} {np.median(crash_rets):>+11.1f}% {np.median(fixed_rets):>+11.1f}% {np.median(sp500_rets):>+11.1f}%")
    print(f"  {'Std Dev (volatility)':<30} {crash_std:>11.1f}% {fixed_std:>11.1f}% {sp_std:>11.1f}%")
    print(f"  {'Worst Year':<30} {min(crash_rets):>+11.1f}% {min(fixed_rets):>+11.1f}% {min(sp500_rets):>+11.1f}%")
    print(f"  {'Best Year':<30} {max(crash_rets):>+11.1f}% {max(fixed_rets):>+11.1f}% {max(sp500_rets):>+11.1f}%")
    print(f"  {'Sharpe Ratio (simplified)':<30} {crash_sharpe:>11.2f} {fixed_sharpe:>11.2f} {sp_sharpe:>11.2f}")
    print(f"  {'Positive Years':<30} {sum(1 for r in crash_rets if r>0)}/{len(crash_rets):>9} "
          f"{sum(1 for r in fixed_rets if r>0)}/{len(fixed_rets):>9} "
          f"{sum(1 for r in sp500_rets if r>0)}/{len(sp500_rets):>9}")

    # ── Return per unit of risk ──
    crash_return_per_risk = np.mean(crash_rets) / crash_std if crash_std > 0 else 0
    sp_return_per_risk = np.mean(sp500_rets) / sp_std if sp_std > 0 else 0

    print(f"\n{'='*80}")
    print(f"  THE BOTTOM LINE")
    print(f"{'='*80}")
    print(f"""
  Crash DCA (BTC):
    Average annual return:    {np.mean(crash_rets):+.1f}%
    Volatility (std dev):     {crash_std:.1f}%
    Worst year:               {min(crash_rets):+.1f}%
    Return per unit of risk:  {crash_return_per_risk:.2f}

  S&P 500 DCA:
    Average annual return:    {np.mean(sp500_rets):+.1f}%
    Volatility (std dev):     {sp_std:.1f}%
    Worst year:               {min(sp500_rets):+.1f}%
    Return per unit of risk:  {sp_return_per_risk:.2f}

  For every 1% of risk you take:
    Crash DCA earns:          {crash_return_per_risk:.2f}% return
    S&P 500 earns:            {sp_return_per_risk:.2f}% return

  BTC max drawdown (peak to trough): ~-77% (Nov 2021 -> Nov 2022)
  S&P 500 max drawdown (same period): ~-25%

  To lose 50%+ of value:
    BTC: has happened 3 times in 6 years
    S&P 500: has happened 2 times in 25 years (2000, 2008)
""")


if __name__ == "__main__":
    main()
