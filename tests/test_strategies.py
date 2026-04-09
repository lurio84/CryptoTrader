import pandas as pd
import numpy as np

from strategies.base import Signal
from strategies.sma_crossover import SMACrossover
from strategies.rsi_mean_reversion import RSIMeanReversion
from strategies.bollinger_breakout import BollingerBreakout


def _make_trending_up_df(n: int = 200) -> pd.DataFrame:
    """Generate uptrending OHLCV data."""
    prices = 40000 + np.cumsum(np.random.normal(10, 50, n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
        "open": prices - 20,
        "high": prices + 50,
        "low": prices - 50,
        "close": prices,
        "volume": np.random.uniform(100, 500, n),
    })


def _make_ranging_df(n: int = 200) -> pd.DataFrame:
    """Generate sideways/ranging OHLCV data."""
    base = 42000
    prices = base + np.sin(np.linspace(0, 8 * np.pi, n)) * 1000
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
        "open": prices - 20,
        "high": prices + 50,
        "low": prices - 50,
        "close": prices,
        "volume": np.random.uniform(100, 500, n),
    })


class TestSMACrossover:
    def test_generates_signals(self):
        strategy = SMACrossover(fast_period=10, slow_period=30)
        df = _make_trending_up_df(200)
        result = strategy.generate_signals(df)

        assert "signal" in result.columns
        assert "sma_fast" in result.columns
        assert "sma_slow" in result.columns

        signals = result["signal"].value_counts()
        assert Signal.HOLD in signals.index

    def test_has_buy_and_sell_signals(self):
        strategy = SMACrossover(fast_period=5, slow_period=20)
        df = _make_ranging_df(300)
        result = strategy.generate_signals(df)

        unique_signals = set(result["signal"].dropna())
        assert Signal.BUY in unique_signals or Signal.SELL in unique_signals

    def test_params(self):
        strategy = SMACrossover(fast_period=10, slow_period=50)
        params = strategy.get_params()
        assert params["fast_period"] == 10
        assert params["slow_period"] == 50


class TestRSIMeanReversion:
    def test_generates_signals(self):
        strategy = RSIMeanReversion(rsi_period=14)
        df = _make_ranging_df(200)
        result = strategy.generate_signals(df)

        assert "signal" in result.columns
        assert "rsi" in result.columns

    def test_rsi_values_in_range(self):
        strategy = RSIMeanReversion()
        df = _make_ranging_df(200)
        result = strategy.generate_signals(df)

        rsi_values = result["rsi"].dropna()
        assert rsi_values.min() >= 0
        assert rsi_values.max() <= 100

    def test_params(self):
        strategy = RSIMeanReversion(rsi_period=10, oversold=25, overbought=75)
        params = strategy.get_params()
        assert params["rsi_period"] == 10
        assert params["oversold"] == 25


class TestBollingerBreakout:
    def test_generates_signals(self):
        strategy = BollingerBreakout(bb_period=20)
        df = _make_ranging_df(200)
        result = strategy.generate_signals(df)

        assert "signal" in result.columns
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns
        assert "bb_middle" in result.columns

    def test_bands_relationship(self):
        strategy = BollingerBreakout()
        df = _make_ranging_df(200)
        result = strategy.generate_signals(df)

        valid = result.dropna(subset=["bb_upper", "bb_lower", "bb_middle"])
        assert (valid["bb_upper"] >= valid["bb_middle"]).all()
        assert (valid["bb_middle"] >= valid["bb_lower"]).all()

    def test_params(self):
        strategy = BollingerBreakout(bb_period=25, bb_std=2.5)
        params = strategy.get_params()
        assert params["bb_period"] == 25
        assert params["bb_std"] == 2.5
