"""Parameter optimization script for all strategies."""

from backtesting.data_loader import load_backtest_data
from backtesting.optimizer import StrategyOptimizer, print_optimization_results
from strategies.sma_crossover import SMACrossover
from strategies.rsi_mean_reversion import RSIMeanReversion
from strategies.bollinger_breakout import BollingerBreakout


def main():
    print("Loading BTC/USDT data...")
    df = load_backtest_data("BTC/USDT", "1h", since="2024-01-01")
    print(f"  {len(df)} candles loaded\n")

    optimizer = StrategyOptimizer(initial_capital=500.0, train_ratio=0.7)

    # ── SMA Crossover ──────────────────────────────────────────
    print("=" * 60)
    print("  OPTIMIZING: SMA Crossover")
    print("=" * 60)
    sma_results = optimizer.optimize(
        df,
        SMACrossover,
        param_grid={
            "fast_period": [5, 10, 15, 20, 30],
            "slow_period": [30, 50, 75, 100, 150, 200],
        },
        rank_by="sharpe_ratio",
        min_trades=5,
    )
    print_optimization_results(sma_results, top_n=10)

    # ── RSI Mean Reversion ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("  OPTIMIZING: RSI Mean Reversion")
    print("=" * 60)
    rsi_results = optimizer.optimize(
        df,
        RSIMeanReversion,
        param_grid={
            "rsi_period": [7, 10, 14, 21],
            "oversold": [20, 25, 30, 35],
            "overbought": [65, 70, 75, 80],
            "volume_factor": [0.5, 0.8, 1.0, 1.2],
        },
        rank_by="sharpe_ratio",
        min_trades=5,
    )
    print_optimization_results(rsi_results, top_n=10)

    # ── Bollinger Bands ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  OPTIMIZING: Bollinger Bands")
    print("=" * 60)
    bb_results = optimizer.optimize(
        df,
        BollingerBreakout,
        param_grid={
            "bb_period": [10, 15, 20, 25, 30],
            "bb_std": [1.5, 2.0, 2.5, 3.0],
            "volume_decline_periods": [3, 5, 7, 10],
        },
        rank_by="sharpe_ratio",
        min_trades=5,
    )
    print_optimization_results(bb_results, top_n=10)

    # ── Best of each: full backtest ────────────────────────────
    print("\n" + "=" * 60)
    print("  BEST PARAMS - FULL BACKTEST (all data)")
    print("=" * 60)

    for name, results, cls in [
        ("SMA Crossover", sma_results, SMACrossover),
        ("RSI Mean Reversion", rsi_results, RSIMeanReversion),
        ("Bollinger Bands", bb_results, BollingerBreakout),
    ]:
        if not results:
            print(f"\n  {name}: No valid results")
            continue
        best = results[0]
        print(f"\n  {name} - Best params: {best.params}")
        result = optimizer.run_full_backtest(df, cls, best.params)
        result.print_summary()


if __name__ == "__main__":
    main()
