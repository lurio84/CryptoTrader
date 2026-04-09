"""FastAPI dashboard for CryptoTrader Advisor."""

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ccxt
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from config.settings import settings
from data.database import init_db, get_session
from data.models import SentimentData, AlertLog

logger = logging.getLogger(__name__)

app = FastAPI(title="CryptoTrader Advisor")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _fetch_prices() -> dict:
    """Fetch current BTC and ETH prices from exchange."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        btc_ticker = exchange.fetch_ticker("BTC/USDT")
        eth_ticker = exchange.fetch_ticker("ETH/USDT")
        return {
            "btc_price": btc_ticker.get("last", 0),
            "btc_change_24h": btc_ticker.get("percentage", 0),
            "eth_price": eth_ticker.get("last", 0),
            "eth_change_24h": eth_ticker.get("percentage", 0),
        }
    except Exception as e:
        logger.error("Failed to fetch prices: %s", e)
        return {
            "btc_price": None,
            "btc_change_24h": None,
            "eth_price": None,
            "eth_change_24h": None,
        }


def _fetch_fear_greed() -> dict:
    """Fetch current Fear & Greed Index."""
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        return {
            "fear_greed_value": int(data.get("value", 0)),
            "fear_greed_label": data.get("value_classification", "N/A"),
        }
    except Exception as e:
        logger.error("Failed to fetch Fear & Greed: %s", e)
        return {"fear_greed_value": None, "fear_greed_label": "N/A"}


def _fetch_eth_mvrv() -> float | None:
    """Fetch ETH MVRV from CoinMetrics community API."""
    try:
        resp = requests.get(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={
                "assets": "eth",
                "metrics": "CapMVRVCur",
                "frequency": "1d",
                "page_size": "1",
                "paging_from": "end",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return float(data[0].get("CapMVRVCur", 0))
        return None
    except Exception as e:
        logger.error("Failed to fetch ETH MVRV: %s", e)
        return None


def _get_latest_funding_rate() -> float | None:
    """Get the latest BTC funding rate from DB."""
    try:
        with get_session() as session:
            row = session.execute(
                select(SentimentData)
                .where(SentimentData.funding_rate_btc.isnot(None))
                .order_by(SentimentData.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row:
                return row.funding_rate_btc
        return None
    except Exception:
        return None


def _get_alert_history(limit: int = 20) -> list[dict]:
    """Get recent alert history from DB."""
    try:
        with get_session() as session:
            rows = session.execute(
                select(AlertLog)
                .order_by(AlertLog.timestamp.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {
                    "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else "",
                    "alert_type": r.alert_type,
                    "severity": r.severity,
                    "message": r.message,
                    "btc_price": r.btc_price,
                    "eth_price": r.eth_price,
                    "metric_value": r.metric_value,
                }
                for r in rows
            ]
    except Exception:
        return []


def _evaluate_alerts(prices: dict, funding_rate: float | None, mvrv: float | None) -> list[dict]:
    """Evaluate current alert conditions."""
    alerts = []

    btc_change = prices.get("btc_change_24h")
    if btc_change is not None and btc_change <= -15:
        alerts.append({
            "severity": "red",
            "type": "BTC Crash",
            "message": "BTC dropped %.1f%% in 24h - consider large DCA buy" % btc_change,
        })

    if funding_rate is not None and funding_rate < -0.0001:
        alerts.append({
            "severity": "orange",
            "type": "Negative Funding",
            "message": "BTC funding rate at %.4f%% - shorts paying longs, bullish signal" % (
                funding_rate * 100
            ),
        })

    if mvrv is not None:
        if mvrv < 0.8:
            alerts.append({
                "severity": "red",
                "type": "ETH MVRV Critical",
                "message": "ETH MVRV at %.2f (< 0.8) - historically strong buy zone" % mvrv,
            })
        elif mvrv < 1.0:
            alerts.append({
                "severity": "yellow",
                "type": "ETH MVRV Low",
                "message": "ETH MVRV at %.2f (< 1.0) - undervalued territory" % mvrv,
            })

    return alerts


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Main dashboard page - loads instantly with placeholders, data fills via JS."""
    alert_history = _get_alert_history()

    context = {
        "request": request,
        "btc_price": "...",
        "btc_change_24h": "...",
        "btc_change_raw": None,
        "eth_price": "...",
        "eth_change_24h": "...",
        "eth_change_raw": None,
        "fear_greed_value": None,
        "fear_greed_label": "Loading",
        "funding_rate": "...",
        "funding_rate_raw": None,
        "mvrv": "...",
        "mvrv_raw": None,
        "active_alerts": [],
        "alert_history": alert_history,
        "dca_btc": "8 EUR/week",
        "dca_eth": "2 EUR/week + staking",
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/status")
def api_status():
    """JSON endpoint for current status - fetches all data in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_prices = pool.submit(_fetch_prices)
        f_fg = pool.submit(_fetch_fear_greed)
        f_mvrv = pool.submit(_fetch_eth_mvrv)
        f_funding = pool.submit(_get_latest_funding_rate)

    prices = f_prices.result()
    fg = f_fg.result()
    mvrv = f_mvrv.result()
    funding_rate = f_funding.result()
    alerts = _evaluate_alerts(prices, funding_rate, mvrv)

    return {
        "prices": prices,
        "fear_greed": fg,
        "mvrv": mvrv,
        "funding_rate": funding_rate,
        "alerts": alerts,
    }
