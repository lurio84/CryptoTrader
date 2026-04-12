import pandas as pd
import numpy as np
import pytest

from config.settings import DCASettings
from backtesting.dca_engine import DCABacktestEngine, DCABacktestResult


def _make_candles(n_days: int = 200, start_price: float = 40000) -> pd.DataFrame:
    """Generate daily candle data."""
    np.random.seed(42)
    prices = start_price + np.cumsum(np.random.normal(50, 500, n_days * 24))
    prices = np.maximum(prices, 1000)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n_days * 24, freq="h", tz="UTC"),
        "open": prices - 20,
        "high": prices + 50,
        "low": prices - 50,
        "close": prices,
        "volume": np.random.uniform(100, 500, n_days * 24),
    })


def _make_sentiment(n_days: int = 200) -> pd.DataFrame:
    """Generate sentiment data with varying fear/greed."""
    np.random.seed(42)
    values = np.clip(np.random.normal(50, 20, n_days).astype(int), 0, 100)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n_days, freq="D", tz="UTC"),
        "fear_greed_value": values,
        "fear_greed_label": ["Fear" if v < 40 else "Greed" if v > 60 else "Neutral" for v in values],
        "funding_rate_btc": np.random.normal(0.0002, 0.0003, n_days),
        "funding_rate_eth": np.random.normal(0.0002, 0.0003, n_days),
    })


class TestDCASettings:
    def test_multiplier_extreme_fear(self):
        dca = DCASettings()
        assert dca.get_multiplier(5) == 2.0
        assert dca.get_multiplier(15) == 2.0

    def test_multiplier_fear(self):
        dca = DCASettings()
        assert dca.get_multiplier(20) == 1.5
        assert dca.get_multiplier(30) == 1.5

    def test_multiplier_neutral(self):
        dca = DCASettings()
        assert dca.get_multiplier(40) == 1.0
        assert dca.get_multiplier(50) == 1.0

    def test_multiplier_greed(self):
        dca = DCASettings()
        assert dca.get_multiplier(60) == 0.5
        assert dca.get_multiplier(75) == 0.5

    def test_multiplier_extreme_greed(self):
        dca = DCASettings()
        assert dca.get_multiplier(80) == 0.0
        assert dca.get_multiplier(100) == 0.0

    def test_funding_rate_adjustment_high(self):
        dca = DCASettings()
        # High funding should reduce multiplier by 25%
        mult = dca.get_multiplier(40, funding_rate=0.001)
        assert mult == pytest.approx(0.75)  # 1.0 * 0.75

    def test_funding_rate_adjustment_low(self):
        dca = DCASettings()
        # Negative funding should increase multiplier by 25%
        mult = dca.get_multiplier(40, funding_rate=-0.001)
        assert mult == pytest.approx(1.25)  # 1.0 * 1.25

    def test_funding_no_effect_on_zero_multiplier(self):
        dca = DCASettings()
        # Extreme greed = 0 multiplier, funding shouldn't change it
        assert dca.get_multiplier(90, funding_rate=-0.01) == 0.0


class TestDCABacktestEngine:
    def test_run_returns_result(self):
        candles = _make_candles(100)
        sentiment = _make_sentiment(100)
        engine = DCABacktestEngine()
        result = engine.run(candles, sentiment, "BTC/USDT")

        assert isinstance(result, DCABacktestResult)
        assert result.symbol == "BTC/USDT"
        assert result.smart_total_invested > 0
        assert result.fixed_total_invested > 0
        assert result.smart_total_buys > 0

    def test_fixed_dca_always_invests(self):
        candles = _make_candles(100)
        sentiment = _make_sentiment(100)
        engine = DCABacktestEngine()
        result = engine.run(candles, sentiment, "BTC/USDT")

        # Fixed DCA should invest every period
        expected_buys = 100 // 7  # ~14 weekly buys
        assert result.fixed_total_invested == pytest.approx(
            expected_buys * 50.0, rel=0.1
        )

    def test_smart_invests_less_in_greed(self):
        """Smart DCA should invest less total when market is greedy."""
        candles = _make_candles(100)
        # All greed sentiment
        greed_sentiment = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "fear_greed_value": [80] * 100,  # extreme greed
            "funding_rate_btc": [0.0002] * 100,
            "funding_rate_eth": [0.0002] * 100,
        })
        engine = DCABacktestEngine()
        result = engine.run(candles, greed_sentiment, "BTC/USDT")

        # Smart should invest 0 in extreme greed
        assert result.smart_total_invested == 0
        assert result.smart_total_buys == 0

    def test_smart_invests_more_in_fear(self):
        """Smart DCA should invest more when market is fearful."""
        candles = _make_candles(100)
        # All fear sentiment
        fear_sentiment = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "fear_greed_value": [10] * 100,  # extreme fear
            "funding_rate_btc": [0.0002] * 100,
            "funding_rate_eth": [0.0002] * 100,
        })
        engine = DCABacktestEngine()
        result = engine.run(candles, fear_sentiment, "BTC/USDT")

        # Smart should invest 2x in extreme fear
        assert result.smart_total_invested > result.fixed_total_invested * 1.5

    def test_summary_output(self):
        candles = _make_candles(100)
        sentiment = _make_sentiment(100)
        engine = DCABacktestEngine()
        result = engine.run(candles, sentiment, "BTC/USDT")
        summary = result.summary()

        assert "SMART DCA" in summary
        assert "FIXED DCA" in summary
        assert "BUY & HOLD" in summary
        assert "BTC/USDT" in summary

    def test_f18_run_twice_gives_same_result(self):
        """F18: calling run() twice on the same engine instance must not accumulate state."""
        candles = _make_candles(100)
        sentiment = _make_sentiment(100)
        engine = DCABacktestEngine()

        result1 = engine.run(candles, sentiment, "BTC/USDT")
        result2 = engine.run(candles, sentiment, "BTC/USDT")

        assert result1.smart_total_invested == pytest.approx(result2.smart_total_invested)
        assert result1.smart_total_buys == result2.smart_total_buys
        assert result1.fixed_total_invested == pytest.approx(result2.fixed_total_invested)
