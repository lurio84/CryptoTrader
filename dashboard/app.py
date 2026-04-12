"""FastAPI dashboard for CryptoTrader Advisor."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from data.database import init_db, get_session
from data.market_data import fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_fear_greed
from data.models import AlertLog, UserPortfolioSnapshot
from alerts.discord_bot import (
    BTC_CRASH_THRESHOLD, FUNDING_RATE_THRESHOLD,
    ETH_MVRV_CRITICAL, ETH_MVRV_LOW,
)
from cli.constants import halving_cycle_info

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CryptoTrader Advisor", lifespan=lifespan)
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


def _alert_row_to_dict(r: AlertLog) -> dict:
    return {
        "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else "",
        "alert_type": r.alert_type,
        "severity": r.severity,
        "message": r.message,
        "btc_price": r.btc_price,
        "eth_price": r.eth_price,
        "metric_value": r.metric_value,
        "notified": bool(r.notified),
    }


def _get_alert_history(limit: int = 20) -> list[dict]:
    """Get recent alert history from DB, excluding heartbeats."""
    try:
        with get_session() as session:
            rows = session.execute(
                select(AlertLog)
                .where(AlertLog.alert_type != "heartbeat")
                .order_by(AlertLog.timestamp.desc())
                .limit(limit)
            ).scalars().all()
            return [_alert_row_to_dict(r) for r in rows]
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


@app.get("/api/snapshots")
def api_snapshots():
    """Portfolio weekly snapshots for historical chart."""
    import json
    try:
        with get_session() as session:
            rows = session.query(UserPortfolioSnapshot).order_by(
                UserPortfolioSnapshot.snapshot_date
            ).all()
            return [
                {"date": r.snapshot_date, **json.loads(r.data_json)}
                for r in rows
            ]
    except Exception as exc:
        logger.error("Failed to fetch portfolio snapshots: %s", exc)
        return []


@app.get("/api/alerts")
def api_alerts(
    days: int = 30,
    include_heartbeats: int = 0,
    alert_type: str | None = None,
    severity: str | None = None,
):
    """Alert log history. Excludes heartbeats by default (?include_heartbeats=1 to include).

    Optional filters: alert_type (exact match), severity (red/orange/yellow/green).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with get_session() as session:
            q = select(AlertLog).where(AlertLog.timestamp >= cutoff)
            if not include_heartbeats:
                q = q.where(AlertLog.alert_type != "heartbeat")
            if alert_type:
                q = q.where(AlertLog.alert_type == alert_type)
            if severity:
                q = q.where(AlertLog.severity == severity)
            rows = session.execute(
                q.order_by(AlertLog.timestamp.desc())
            ).scalars().all()
            return [_alert_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to fetch alert log: %s", exc)
        return []


@app.get("/api/drift")
def api_drift():
    """Current allocation vs Sparplan targets for each asset.

    Returns list of {asset, target_pct, actual_pct, drift_pp, value_eur, status}.
    Used by the dashboard to render live allocation bars.
    """
    from cli.constants import SPARPLAN_TARGETS, DRIFT_THRESHOLD, DRIFT_WATCH_THRESHOLD
    from data.market_data import fetch_portfolio_prices_eur
    from data.models import UserTrade

    try:
        prices = fetch_portfolio_prices_eur(include_etfs=True)
    except Exception as exc:
        logger.warning("drift: price fetch failed: %s", exc)
        prices = {"btc_eur": None, "eth_eur": None, "etf_prices": {}}

    with get_session() as session:
        rows = session.query(UserTrade).all()
        trades = [t.to_dict() for t in rows]

    if not trades:
        return []

    units_held: dict[str, float] = {}
    for t in trades:
        if t["side"] == "buy":
            units_held[t["asset"]] = units_held.get(t["asset"], 0.0) + t["units"]
        elif t["side"] == "sell":
            units_held[t["asset"]] = units_held.get(t["asset"], 0.0) - t["units"]

    asset_prices_eur = {
        "BTC": prices["btc_eur"] or 0.0,
        "ETH": prices["eth_eur"] or 0.0,
        "SP500": prices["etf_prices"].get("SP500") or 0.0,
        "SEMICONDUCTORS": prices["etf_prices"].get("SEMICONDUCTORS") or 0.0,
        "REALTY_INCOME": prices["etf_prices"].get("REALTY_INCOME") or 0.0,
        "URANIUM": prices["etf_prices"].get("URANIUM") or 0.0,
    }
    values = {
        a: units_held.get(a, 0.0) * asset_prices_eur.get(a, 0.0)
        for a in SPARPLAN_TARGETS
    }
    total = sum(values.values())
    if total <= 0:
        return []

    result = []
    for asset, target_pct in SPARPLAN_TARGETS.items():
        val = values[asset]
        actual_pct = val / total * 100
        drift = actual_pct - target_pct
        if abs(drift) > DRIFT_THRESHOLD:
            status = "rebalance"
        elif abs(drift) > DRIFT_WATCH_THRESHOLD:
            status = "watch"
        else:
            status = "ok"
        result.append({
            "asset": asset,
            "target_pct": round(target_pct, 2),
            "actual_pct": round(actual_pct, 2),
            "drift_pp": round(drift, 2),
            "value_eur": round(val, 2),
            "status": status,
        })
    return result


@app.get("/api/portfolio_pnl")
def api_portfolio_pnl():
    """Per-asset unrealized + realized P&L summary."""
    from data.market_data import fetch_portfolio_prices_eur
    from data.models import UserTrade
    from data.portfolio import calculate_portfolio_status
    from alerts.discord_bot import (
        BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP,
        ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP,
    )

    try:
        prices = fetch_portfolio_prices_eur(include_etfs=True)
    except Exception as exc:
        logger.warning("portfolio_pnl: price fetch failed: %s", exc)
        prices = {"btc_eur": None, "eth_eur": None, "etf_prices": {}}

    with get_session() as session:
        rows = session.query(UserTrade).all()
        trades = [t.to_dict() for t in rows]

    if not trades:
        return {"assets": [], "totals": {"invested": 0, "value": 0, "pnl": 0}}

    by_asset: dict[str, list[dict]] = {}
    for t in trades:
        by_asset.setdefault(t["asset"], []).append(t)

    results = []
    total_invested = 0.0
    total_value = 0.0
    total_pnl = 0.0

    crypto_map = {
        "BTC": (prices["btc_eur"], BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP),
        "ETH": (prices["eth_eur"], ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP),
    }
    for asset, asset_trades in by_asset.items():
        if asset in crypto_map:
            price_eur, dca_base, dca_step = crypto_map[asset]
            if not price_eur:
                continue
            s = calculate_portfolio_status(asset, asset_trades, price_eur, dca_base, dca_step)
            invested = s["total_invested_eur"]
            value = s["current_value_eur"]
            unrealized = s["unrealized_gain_eur"]
            realized = s["realized_gain_eur"]
            pnl = unrealized + realized
        else:
            # ETF: simple sum
            price_eur = prices["etf_prices"].get(asset)
            if not price_eur:
                continue
            units = (
                sum(t["units"] for t in asset_trades if t["side"] == "buy")
                - sum(t["units"] for t in asset_trades if t["side"] == "sell")
            )
            invested = sum(
                t["units"] * t["price_eur"] + t["fee_eur"]
                for t in asset_trades if t["side"] == "buy"
            )
            value = units * price_eur
            unrealized = value - invested
            realized = 0.0
            pnl = unrealized

        total_invested += invested
        total_value += value
        total_pnl += pnl

        results.append({
            "asset": asset,
            "units": round(sum(t["units"] for t in asset_trades if t["side"] == "buy")
                           - sum(t["units"] for t in asset_trades if t["side"] == "sell"), 6),
            "price_eur": round(price_eur or 0.0, 2),
            "invested_eur": round(invested, 2),
            "value_eur": round(value, 2),
            "unrealized_eur": round(unrealized, 2),
            "realized_eur": round(realized, 2),
            "pnl_eur": round(pnl, 2),
        })

    results.sort(key=lambda r: r["value_eur"], reverse=True)
    return {
        "assets": results,
        "totals": {
            "invested": round(total_invested, 2),
            "value": round(total_value, 2),
            "pnl": round(total_pnl, 2),
        },
    }
