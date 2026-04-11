import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class BacktestMetrics:
    total_return_pct: float
    buy_and_hold_return_pct: float
    excess_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    total_fees: float
    start_date: str
    end_date: str

    def summary(self) -> str:
        return (
            f"{'='*50}\n"
            f"  BACKTEST RESULTS ({self.start_date} -> {self.end_date})\n"
            f"{'='*50}\n"
            f"  Total Return:      {self.total_return_pct:+.2f}%\n"
            f"  Buy & Hold:        {self.buy_and_hold_return_pct:+.2f}%\n"
            f"  Excess Return:     {self.excess_return_pct:+.2f}%\n"
            f"{'-'*50}\n"
            f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}\n"
            f"  Max Drawdown:      {self.max_drawdown_pct:.2f}%\n"
            f"{'-'*50}\n"
            f"  Total Trades:      {self.total_trades}\n"
            f"  Win Rate:          {self.win_rate:.1f}%\n"
            f"  Profit Factor:     {self.profit_factor:.2f}\n"
            f"  Avg Win:           {self.avg_win_pct:+.2f}%\n"
            f"  Avg Loss:          {self.avg_loss_pct:+.2f}%\n"
            f"{'-'*50}\n"
            f"  Total Fees Paid:   {self.total_fees:.2f} USDT\n"
            f"{'='*50}"
        )


def calculate_metrics(
    trades: list[dict],
    equity_curve: pd.Series,
    initial_capital: float,
    first_price: float,
    last_price: float,
    start_date: str,
    end_date: str,
    periods_per_year: float = 8760,
) -> BacktestMetrics:
    """Calculate backtest performance metrics from trade list and equity curve."""

    total_return_pct = ((equity_curve.iloc[-1] - initial_capital) / initial_capital) * 100
    buy_and_hold_return_pct = ((last_price - first_price) / first_price) * 100
    excess_return_pct = total_return_pct - buy_and_hold_return_pct

    # Sharpe ratio (annualized). periods_per_year: 8760=hourly, 365=daily, 52=weekly
    returns = equity_curve.pct_change().dropna()
    if len(returns) > 1 and returns.std() > 0:
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(periods_per_year)
    else:
        sharpe_ratio = 0.0

    # Max drawdown
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    max_drawdown_pct = abs(drawdown.min()) * 100

    # Trade statistics
    pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
    total_trades = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    winning_trades = len(wins)
    losing_trades = len(losses)

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win_pct = (np.mean(wins) / initial_capital * 100) if wins else 0.0
    avg_loss_pct = (np.mean(losses) / initial_capital * 100) if losses else 0.0

    total_fees = sum(t.get("fee", 0) for t in trades)

    return BacktestMetrics(
        total_return_pct=round(total_return_pct, 2),
        buy_and_hold_return_pct=round(buy_and_hold_return_pct, 2),
        excess_return_pct=round(excess_return_pct, 2),
        sharpe_ratio=round(sharpe_ratio, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        win_rate=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_win_pct=round(avg_win_pct, 2),
        avg_loss_pct=round(avg_loss_pct, 2),
        total_fees=round(total_fees, 2),
        start_date=start_date,
        end_date=end_date,
    )
