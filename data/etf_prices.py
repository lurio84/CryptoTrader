"""Fetch current ETF/stock prices in EUR using yfinance.

LOCAL-ONLY MODULE -- Never import from alerts/ or any module that runs in
GitHub Actions CI. yfinance is an optional dependency (pip install -e ".[all]").

EUR conversion: fetches EURUSD=X ticker from yfinance.
All functions return None gracefully on any network or import failure.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Ticker mapping: canonical asset name -> yfinance symbol
# ---------------------------------------------------------------------------

ETF_TICKERS: dict[str, str] = {
    "SP500":          "SPY",   # iShares S&P 500 (US proxy; TR uses UCITS equiv)
    "SEMICONDUCTORS": "SOXX",  # iShares Semiconductor ETF
    "REALTY_INCOME":  "O",     # Realty Income Corp (NYSE)
    "URANIUM":        "URA",   # Global X Uranium ETF
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
    except Exception:
        return None


def fetch_etf_price_eur(asset_name: str) -> float | None:
    """Return current price in EUR for a given ETF asset name, or None on failure.

    Args:
        asset_name: key from ETF_TICKERS (e.g. "SP500", "URANIUM").
                    Case-insensitive.
    """
    try:
        import yfinance as yf
        ticker_sym = ETF_TICKERS.get(asset_name.upper())
        if ticker_sym is None:
            return None
        eurusd = _get_eur_usd()
        if eurusd is None or eurusd <= 0:
            return None
        ticker = yf.Ticker(ticker_sym)
        hist = ticker.history(period="2d")
        if hist.empty:
            return None
        price_usd = float(hist["Close"].iloc[-1])
        return price_usd / eurusd
    except Exception:
        return None


def fetch_all_etf_prices_eur() -> dict[str, float | None]:
    """Return {asset_name: price_eur_or_None} for all known ETF assets.

    Fetches EUR/USD rate once and reuses it for all tickers to minimize
    API calls.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {name: None for name in ETF_TICKERS}

    eurusd = _get_eur_usd()
    if eurusd is None or eurusd <= 0:
        return {name: None for name in ETF_TICKERS}

    result: dict[str, float | None] = {}
    for asset_name, ticker_sym in ETF_TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_sym)
            hist = ticker.history(period="2d")
            if hist.empty:
                result[asset_name] = None
            else:
                result[asset_name] = float(hist["Close"].iloc[-1]) / eurusd
        except Exception:
            result[asset_name] = None
    return result
