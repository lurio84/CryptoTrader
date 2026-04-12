from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, Signal
from backtesting.metrics import BacktestMetrics, calculate_metrics
from config.settings import settings


class BacktestEngine:
    """Simulates strategy execution on historical data with realistic fees and slippage."""

    def __init__(
        self,
        initial_capital: float = 500.0,
        maker_fee: float | None = None,
        taker_fee: float | None = None,
        slippage: float | None = None,
    ):
        self.initial_capital = initial_capital
        self.maker_fee = maker_fee if maker_fee is not None else settings.maker_fee_pct
        self.taker_fee = taker_fee if taker_fee is not None else settings.taker_fee_pct
        self.slippage = slippage if slippage is not None else settings.slippage_pct

    def run(self, df: pd.DataFrame, strategy: BaseStrategy) -> BacktestResult:
        """Run backtest on historical data with a given strategy.

        Args:
            df: OHLCV DataFrame (must have timestamp, open, high, low, close, volume)
            strategy: Strategy instance that generates signals

        Returns:
            BacktestResult with metrics, trades, and equity curve
        """
        df = strategy.generate_signals(df)
        df = df.dropna(subset=["signal"]).reset_index(drop=True)

        # F8: no rows with a valid signal → return clean zero result instead of crashing
        if df.empty:
            zero_metrics = BacktestMetrics(
                total_return_pct=0.0, buy_and_hold_return_pct=0.0, excess_return_pct=0.0,
                sharpe_ratio=0.0, max_drawdown_pct=0.0, win_rate=0.0, profit_factor=0.0,
                total_trades=0, winning_trades=0, losing_trades=0,
                avg_win_pct=0.0, avg_loss_pct=0.0, total_fees=0.0,
                start_date="", end_date="",
            )
            return BacktestResult(
                metrics=zero_metrics, trades=[],
                equity_curve=pd.Series([], dtype=float),
                signals_df=df, strategy_name=strategy.name,
                strategy_params=strategy.get_params(),
            )

        cash = self.initial_capital
        position = 0.0  # amount of asset held
        entry_price = 0.0
        trades: list[dict] = []
        equity_values: list[float] = []

        for i, row in df.iterrows():
            # F10: OHLCV columns may still have NaN even after signal dropna; skip trade logic
            if pd.isna(row["close"]):
                equity_values.append(cash)
                continue
            price = row["close"]
            signal = row["signal"]
            timestamp = row["timestamp"]

            if signal == Signal.BUY and position == 0:
                # Buy: apply slippage (pay slightly more)
                exec_price = price * (1 + self.slippage)
                fee = cash * self.taker_fee
                available = cash - fee
                position = available / exec_price
                entry_price = exec_price
                cash = 0.0

                trades.append({
                    "side": "buy",
                    "price": exec_price,
                    "amount": position,
                    "cost": available,
                    "fee": fee,
                    "timestamp": timestamp,
                    "pnl": None,
                })

            elif signal == Signal.SELL and position > 0:
                # Sell: apply slippage (receive slightly less)
                exec_price = price * (1 - self.slippage)
                gross = position * exec_price
                fee = gross * self.taker_fee
                cash = gross - fee
                pnl = cash - (entry_price * position)

                trades.append({
                    "side": "sell",
                    "price": exec_price,
                    "amount": position,
                    "cost": gross,
                    "fee": fee,
                    "timestamp": timestamp,
                    "pnl": pnl,
                })

                position = 0.0
                entry_price = 0.0

            # Track equity (cash + position value at current price)
            equity = cash + (position * price)
            equity_values.append(equity)

        # If still holding at end, calculate unrealized value
        if position > 0:
            final_price = df["close"].iloc[-1] * (1 - self.slippage)
            fee = position * final_price * self.taker_fee
            cash = position * final_price - fee
            equity_values[-1] = cash

        equity_curve = pd.Series(equity_values, index=df.index)

        # Detect data frequency to annualize Sharpe correctly
        if len(df) >= 2:
            median_gap_h = df["timestamp"].diff().dropna().median().total_seconds() / 3600
            if median_gap_h <= 2:
                periods_per_year = 8760    # hourly
            elif median_gap_h <= 26:
                periods_per_year = 365     # daily
            else:
                periods_per_year = 52      # weekly
        else:
            periods_per_year = 8760

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=self.initial_capital,
            first_price=df["close"].iloc[0],
            last_price=df["close"].iloc[-1],
            start_date=str(df["timestamp"].iloc[0].date()),
            end_date=str(df["timestamp"].iloc[-1].date()),
            periods_per_year=periods_per_year,
        )

        return BacktestResult(
            metrics=metrics,
            trades=trades,
            equity_curve=equity_curve,
            signals_df=df,
            strategy_name=strategy.name,
            strategy_params=strategy.get_params(),
        )


class BacktestResult:
    """Container for backtest output."""

    def __init__(
        self,
        metrics: BacktestMetrics,
        trades: list[dict],
        equity_curve: pd.Series,
        signals_df: pd.DataFrame,
        strategy_name: str,
        strategy_params: dict,
    ):
        self.metrics = metrics
        self.trades = trades
        self.equity_curve = equity_curve
        self.signals_df = signals_df
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params

    def print_summary(self) -> None:
        print(f"\n  Strategy: {self.strategy_name}")
        print(f"  Params:   {self.strategy_params}")
        print(self.metrics.summary())

    def get_trade_log(self) -> pd.DataFrame:
        """Return trades as a DataFrame for analysis."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame(self.trades)
