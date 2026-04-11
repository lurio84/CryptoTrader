"""FastAPI dashboard for CryptoTrader Advisor."""

import logging
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

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
    """Fetch current BTC and ETH prices from CoinGecko (USD + EUR + 24h change)."""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin,ethereum",
                "vs_currencies": "usd,eur",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "btc_price": data["bitcoin"]["usd"],
            "btc_price_eur": data["bitcoin"]["eur"],
            "btc_change_24h": data["bitcoin"]["usd_24h_change"],
            "eth_price": data["ethereum"]["usd"],
            "eth_price_eur": data["ethereum"]["eur"],
            "eth_change_24h": data["ethereum"]["usd_24h_change"],
        }
    except Exception as e:
        logger.error("Failed to fetch prices from CoinGecko: %s", e)
        return {
            "btc_price": None,
            "btc_price_eur": None,
            "btc_change_24h": None,
            "eth_price": None,
            "eth_price_eur": None,
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


def _fetch_btc_mvrv() -> float | None:
    """Fetch BTC MVRV from CoinMetrics community API (informativo, no es senal de venta)."""
    try:
        resp = requests.get(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={
                "assets": "btc",
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
        logger.error("Failed to fetch BTC MVRV: %s", e)
        return None


_LAST_HALVING = date(2024, 4, 19)
_CYCLE_DAYS = 48 * 30.44   # ~4 anios en dias
# Research3: fase mas debil meses 18-24 post-halving (30d=-7.2% vs baseline)
# Halving abril 2024 -> riesgo: octubre 2025 - abril 2026
_RISK_ZONE_START_MONTHS = 18
_RISK_ZONE_END_MONTHS = 24


def _get_halving_cycle() -> dict:
    """Return current halving cycle phase info."""
    today = date.today()
    days_elapsed = (today - _LAST_HALVING).days
    months_elapsed = days_elapsed / 30.44
    cycle_pct = min(days_elapsed / _CYCLE_DAYS * 100, 100)
    in_risk_zone = _RISK_ZONE_START_MONTHS <= months_elapsed < _RISK_ZONE_END_MONTHS
    next_halving_year = 2028
    return {
        "months_elapsed": round(months_elapsed, 1),
        "cycle_pct": round(cycle_pct, 1),
        "in_risk_zone": in_risk_zone,
        "next_halving_year": next_halving_year,
        "halving_date": _LAST_HALVING.strftime("%b %Y"),
    }


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

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_prices = pool.submit(_fetch_prices)
        f_fg = pool.submit(_fetch_fear_greed)
        f_eth_mvrv = pool.submit(_fetch_eth_mvrv)
        f_btc_mvrv = pool.submit(_fetch_btc_mvrv)
        f_funding = pool.submit(_get_latest_funding_rate)

    prices = f_prices.result()
    fg = f_fg.result()
    eth_mvrv = f_eth_mvrv.result()
    btc_mvrv = f_btc_mvrv.result()
    funding_rate = f_funding.result()
    halving = _get_halving_cycle()
    alerts = _evaluate_alerts(prices, funding_rate, eth_mvrv)

    return {
        "prices": prices,
        "fear_greed": fg,
        "eth_mvrv": eth_mvrv,
        "btc_mvrv": btc_mvrv,
        "funding_rate": funding_rate,
        "halving": halving,
        "alerts": alerts,
    }
