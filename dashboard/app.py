"""FastAPI dashboard for CryptoTrader Advisor."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from data.database import init_db, get_session
from data.market_data import fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_fear_greed
from data.models import AlertLog
from alerts.discord_bot import (
    BTC_CRASH_THRESHOLD, FUNDING_RATE_THRESHOLD,
    ETH_MVRV_CRITICAL, ETH_MVRV_LOW,
)
from cli.constants import halving_cycle_info

logger = logging.getLogger(__name__)

app = FastAPI(title="CryptoTrader Advisor")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _get_halving_cycle() -> dict:
    """Return current halving cycle phase info (sourced from cli.constants)."""
    info = halving_cycle_info()
    return {
        "months_elapsed": round(info["months_elapsed"], 1),
        "cycle_pct": info["cycle_pct"],
        "in_risk_zone": info["in_risk_zone"],
        "next_halving_year": info["next_halving_year"],
        "halving_date": info["halving_date_fmt"],
    }


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
    """Evaluate current alert conditions using thresholds from discord_bot."""
    alerts = []

    btc_change = prices.get("btc_change_24h")
    if btc_change is not None and btc_change <= BTC_CRASH_THRESHOLD:
        alerts.append({
            "severity": "red",
            "type": "BTC Crash",
            "message": "BTC dropped %.1f%% in 24h - consider large DCA buy" % btc_change,
        })

    if funding_rate is not None and funding_rate < FUNDING_RATE_THRESHOLD:
        alerts.append({
            "severity": "orange",
            "type": "Negative Funding",
            "message": "BTC funding rate at %.4f%% - shorts paying longs, bullish signal" % (
                funding_rate * 100
            ),
        })

    if mvrv is not None:
        if mvrv < ETH_MVRV_CRITICAL:
            alerts.append({
                "severity": "red",
                "type": "ETH MVRV Critical",
                "message": "ETH MVRV at %.2f (< %.1f) - historically strong buy zone" % (mvrv, ETH_MVRV_CRITICAL),
            })
        elif mvrv < ETH_MVRV_LOW:
            alerts.append({
                "severity": "yellow",
                "type": "ETH MVRV Low",
                "message": "ETH MVRV at %.2f (< %.1f) - undervalued territory" % (mvrv, ETH_MVRV_LOW),
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
        "eth_price": "...",
        "eth_change_24h": "...",
        "fear_greed_value": None,
        "fear_greed_label": "Loading",
        "funding_rate": "...",
        "mvrv": "...",
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

    def _safe_result(future, default):
        try:
            return future.result(timeout=20)
        except Exception as exc:
            logger.error("API fetch failed in /api/status: %s", exc)
            return default

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_prices  = pool.submit(fetch_prices)
        f_fg      = pool.submit(fetch_fear_greed)
        f_eth_mvrv = pool.submit(fetch_mvrv, "eth")
        f_btc_mvrv = pool.submit(fetch_mvrv, "btc")
        f_funding  = pool.submit(fetch_funding_rate)

    _empty_prices = {
        "btc_price": None, "btc_price_eur": None, "btc_change_24h": None,
        "eth_price": None, "eth_price_eur": None, "eth_change_24h": None,
    }
    prices = _safe_result(f_prices, _empty_prices)
    fg = _safe_result(f_fg, {"fear_greed_value": None, "fear_greed_label": "N/A"})
    eth_mvrv = _safe_result(f_eth_mvrv, None)
    btc_mvrv = _safe_result(f_btc_mvrv, None)
    funding_rate = _safe_result(f_funding, None)
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
