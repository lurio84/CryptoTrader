"""Tests for backtesting/crash_dca_engine.py."""

import pandas as pd
import numpy as np
from backtesting.crash_dca_engine import CrashDCAEngine, CrashDCASettings, CrashDCAResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candles(n_hours: int = 1000, base_price: float = 40_000.0) -> pd.DataFrame:
    """Generate synthetic hourly OHLCV data with slight upward drift."""
    rng = np.random.default_rng(42)
    prices = base_price * np.cumprod(1 + rng.normal(0.0002, 0.01, n_hours))
    timestamps = pd.date_range("2022-01-01", periods=n_hours, freq="h", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": rng.uniform(100, 1000, n_hours),
    })


def _make_crash_candles(crash_at_hour: int = 200, n_hours: int = 800) -> pd.DataFrame:
    """Generate synthetic data with a -20% drop at crash_at_hour."""
    rng = np.random.default_rng(7)
    prices = np.ones(n_hours) * 40_000.0
    # Slow drift upward
    for i in range(1, n_hours):
        prices[i] = prices[i - 1] * (1 + rng.normal(0.0001, 0.005))
    # Inject crash: simulate -20% over 24 hours
    if crash_at_hour + 24 < n_hours:
        drop = 0.20 / 24
        for j in range(24):
            prices[crash_at_hour + j] *= (1 - drop)
    timestamps = pd.date_range("2022-01-01", periods=n_hours, freq="h", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": prices * 1.003,
        "low": prices * 0.997,
        "close": prices,
        "volume": rng.uniform(100, 500, n_hours),
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_returns_result_type():
    """Engine.run() returns a CrashDCAResult dataclass."""
    engine = CrashDCAEngine()
    df = _make_candles()
    result = engine.run(df)
    assert isinstance(result, CrashDCAResult)


def test_invested_positive():
    """Total invested must be positive after a run."""
    engine = CrashDCAEngine()
    result = engine.run(_make_candles())
    assert result.total_invested > 0
    assert result.fixed_invested > 0


def test_dca_buys_at_least_one():
    """There should be at least one regular DCA buy."""
    engine = CrashDCAEngine()
    result = engine.run(_make_candles(n_hours=500))
    assert result.dca_buys >= 1


def test_crash_buys_detected_with_crash_data():
    """When crash data is used, crash_buys should be > 0."""
    settings = CrashDCASettings(
        crash_threshold_1=-0.05,   # lowered to make it easier to trigger
        crash_threshold_2=-0.10,
        crash_threshold_3=-0.15,
        crash_cooldown_hours=1,
    )
    engine = CrashDCAEngine(crash_settings=settings)
    df = _make_crash_candles(crash_at_hour=100)
    result = engine.run(df)
    assert result.crash_buys >= 1, "Expected at least one crash buy with injected crash data"


def test_no_crash_buys_when_threshold_not_met():
    """If crash threshold is very low, no crash buys should happen on stable data."""
    settings = CrashDCASettings(
        crash_threshold_1=-0.99,  # -99%: practically never triggered
        crash_threshold_2=-0.999,
        crash_threshold_3=-0.9999,
    )
    engine = CrashDCAEngine(crash_settings=settings)
    result = engine.run(_make_candles())
    assert result.crash_buys == 0


def test_equity_curve_length_matches_daily_rows():
    """Equity curve length should equal number of daily candles."""
    engine = CrashDCAEngine()
    df = _make_candles(n_hours=480)  # 20 days
    result = engine.run(df)
    # Daily resample: 480 hours -> ~20 days
    assert len(result.equity_curve) > 0
    assert len(result.equity_curve) <= 21  # at most 21 daily bars


def test_summary_returns_string():
    """CrashDCAResult.summary() returns a non-empty string."""
    engine = CrashDCAEngine()
    result = engine.run(_make_candles())
    summary = result.summary()
    assert isinstance(summary, str)
    assert "CRASH DCA" in summary


def test_return_pct_defined():
    """return_pct and fixed_return_pct must be defined numbers."""
    engine = CrashDCAEngine()
    result = engine.run(_make_candles())
    assert isinstance(result.return_pct, float)
    assert isinstance(result.fixed_return_pct, float)


def test_avg_buy_price_positive():
    """Average buy price must be positive."""
    engine = CrashDCAEngine()
    result = engine.run(_make_candles())
    assert result.avg_buy_price > 0
    assert result.fixed_avg_buy_price > 0


def test_custom_settings_applied():
    """Custom base amount should affect total invested."""
    small = CrashDCASettings(base_amount_usdt=10.0)
    large = CrashDCASettings(base_amount_usdt=100.0)
    df = _make_candles()
    result_small = CrashDCAEngine(crash_settings=small).run(df)
    result_large = CrashDCAEngine(crash_settings=large).run(df)
    assert result_large.fixed_invested > result_small.fixed_invested
