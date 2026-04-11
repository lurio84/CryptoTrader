"""Shared market data fetching functions.

Centralizes all external API calls so they are not duplicated across
alerts/discord_bot.py, dashboard/app.py and main.py.

APIs used:
- CoinGecko (prices): no API key, public
- CoinMetrics community (MVRV): no API key, public
- OKX (funding rate): no API key, public, no GitHub geo-block
- alternative.me (Fear & Greed): no API key, public
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


def _get_with_retry(url: str, params: dict | None = None, timeout: int = 10, retries: int = 3) -> requests.Response:
    """HTTP GET with exponential backoff retry on transient network errors.

    Raises the last exception if all retries are exhausted.
    Waits 1s, 2s between attempts (2^attempt seconds).
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "API request failed (attempt %d/%d), retry in %ds: %s",
                    attempt + 1, retries, wait, exc,
                )
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def fetch_prices() -> dict:
    """Fetch BTC and ETH prices from CoinGecko.

    Returns dict with keys:
        btc_price, btc_price_eur, btc_change_24h,
        eth_price, eth_price_eur, eth_change_24h
    All values are None on failure.
    """
    try:
        resp = _get_with_retry(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin,ethereum",
                "vs_currencies": "usd,eur",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        data = resp.json()
        return {
            "btc_price":       data["bitcoin"]["usd"],
            "btc_price_eur":   data["bitcoin"]["eur"],
            "btc_change_24h":  data["bitcoin"]["usd_24h_change"],
            "eth_price":       data["ethereum"]["usd"],
            "eth_price_eur":   data["ethereum"]["eur"],
            "eth_change_24h":  data["ethereum"]["usd_24h_change"],
        }
    except Exception as e:
        logger.error("Failed to fetch prices from CoinGecko: %s", e)
        return {
            "btc_price": None, "btc_price_eur": None, "btc_change_24h": None,
            "eth_price": None, "eth_price_eur": None, "eth_change_24h": None,
        }


def fetch_mvrv(asset: str) -> float | None:
    """Fetch MVRV ratio from CoinMetrics community API.

    Args:
        asset: "btc" or "eth"

    Returns float MVRV value, or None on failure.
    Note: BTC MVRV is informativo only -- validated in research3/5 that high
    MVRV predicts HIGHER returns, not lower. Not a sell signal.
    """
    try:
        resp = _get_with_retry(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={
                "assets": asset,
                "metrics": "CapMVRVCur",
                "frequency": "1d",
                "page_size": "1",
                "paging_from": "end",
            },
            timeout=10,
        )
        data = resp.json().get("data", [])
        if data:
            raw = data[0].get("CapMVRVCur")
            return float(raw) if raw is not None else None
        return None
    except Exception as e:
        logger.error("Failed to fetch %s MVRV: %s", asset.upper(), e)
        return None


def fetch_funding_rate() -> float | None:
    """Fetch current BTC perpetual funding rate from OKX.

    OKX has no geo-restrictions from GitHub Actions (unlike Binance/Bybit).
    Returns float rate (e.g. -0.0001 = -0.01%), or None on failure.
    """
    try:
        resp = _get_with_retry(
            "https://www.okx.com/api/v5/public/funding-rate",
            params={"instId": "BTC-USDT-SWAP"},
            timeout=10,
        )
        data = resp.json().get("data", [])
        if data:
            return float(data[0]["fundingRate"])
        return None
    except Exception as e:
        logger.error("Failed to fetch funding rate from OKX: %s", e)
        return None


def fetch_sp500_change(days: int = 5) -> float | None:
    """Fetch S&P 500 recent price change via Stooq (no API key, works in GitHub Actions).

    Args:
        days: Number of trading days to look back (default 5 = one week).

    Returns percentage change over the last `days` trading days, or None on failure.
    Validated threshold: -5% over 5d (research6: N=31, consistent edge).
    """
    try:
        import csv
        import io
        from datetime import date, timedelta

        end = date.today()
        # Request extra calendar days to ensure we get enough trading days
        start = end - timedelta(days=days * 3 + 10)
        url = (
            "https://stooq.com/q/d/l/?s=spy.us&d1={}&d2={}&i=d".format(
                start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
            )
        )
        resp = _get_with_retry(url, timeout=15)
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = [r for r in reader if r.get("Close") and r["Close"] != "null"]
        if len(rows) < 2:
            logger.warning("Stooq returned insufficient data for SPY (%d rows)", len(rows))
            return None
        rows.sort(key=lambda r: r.get("Date", ""))
        closes = [float(r["Close"]) for r in rows]
        recent = closes[-1]
        base_idx = max(0, len(closes) - 1 - days)
        base = closes[base_idx]
        return float((recent - base) / base * 100)
    except Exception as e:
        logger.error("Failed to fetch S&P 500 change from Stooq: %s", e)
        return None


def fetch_fear_greed() -> dict:
    """Fetch current Fear & Greed Index from alternative.me.

    Returns dict with keys:
        fear_greed_value (int|None), fear_greed_label (str)

    Note: F&G is NOT a buy signal -- validated in research that extreme fear
    gives WORSE returns than baseline. Kept as informational display only.
    """
    try:
        resp = _get_with_retry(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10,
        )
        data = resp.json().get("data", [{}])[0]
        return {
            "fear_greed_value": int(data.get("value", 0)),
            "fear_greed_label": data.get("value_classification", "N/A"),
        }
    except Exception as e:
        logger.error("Failed to fetch Fear & Greed: %s", e)
        return {"fear_greed_value": None, "fear_greed_label": "N/A"}
