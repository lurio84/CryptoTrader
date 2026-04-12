import pandas as pd
import numpy as np
import pytest

from backtesting.engine import BacktestEngine, BacktestResult
from backtesting.metrics import calculate_metrics
from strategies.base import BaseStrategy, Signal
from strategies.sma_crossover import SMACrossover
from strategies.rsi_mean_reversion import RSIMeanReversion
from strategies.bollinger_breakout import BollingerBreakout


def _make_df(n: int = 500) -> pd.DataFrame:
    """Generate realistic-ish OHLCV data with trends and ranges."""
    np.random.seed(42)
    # Mix trending and ranging periods
    trend = np.cumsum(np.random.normal(5, 100, n))
    cycle = np.sin(np.linspace(0, 10 * np.pi, n)) * 500
    prices = 42000 + trend + cycle
    prices = np.maximum(prices, 1000)  # prevent negative

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
        "open": prices - np.random.uniform(10, 50, n),
        "high": prices + np.random.uniform(20, 100, n),
        "low": prices - np.random.uniform(20, 100, n),
        "close": prices,
        "volume": np.random.uniform(50, 1000, n),
    })


class _AllNaNSignalStrategy(BaseStrategy):
    """Test-only strategy that sets every signal to NaN (triggers F8 path)."""
    name = "all_nan"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = float("nan")
        return df

    def get_params(self) -> dict:
        return {}


class _NaNCloseStrategy(BaseStrategy):
    """Test-only strategy that injects NaN into one close row (triggers F10 path)."""
    name = "nan_close"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = Signal.HOLD
        if len(df) > 1:
            df.loc[df.index[1], "close"] = float("nan")
        return df

    def get_params(self) -> dict:
        return {}


class TestBacktestEngine:
    def test_run_sma_returns_result(self):
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df()
        strategy = SMACrossover(fast_period=10, slow_period=30)
        result = engine.run(df, strategy)

        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "sma_crossover"
        assert result.metrics.total_trades >= 0
        assert len(result.equity_curve) > 0

    def test_run_rsi_returns_result(self):
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df()
        strategy = RSIMeanReversion()
        result = engine.run(df, strategy)

        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "rsi_mean_reversion"

    def test_run_bollinger_returns_result(self):
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df()
        strategy = BollingerBreakout()
        result = engine.run(df, strategy)

        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "bollinger_breakout"

    def test_fees_reduce_capital(self):
        """Verify that fees actually reduce the final equity."""
        df = _make_df()
        strategy = SMACrossover(fast_period=10, slow_period=30)

        engine_with_fees = BacktestEngine(initial_capital=500.0, taker_fee=0.001, slippage=0.0005)
        engine_no_fees = BacktestEngine(initial_capital=500.0, taker_fee=0.0, slippage=0.0)

        result_fees = engine_with_fees.run(df, strategy)
        result_no_fees = engine_no_fees.run(df, strategy)

        # With fees, final equity should be less (if any trades happened)
        if result_fees.metrics.total_trades > 0:
            assert result_fees.equity_curve.iloc[-1] <= result_no_fees.equity_curve.iloc[-1]

    def test_equity_curve_starts_at_capital(self):
        engine = BacktestEngine(initial_capital=1000.0)
        df = _make_df()
        strategy = SMACrossover(fast_period=10, slow_period=30)
        result = engine.run(df, strategy)

        # First value should be initial capital (before any trade)
        assert result.equity_curve.iloc[0] == pytest.approx(1000.0, rel=0.01)

    def test_trade_log_dataframe(self):
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df()
        strategy = SMACrossover(fast_period=10, slow_period=30)
        result = engine.run(df, strategy)

        trade_log = result.get_trade_log()
        if not trade_log.empty:
            assert "side" in trade_log.columns
            assert "price" in trade_log.columns
            assert "fee" in trade_log.columns


class TestMetrics:
    def test_calculate_with_trades(self):
        trades = [
            {"side": "buy", "price": 100, "amount": 1, "cost": 100, "fee": 0.1, "pnl": None},
            {"side": "sell", "price": 110, "amount": 1, "cost": 110, "fee": 0.1, "pnl": 9.8},
            {"side": "buy", "price": 105, "amount": 1, "cost": 105, "fee": 0.1, "pnl": None},
            {"side": "sell", "price": 100, "amount": 1, "cost": 100, "fee": 0.1, "pnl": -5.2},
        ]
        equity = pd.Series([100, 100, 109.8, 109.8, 104.6])

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity,
            initial_capital=100,
            first_price=100,
            last_price=104.6,
            start_date="2024-01-01",
            end_date="2024-06-01",
        )

        assert metrics.total_trades == 2  # only closing trades have pnl
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 1
        assert metrics.win_rate == 50.0
        assert metrics.total_fees == pytest.approx(0.4)

    def test_calculate_no_trades(self):
        equity = pd.Series([500, 500, 500])
        metrics = calculate_metrics(
            trades=[], equity_curve=equity, initial_capital=500,
            first_price=42000, last_price=43000,
            start_date="2024-01-01", end_date="2024-06-01",
        )
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0

    def test_summary_string(self):
        equity = pd.Series([100, 105, 110])
        metrics = calculate_metrics(
            trades=[], equity_curve=equity, initial_capital=100,
            first_price=100, last_price=110,
            start_date="2024-01-01", end_date="2024-06-01",
        )
        summary = metrics.summary()
        assert "BACKTEST RESULTS" in summary
        assert "Total Return" in summary

    def test_zero_equity_curve_no_division_error(self):
        """F9: all-zero equity curve must not produce inf/-inf in drawdown."""
        equity = pd.Series([0.0, 0.0, 0.0])
        metrics = calculate_metrics(
            trades=[], equity_curve=equity, initial_capital=0,
            first_price=1, last_price=1,
            start_date="2024-01-01", end_date="2024-01-03",
        )
        import math
        assert not math.isinf(metrics.max_drawdown_pct)
        assert not math.isnan(metrics.max_drawdown_pct)
        assert metrics.max_drawdown_pct == 0.0


class TestEdgeCases:
    def test_f8_all_nan_signals_returns_zero_trades(self):
        """F8: strategy that emits all NaN signals must not raise; returns 0 trades."""
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df(50)
        result = engine.run(df, _AllNaNSignalStrategy())

        assert isinstance(result, BacktestResult)
        assert result.metrics.total_trades == 0
        assert result.trades == []

    def test_f10_nan_close_row_does_not_raise(self):
        """F10: a NaN close in an OHLCV row must not propagate into trade logic."""
        engine = BacktestEngine(initial_capital=500.0)
        df = _make_df(50)
        result = engine.run(df, _NaNCloseStrategy())

        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) > 0
