"""Fetch current ETF/stock prices in EUR using yfinance.

LOCAL-ONLY MODULE -- Never import from alerts/ or any module that runs in
GitHub Actions CI. yfinance is an optional dependency (pip install -e ".[all]").

EUR conversion: fetches EURUSD=X ticker from yfinance.
All functions return None gracefully on any network or import failure.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticker mapping: canonical asset name -> yfinance symbol
# Tickers correspond to the exact instruments sold by Trade Republic.
# EUR tickers (XETRA): returned directly, no conversion needed.
# USD tickers (NYSE): converted via EURUSD=X.
# ---------------------------------------------------------------------------

ETF_TICKERS: dict[str, str] = {
    "SP500":          "AUM5.DE",  # Amundi S&P 500 Swap UCITS ETF (EUR, XETRA) LU1681049018
    "SEMICONDUCTORS": "SEC0.DE",  # iShares MSCI Global Semiconductors UCITS ETF (EUR, XETRA) IE000I8KRLL9
    "REALTY_INCOME":  "O",        # Realty Income Corp (USD, NYSE) US7561091049
    "URANIUM":        "URNU.DE",  # Global X Uranium UCITS ETF (EUR, XETRA) IE000NDWFGA5
}


def _get_eur_usd() -> float | None:
    """Return current EUR/USD exchange rate from yfinance, or None on failure."""
    try:
        import yfinance as yf
        ticker = yf.Ticker("EURUSD=X")
        hist = ticker.history(period="2d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning("Failed to fetch EUR/USD rate from yfinance: %s", e)
        return None


def _ticker_price_eur(ticker_sym: str, yf, eurusd: float | None) -> float | None:
    """Return EUR price for a single yfinance ticker.

    EUR-denominated tickers (e.g. XETRA .DE) are returned directly.
    USD-denominated tickers (e.g. NYSE) are converted via eurusd rate.
    """
    ticker = yf.Ticker(ticker_sym)
    hist = ticker.history(period="2d")
    if hist.empty:
        return None
    price = float(hist["Close"].iloc[-1])
    currency = ticker.fast_info.get("currency", "USD")
    if currency == "EUR":
        return price
    if eurusd and eurusd > 0:
        return price / eurusd
    return None


def fetch_etf_price_eur(asset_name: str) -> float | None:
    """Return current price in EUR for a given ETF asset name, or None on failure."""
    try:
        import yfinance as yf
        ticker_sym = ETF_TICKERS.get(asset_name.upper())
        if ticker_sym is None:
            return None
        eurusd = _get_eur_usd()
        return _ticker_price_eur(ticker_sym, yf, eurusd)
    except Exception as e:
        logger.warning("Failed to fetch ETF price for %s: %s", asset_name, e)
        return None


def fetch_all_etf_prices_eur() -> dict[str, float | None]:
    """Return {asset_name: price_eur_or_None} for all known ETF assets.

    Fetches EUR/USD rate once and reuses it for all tickers to minimise
    API calls. EUR-native tickers skip the conversion.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {name: None for name in ETF_TICKERS}

    eurusd = _get_eur_usd()

    result: dict[str, float | None] = {}
    for asset_name, ticker_sym in ETF_TICKERS.items():
        try:
            result[asset_name] = _ticker_price_eur(ticker_sym, yf, eurusd)
        except Exception as e:
            logger.warning("Failed to fetch price for %s: %s", asset_name, e)
            result[asset_name] = None
    return result
