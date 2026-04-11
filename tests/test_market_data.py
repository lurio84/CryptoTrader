"""Tests for data/market_data.py API fetching functions.

Mocking strategy:
- For _get_with_retry tests: patch requests.get at data.market_data.requests.get
  and time.sleep to avoid real waits.
- For higher-level fetch tests: patch data.market_data._get_with_retry directly
  to return a mock Response, bypassing retry logic entirely.

Pattern: patch as close to usage as possible.
"""

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(json_data=None, text="", raise_for_status=None):
    """Build a mock requests.Response-like object."""
    resp = MagicMock()
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    if raise_for_status is not None:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status.return_value = None
    return resp


def _stooq_csv(rows):
    """Build a Stooq-style CSV string with N data rows."""
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, close in enumerate(rows):
        lines.append("2024-01-{:02d},100,105,95,{},1000000".format(i + 1, close))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# _get_with_retry
# ---------------------------------------------------------------------------

def test_get_with_retry_succeeds_on_first_try():
    from data.market_data import _get_with_retry

    mock_resp = _make_response()
    with patch("data.market_data.requests.get", return_value=mock_resp) as mock_get:
        result = _get_with_retry("http://example.com")
    assert result is mock_resp
    assert mock_get.call_count == 1


def test_get_with_retry_retries_on_failure():
    from data.market_data import _get_with_retry

    mock_resp = _make_response()
    side_effects = [Exception("timeout"), mock_resp]
    with patch("data.market_data.requests.get", side_effect=side_effects) as mock_get, \
         patch("data.market_data.time.sleep"):
        result = _get_with_retry("http://example.com")
    assert result is mock_resp
    assert mock_get.call_count == 2


def test_get_with_retry_raises_after_all_retries():
    from data.market_data import _get_with_retry

    with patch("data.market_data.requests.get", side_effect=Exception("network error")), \
         patch("data.market_data.time.sleep"):
        try:
            _get_with_retry("http://example.com", retries=3)
            assert False, "Should have raised"
        except Exception as e:
            assert "network error" in str(e)


# ---------------------------------------------------------------------------
# fetch_prices
# ---------------------------------------------------------------------------

def test_fetch_prices_success():
    from data.market_data import fetch_prices

    mock_json = {
        "bitcoin": {"usd": 95000.0, "eur": 87000.0, "usd_24h_change": -2.5},
        "ethereum": {"usd": 3500.0, "eur": 3200.0, "usd_24h_change": 1.1},
    }
    mock_resp = _make_response(json_data=mock_json)
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_prices()

    assert result["btc_price"] == 95000.0
    assert result["btc_price_eur"] == 87000.0
    assert result["btc_change_24h"] == -2.5
    assert result["eth_price"] == 3500.0
    assert result["eth_price_eur"] == 3200.0
    assert result["eth_change_24h"] == 1.1


def test_fetch_prices_returns_none_on_failure():
    from data.market_data import fetch_prices

    with patch("data.market_data._get_with_retry", side_effect=Exception("API down")):
        result = fetch_prices()

    assert result["btc_price"] is None
    assert result["btc_price_eur"] is None
    assert result["btc_change_24h"] is None
    assert result["eth_price"] is None
    assert result["eth_price_eur"] is None
    assert result["eth_change_24h"] is None


# ---------------------------------------------------------------------------
# fetch_mvrv
# ---------------------------------------------------------------------------

def test_fetch_mvrv_success():
    from data.market_data import fetch_mvrv

    mock_json = {"data": [{"CapMVRVCur": "2.15"}]}
    mock_resp = _make_response(json_data=mock_json)
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_mvrv("eth")

    assert isinstance(result, float)
    assert result == 2.15


def test_fetch_mvrv_returns_none_when_key_missing():
    """CapMVRVCur absent -> None (not 0.0). Validates MVRV None-safe convention."""
    from data.market_data import fetch_mvrv

    mock_json = {"data": [{"SomeOtherMetric": "1.5"}]}
    mock_resp = _make_response(json_data=mock_json)
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_mvrv("btc")

    assert result is None


def test_fetch_mvrv_returns_none_on_failure():
    from data.market_data import fetch_mvrv

    with patch("data.market_data._get_with_retry", side_effect=Exception("API down")):
        result = fetch_mvrv("btc")

    assert result is None


# ---------------------------------------------------------------------------
# fetch_funding_rate
# ---------------------------------------------------------------------------

def test_fetch_funding_rate_success():
    from data.market_data import fetch_funding_rate

    mock_json = {"data": [{"fundingRate": "-0.0001"}]}
    mock_resp = _make_response(json_data=mock_json)
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_funding_rate()

    assert isinstance(result, float)
    assert result == -0.0001


def test_fetch_funding_rate_returns_none_on_failure():
    from data.market_data import fetch_funding_rate

    with patch("data.market_data._get_with_retry", side_effect=Exception("OKX down")):
        result = fetch_funding_rate()

    assert result is None


# ---------------------------------------------------------------------------
# fetch_sp500_change
# ---------------------------------------------------------------------------

def test_fetch_sp500_change_success():
    from data.market_data import fetch_sp500_change

    # 7 rows: base price 500, recent price 490 -> change = (490-500)/500*100 = -2.0%
    closes = [500, 498, 502, 497, 503, 495, 490]
    mock_resp = _make_response(text=_stooq_csv(closes))
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_sp500_change(days=5)

    assert result is not None
    assert isinstance(result, float)


def test_fetch_sp500_change_insufficient_rows():
    from data.market_data import fetch_sp500_change

    mock_resp = _make_response(text=_stooq_csv([500]))
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_sp500_change(days=5)

    assert result is None


def test_fetch_sp500_change_returns_none_on_failure():
    from data.market_data import fetch_sp500_change

    with patch("data.market_data._get_with_retry", side_effect=Exception("Stooq down")):
        result = fetch_sp500_change()

    assert result is None


# ---------------------------------------------------------------------------
# fetch_fear_greed
# ---------------------------------------------------------------------------

def test_fetch_fear_greed_success():
    from data.market_data import fetch_fear_greed

    mock_json = {"data": [{"value": "25", "value_classification": "Extreme Fear"}]}
    mock_resp = _make_response(json_data=mock_json)
    with patch("data.market_data._get_with_retry", return_value=mock_resp):
        result = fetch_fear_greed()

    assert result["fear_greed_value"] == 25
    assert result["fear_greed_label"] == "Extreme Fear"


def test_fetch_fear_greed_returns_none_value_on_failure():
    from data.market_data import fetch_fear_greed

    with patch("data.market_data._get_with_retry", side_effect=Exception("API down")):
        result = fetch_fear_greed()

    assert result["fear_greed_value"] is None
    assert result["fear_greed_label"] == "N/A"
