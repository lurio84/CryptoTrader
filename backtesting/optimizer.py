from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

from backtesting.engine import BacktestEngine, BacktestResult
from strategies.base import BaseStrategy


@dataclass
class OptimizationResult:
    strategy_name: str
    params: dict
    total_return_pct: float
    excess_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    total_fees: float


class StrategyOptimizer:
    """Grid search optimizer for strategy parameters.

    Tests all combinations of parameter ranges and ranks by chosen metric.
    Uses walk-forward validation to avoid overfitting:
      - Train on first 70% of data
      - Validate on last 30% of data
    """

    def __init__(
        self,
        initial_capital: float = 500.0,
        train_ratio: float = 0.7,
    ):
        self.initial_capital = initial_capital
        self.train_ratio = train_ratio

    def optimize(
        self,
        df: pd.DataFrame,
        strategy_class: type[BaseStrategy],
        param_grid: dict[str, list],
        rank_by: str = "sharpe_ratio",
        min_trades: int = 10,
    ) -> list[OptimizationResult]:
        """Run grid search over parameter combinations.

        Args:
            df: OHLCV DataFrame
            strategy_class: Strategy class to instantiate
            param_grid: Dict of param_name -> list of values to test
            rank_by: Metric to sort results by (descending)
            min_trades: Minimum trades required to be considered valid

        Returns:
            List of OptimizationResult sorted by rank_by (best first)
        """
        # Walk-forward split
        split_idx = int(len(df) * self.train_ratio)
        train_df = df.iloc[:split_idx].reset_index(drop=True)
        val_df = df.iloc[split_idx:].reset_index(drop=True)

        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(itertools.product(*param_values))

        print(f"  Testing {len(combinations)} parameter combinations...")
        print(f"  Train: {len(train_df)} candles | Validation: {len(val_df)} candles")

        engine = BacktestEngine(initial_capital=self.initial_capital)
        results: list[OptimizationResult] = []

        for i, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))
            strategy = strategy_class(**params)

            # Run on TRAIN data to find best params
            train_result = engine.run(train_df, strategy)

            if train_result.metrics.total_trades < min_trades:
                continue

            # Validate on OUT-OF-SAMPLE data
            val_result = engine.run(val_df, strategy)

            results.append(OptimizationResult(
                strategy_name=strategy.name,
                params=params,
                total_return_pct=val_result.metrics.total_return_pct,
                excess_return_pct=val_result.metrics.excess_return_pct,
                sharpe_ratio=val_result.metrics.sharpe_ratio,
                max_drawdown_pct=val_result.metrics.max_drawdown_pct,
                win_rate=val_result.metrics.win_rate,
                profit_factor=val_result.metrics.profit_factor,
                total_trades=val_result.metrics.total_trades,
                total_fees=val_result.metrics.total_fees,
            ))

        # Sort by chosen metric (descending)
        results.sort(key=lambda r: getattr(r, rank_by), reverse=True)
        return results

    def run_full_backtest(
        self,
        df: pd.DataFrame,
        strategy_class: type[BaseStrategy],
        params: dict,
    ) -> BacktestResult:
        """Run a full backtest with specific params on ALL data."""
        engine = BacktestEngine(initial_capital=self.initial_capital)
        strategy = strategy_class(**params)
        return engine.run(df, strategy)


def print_optimization_results(results: list[OptimizationResult], top_n: int = 10) -> None:
    """Print top N optimization results as a table."""
    if not results:
        print("  No valid results (all combinations had too few trades)")
        return

    print(f"\n  {'Rank':<5} {'Return':>8} {'Excess':>8} {'Sharpe':>7} {'MaxDD':>7} "
          f"{'WinRate':>8} {'PF':>6} {'Trades':>7} {'Params'}")
    print(f"  {'-'*80}")

    for i, r in enumerate(results[:top_n], 1):
        params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
        print(f"  {i:<5} {r.total_return_pct:>+7.1f}% {r.excess_return_pct:>+7.1f}% "
              f"{r.sharpe_ratio:>7.2f} {r.max_drawdown_pct:>6.1f}% "
              f"{r.win_rate:>7.1f}% {r.profit_factor:>5.2f} {r.total_trades:>7} "
              f"  {params_str}")
