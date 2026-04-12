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

import csv
import io
import logging
import time
from datetime import date, timedelta

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


def fetch_portfolio_prices_eur(include_etfs: bool = True) -> dict:
    """Fetch BTC/ETH prices in EUR plus optional ETF prices for portfolio views.

    Args:
        include_etfs: If True, try to fetch ETF EUR prices via yfinance (lazy import).
                      Fails gracefully if yfinance is unavailable (e.g. CI).

    Returns dict with keys:
        btc_eur:        float | None
        eth_eur:        float | None
        etf_prices:     dict[str, float]  (may be empty)

    Shared by cli/commands_portfolio.py, cli/commands_ops.py (drift-check),
    alerts/digest.py and dashboard endpoints.
    """
    result = {"btc_eur": None, "eth_eur": None, "etf_prices": {}}

    prices = fetch_prices()
    result["btc_eur"] = prices.get("btc_price_eur")
    result["eth_eur"] = prices.get("eth_price_eur")

    if include_etfs:
        try:
            from data.etf_prices import fetch_all_etf_prices_eur
            result["etf_prices"] = fetch_all_etf_prices_eur() or {}
        except ImportError:
            logger.info("yfinance not installed -- ETF prices unavailable")
        except Exception as exc:
            logger.warning("ETF price fetch failed: %s", exc)

    return result


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


def fetch_price_history(asset: str, days: int = 30) -> list[float] | None:
    """Fetch daily closing prices for BTC or ETH from CoinGecko.

    Args:
        asset: CoinGecko coin id, e.g. 'bitcoin' or 'ethereum'.
        days: Number of calendar days to fetch (default 30).

    Returns list of daily close prices in USD, or None on failure.
    CoinGecko free tier returns one price per day for days > 1.
    """
    try:
        url = "https://api.coingecko.com/api/v3/coins/{}/market_chart".format(asset)
        resp = _get_with_retry(url, params={"vs_currency": "usd", "days": days, "interval": "daily"}, timeout=15)
        prices = resp.json().get("prices", [])
        return [float(p[1]) for p in prices] if prices else None
    except Exception as e:
        logger.error("Failed to fetch price history for %s: %s", asset, e)
        return None


def fetch_sp500_history(days: int = 30) -> list[float] | None:
    """Fetch daily closing prices for S&P 500 (SPY) from Stooq.

    Returns list of daily close prices sorted ascending by date, or None on failure.
    """
    try:
        end = date.today()
        start = end - timedelta(days=days * 2 + 10)
        url = (
            "https://stooq.com/q/d/l/?s=spy.us&d1={}&d2={}&i=d".format(
                start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
            )
        )
        resp = _get_with_retry(url, timeout=15)
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = [r for r in reader if r.get("Close") and r["Close"] != "null"]
        if len(rows) < 5:
            return None
        rows.sort(key=lambda r: r.get("Date", ""))
        closes = [float(r["Close"]) for r in rows]
        return closes[-days:] if len(closes) >= days else closes
    except Exception as e:
        logger.error("Failed to fetch S&P 500 history from Stooq: %s", e)
        return None


def calc_correlation(series_a: list[float], series_b: list[float]) -> float | None:
    """Calculate Pearson correlation of daily returns between two price series.

    Returns correlation coefficient [-1, 1], or None if insufficient data.
    Uses stdlib statistics.correlation (Python 3.10+).
    """
    import statistics

    min_len = min(len(series_a), len(series_b))
    if min_len < 10:
        return None
    a = series_a[-min_len:]
    b = series_b[-min_len:]
    returns_a = [(a[i] - a[i - 1]) / a[i - 1] for i in range(1, len(a)) if a[i - 1] != 0]
    returns_b = [(b[i] - b[i - 1]) / b[i - 1] for i in range(1, len(b)) if b[i - 1] != 0]
    min_ret = min(len(returns_a), len(returns_b))
    if min_ret < 9:
        return None
    try:
        return statistics.correlation(returns_a[:min_ret], returns_b[:min_ret])
    except Exception:
        return None
