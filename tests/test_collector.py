from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from data.collector import DataCollector


def _make_ohlcv_raw(n: int = 5, start_ts: int = 1704067200000) -> list:
    """Generate fake OHLCV data (Binance format)."""
    data = []
    for i in range(n):
        ts = start_ts + i * 3600000  # 1h intervals
        data.append([ts, 42000 + i, 42100 + i, 41900 + i, 42050 + i, 100.0 + i])
    return data


@patch("ccxt.binance")
def test_fetch_ohlcv(mock_binance_class):
    """Test fetching OHLCV data returns correct DataFrame."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv.return_value = _make_ohlcv_raw(5)
    mock_binance_class.return_value = mock_exchange

    collector = DataCollector("binance")
    df = collector.fetch_ohlcv("BTC/USDT", "1h")

    assert len(df) == 5
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    assert df["symbol"].iloc[0] == "BTC/USDT"
    assert df["timeframe"].iloc[0] == "1h"


@patch("ccxt.binance")
def test_fetch_ohlcv_empty(mock_binance_class):
    """Test fetching with no data returns empty DataFrame."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv.return_value = []
    mock_binance_class.return_value = mock_exchange

    collector = DataCollector("binance")
    df = collector.fetch_ohlcv("BTC/USDT", "1h")

    assert df.empty


@patch("ccxt.binance")
def test_fetch_all_history_pagination(mock_binance_class):
    """Test that fetch_all_history paginates correctly."""
    mock_exchange = MagicMock()
    # First call returns 1000, second returns 500 (< limit, signals end)
    mock_exchange.fetch_ohlcv.side_effect = [
        _make_ohlcv_raw(1000, start_ts=1704067200000),
        _make_ohlcv_raw(500, start_ts=1704067200000 + 1000 * 3600000),
    ]
    mock_binance_class.return_value = mock_exchange

    collector = DataCollector("binance")
    df = collector.fetch_all_history("BTC/USDT", "1h")

    assert len(df) == 1500
    assert mock_exchange.fetch_ohlcv.call_count == 2


def test_load_candles_empty():
    """Test loading candles when DB is empty."""
    with patch("data.collector.get_session") as mock_session:
        mock_ctx = MagicMock()
        mock_session.return_value.__enter__ = lambda s: mock_ctx
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_ctx.execute.return_value = mock_result

        collector = DataCollector.__new__(DataCollector)
        df = collector.load_candles("BTC/USDT", "1h")
        assert df.empty
