"""Telegram alert system for CryptoTrader."""

import logging
from datetime import datetime, timezone, timedelta

import ccxt
import requests
from sqlalchemy import select

from config.settings import settings
from data.database import init_db, get_session
from data.models import SentimentData, AlertLog

logger = logging.getLogger(__name__)


def fetch_btc_data() -> dict:
    """Fetch current BTC price and 24h change."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker("BTC/USDT")
        return {
            "price": ticker.get("last", 0),
            "change_24h": ticker.get("percentage", 0),
        }
    except Exception as e:
        logger.error("Failed to fetch BTC data: %s", e)
        return {"price": None, "change_24h": None}


def fetch_eth_price() -> float | None:
    """Fetch current ETH price."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker("ETH/USDT")
        return ticker.get("last")
    except Exception as e:
        logger.error("Failed to fetch ETH price: %s", e)
        return None


def fetch_funding_rate() -> float | None:
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


def fetch_eth_mvrv() -> float | None:
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


def _already_alerted(session, alert_type: str, hours: int = 24) -> bool:
    """Check if we already sent this alert type recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    # SQLite stores naive datetimes, so compare without tz
    cutoff_naive = cutoff.replace(tzinfo=None)
    row = session.execute(
        select(AlertLog)
        .where(
            AlertLog.alert_type == alert_type,
            AlertLog.timestamp >= cutoff_naive,
        )
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


def _log_alert(
    session,
    alert_type: str,
    severity: str,
    message: str,
    btc_price: float | None,
    eth_price: float | None,
    metric_value: float | None,
    notified: bool,
) -> AlertLog:
    """Log an alert to the database."""
    entry = AlertLog(
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        alert_type=alert_type,
        severity=severity,
        message=message,
        btc_price=btc_price,
        eth_price=eth_price,
        metric_value=metric_value,
        notified=1 if notified else 0,
    )
    session.add(entry)
    return entry


def _format_telegram_message(alert_type: str, severity: str, details: dict) -> str:
    """Format a plain text Telegram message."""
    lines = []
    lines.append("=== CRYPTOTRADER ALERT ===")
    lines.append("")
    lines.append("Signal: %s" % alert_type)
    lines.append("Severity: %s" % severity.upper())
    lines.append("")

    if details.get("btc_price") is not None:
        lines.append("BTC Price: ${:,.2f}".format(details["btc_price"]))
    if details.get("btc_change") is not None:
        lines.append("BTC 24h Change: {:.2f}%".format(details["btc_change"]))
    if details.get("eth_price") is not None:
        lines.append("ETH Price: ${:,.2f}".format(details["eth_price"]))
    if details.get("funding_rate") is not None:
        lines.append("BTC Funding Rate: {:.4f}%".format(details["funding_rate"] * 100))
    if details.get("mvrv") is not None:
        lines.append("ETH MVRV: {:.2f}".format(details["mvrv"]))

    lines.append("")
    lines.append("Recommendation: %s" % details.get("recommendation", "Review positions"))
    lines.append("")
    lines.append("---")
    lines.append("CryptoTrader Advisor")
    return "\n".join(lines)


def send_telegram_message(text: str) -> bool:
    """Send a message via Telegram bot API."""
    token = settings.telegram.bot_token
    chat_id = settings.telegram.chat_id

    if not token or not chat_id:
        logger.warning("Telegram credentials not configured. Skipping notification.")
        return False

    try:
        url = "https://api.telegram.org/bot%s/sendMessage" % token
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram message sent successfully")
        return True
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False


def _send_notification(alert_type: str, severity: str, details: dict) -> bool:
    """Send notification via Discord (primary) or Telegram (fallback)."""
    from alerts.discord_bot import format_discord_message, send_discord_message

    # Try Discord first
    if settings.discord.webhook_url:
        payload = format_discord_message(alert_type, severity, details)
        if send_discord_message(payload):
            return True

    # Fallback to Telegram
    msg = _format_telegram_message(alert_type, severity, details)
    return send_telegram_message(msg)


def check_and_alert() -> list[dict]:
    """
    Check all signal thresholds and send alerts if triggered.

    Returns list of triggered alerts.
    """
    init_db()

    btc_data = fetch_btc_data()
    eth_price = fetch_eth_price()
    funding_rate = fetch_funding_rate()
    mvrv = fetch_eth_mvrv()

    btc_price = btc_data.get("price")
    btc_change = btc_data.get("change_24h")

    triggered = []

    with get_session() as session:
        # Check 1: BTC crash > 15% in 24h
        if btc_change is not None and btc_change <= -15:
            alert_type = "btc_crash"
            if not _already_alerted(session, alert_type, hours=6):
                details = {
                    "btc_price": btc_price, "btc_change": btc_change, "eth_price": eth_price,
                    "recommendation": "Buy extra 100-150 EUR of BTC in Trade Republic. Historical crashes of this magnitude recover within 3-6 months.",
                }
                sent = _send_notification("BTC Crash (>15% drop in 24h)", "red", details)
                msg = _format_telegram_message("BTC Crash", "red", details)
                _log_alert(session, alert_type, "red", msg, btc_price, eth_price, btc_change, sent)
                triggered.append({"type": alert_type, "severity": "red"})

        # Check 2: BTC funding rate < -0.01%
        if funding_rate is not None and funding_rate < -0.0001:
            alert_type = "funding_negative"
            if not _already_alerted(session, alert_type, hours=24):
                details = {
                    "btc_price": btc_price, "funding_rate": funding_rate, "eth_price": eth_price,
                    "recommendation": "Shorts are paying longs (88% win rate historically). Consider buying extra 100 EUR of BTC.",
                }
                sent = _send_notification("Negative BTC Funding Rate", "orange", details)
                msg = _format_telegram_message("Negative Funding", "orange", details)
                _log_alert(session, alert_type, "orange", msg, btc_price, eth_price, funding_rate, sent)
                triggered.append({"type": alert_type, "severity": "orange"})

        # Check 3: ETH MVRV thresholds
        if mvrv is not None:
            if mvrv < 0.8:
                alert_type = "mvrv_critical"
                if not _already_alerted(session, alert_type, hours=24):
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": mvrv,
                        "recommendation": "ETH deeply undervalued (89% win rate, +34% avg at 30d). Buy extra 100 EUR of ETH in Trade Republic.",
                    }
                    sent = _send_notification("ETH MVRV Critical (< 0.8)", "red", details)
                    msg = _format_telegram_message("ETH MVRV Critical", "red", details)
                    _log_alert(session, alert_type, "red", msg, btc_price, eth_price, mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "red"})
            elif mvrv < 1.0:
                alert_type = "mvrv_low"
                if not _already_alerted(session, alert_type, hours=24):
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": mvrv,
                        "recommendation": "ETH undervalued territory. Consider increasing ETH Sparplan temporarily.",
                    }
                    sent = _send_notification("ETH MVRV Low (< 1.0)", "yellow", details)
                    msg = _format_telegram_message("ETH MVRV Low", "yellow", details)
                    _log_alert(session, alert_type, "yellow", msg, btc_price, eth_price, mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "yellow"})

    if not triggered:
        logger.info("No alerts triggered. All metrics within normal ranges.")

    return triggered
