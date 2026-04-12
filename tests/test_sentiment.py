import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _make_collector():
    """Create SentimentCollector with mocked ccxt (no real exchange or network needed)."""
    with patch("ccxt.binance") as mock_exchange_class:
        mock_exchange = MagicMock()
        mock_exchange_class.return_value = mock_exchange
        from data.sentiment import SentimentCollector
        collector = SentimentCollector()
    # Reassign so tests can configure responses after the context manager exits
    collector.exchange = mock_exchange
    return collector, mock_exchange


def _make_fg_df(n: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "timestamp": dates,
        "fear_greed_value": [10, 30, 50, 70, 90][:n],
        "fear_greed_label": ["Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"][:n],
    })


class TestFetchFundingRate:
    def test_normal_response_returns_float(self):
        collector, mock_exchange = _make_collector()
        mock_exchange.fetch_funding_rate.return_value = {"fundingRate": 0.0003}

        result = collector.fetch_funding_rate("BTC/USDT:USDT")

        assert result == pytest.approx(0.0003)

    def test_exception_returns_none(self):
        collector, mock_exchange = _make_collector()
        mock_exchange.fetch_funding_rate.side_effect = Exception("connection error")

        result = collector.fetch_funding_rate("BTC/USDT:USDT")

        assert result is None

    def test_missing_key_returns_none(self):
        collector, mock_exchange = _make_collector()
        mock_exchange.fetch_funding_rate.return_value = {}  # no fundingRate key

        result = collector.fetch_funding_rate("BTC/USDT:USDT")

        assert result is None


class TestCollectAll:
    def test_normal_flow_returns_inserted_count(self):
        collector, _ = _make_collector()
        fg_df = _make_fg_df()

        with patch.object(collector, "fetch_fear_greed", return_value=fg_df), \
             patch.object(collector, "fetch_funding_history", return_value=pd.DataFrame()), \
             patch.object(collector, "save_sentiment", return_value=5) as mock_save:
            result = collector.collect_all(days=5)

        assert result == 5
        mock_save.assert_called_once()
        saved_df = mock_save.call_args[0][0]
        assert not saved_df.empty

    def test_empty_fear_greed_returns_zero(self):
        collector, _ = _make_collector()

        with patch.object(collector, "fetch_fear_greed", return_value=pd.DataFrame()), \
             patch.object(collector, "fetch_funding_history", return_value=pd.DataFrame()), \
             patch.object(collector, "save_sentiment", return_value=0) as mock_save:
            result = collector.collect_all(days=5)

        assert result == 0
        # save_sentiment is still called (with the empty df)
        mock_save.assert_called_once()
