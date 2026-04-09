"""Multi-pair validation script for optimized strategies."""

import numpy as np
from backtesting.data_loader import load_backtest_data
from backtesting.engine import BacktestEngine
from backtesting.optimizer import StrategyOptimizer
from strategies.sma_crossover import SMACrossover
from strategies.rsi_mean_reversion import RSIMeanReversion
from strategies.bollinger_breakout import BollingerBreakout

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
SINCE = "2023-01-01"
CAPITAL = 500.0

# Best params from optimization
STRATEGIES = [
    ("Bollinger Bands", BollingerBreakout, {"bb_period": 25, "bb_std": 3.0, "volume_decline_periods": 7}),
    ("SMA Crossover", SMACrossover, {"fast_period": 20, "slow_period": 75}),
    ("RSI Mean Reversion", RSIMeanReversion, {"rsi_period": 21, "oversold": 30, "overbought": 70, "volume_factor": 1.2}),
]


def main():
    engine = BacktestEngine(initial_capital=CAPITAL)
    optimizer = StrategyOptimizer(initial_capital=CAPITAL)

    # ── Per-strategy results across all pairs ──
    for strat_name, strat_cls, params in STRATEGIES:
        print("=" * 70)
        print(f"  {strat_name.upper()} | Params: {params}")
        print("=" * 70)

        returns = []
        excess_returns = []
        sharpes = []
        drawdowns = []
        win_rates = []
        profit_factors = []
        total_trades_all = 0

        print(f"\n  {'Symbol':<12} {'Return':>8} {'B&H':>8} {'Excess':>8} "
              f"{'Sharpe':>7} {'MaxDD':>7} {'WR':>6} {'PF':>6} {'Trades':>7}")
        print(f"  {'-'*75}")

        for symbol in SYMBOLS:
            df = load_backtest_data(symbol, "1h", since=SINCE)
            strategy = strat_cls(**params)
            result = engine.run(df, strategy)
            m = result.metrics

            returns.append(m.total_return_pct)
            excess_returns.append(m.excess_return_pct)
            sharpes.append(m.sharpe_ratio)
            drawdowns.append(m.max_drawdown_pct)
            win_rates.append(m.win_rate)
            pf = m.profit_factor if m.profit_factor != float("inf") else 0
            profit_factors.append(pf)
            total_trades_all += m.total_trades

            print(f"  {symbol:<12} {m.total_return_pct:>+7.1f}% {m.buy_and_hold_return_pct:>+7.1f}% "
                  f"{m.excess_return_pct:>+7.1f}% {m.sharpe_ratio:>7.2f} {m.max_drawdown_pct:>6.1f}% "
                  f"{m.win_rate:>5.1f}% {pf:>5.2f} {m.total_trades:>7}")

        print(f"  {'-'*75}")
        print(f"  {'AVERAGE':<12} {np.mean(returns):>+7.1f}% {'':>8} "
              f"{np.mean(excess_returns):>+7.1f}% {np.mean(sharpes):>7.2f} {np.mean(drawdowns):>6.1f}% "
              f"{np.mean(win_rates):>5.1f}% {np.mean(profit_factors):>5.2f} {total_trades_all:>7}")
        print(f"  {'MEDIAN':<12} {np.median(returns):>+7.1f}% {'':>8} "
              f"{np.median(excess_returns):>+7.1f}% {np.median(sharpes):>7.2f} {np.median(drawdowns):>6.1f}% "
              f"{np.median(win_rates):>5.1f}% {np.median(profit_factors):>5.2f}")

        wins = sum(1 for e in excess_returns if e > 0)
        print(f"\n  Beats Buy&Hold: {wins}/{len(SYMBOLS)} pairs")
        print(f"  Total trades across all pairs: {total_trades_all}")
        print()

    # ── Walk-forward validation for Bollinger (best strategy) ──
    print("=" * 70)
    print("  WALK-FORWARD VALIDATION: Bollinger Bands (best strategy)")
    print("  Train on 2023, Validate on 2024, Test on 2025-2026")
    print("=" * 70)

    bb_params = STRATEGIES[0][2]

    print(f"\n  {'Symbol':<12} {'Train':>8} {'Val':>8} {'Test':>8} {'Consistent?':>12}")
    print(f"  {'-'*55}")

    for symbol in SYMBOLS:
        df = load_backtest_data(symbol, "1h", since=SINCE)

        # Split into 3 periods
        total = len(df)
        t1 = int(total * 0.4)  # ~2023
        t2 = int(total * 0.7)  # ~2024

        df_train = df.iloc[:t1].reset_index(drop=True)
        df_val = df.iloc[t1:t2].reset_index(drop=True)
        df_test = df.iloc[t2:].reset_index(drop=True)

        strategy = BollingerBreakout(**bb_params)

        r_train = engine.run(df_train, strategy).metrics.excess_return_pct
        r_val = engine.run(df_val, strategy).metrics.excess_return_pct
        r_test = engine.run(df_test, strategy).metrics.excess_return_pct

        # Consistent if at least 2/3 periods show positive excess return
        positive = sum(1 for r in [r_train, r_val, r_test] if r > 0)
        consistent = "YES" if positive >= 2 else "NO"

        print(f"  {symbol:<12} {r_train:>+7.1f}% {r_val:>+7.1f}% {r_test:>+7.1f}% {consistent:>12}")


if __name__ == "__main__":
    main()
