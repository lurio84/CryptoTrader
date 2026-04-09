"""Discord alert system for CryptoTrader."""

import logging
import requests as http_requests

from config.settings import settings

logger = logging.getLogger(__name__)


def format_discord_message(alert_type: str, severity: str, details: dict) -> dict:
    """Format a Discord webhook embed message."""
    colors = {"red": 0xEF4444, "orange": 0xF59E0B, "yellow": 0xEAB308}
    color = colors.get(severity, 0x3B82F6)

    fields = []
    if details.get("btc_price") is not None:
        fields.append({"name": "BTC Price", "value": "${:,.2f}".format(details["btc_price"]), "inline": True})
    if details.get("btc_change") is not None:
        fields.append({"name": "BTC 24h", "value": "{:+.2f}%".format(details["btc_change"]), "inline": True})
    if details.get("eth_price") is not None:
        fields.append({"name": "ETH Price", "value": "${:,.2f}".format(details["eth_price"]), "inline": True})
    if details.get("funding_rate") is not None:
        fields.append({"name": "Funding Rate", "value": "{:.4f}%".format(details["funding_rate"] * 100), "inline": True})
    if details.get("mvrv") is not None:
        fields.append({"name": "ETH MVRV", "value": "{:.3f}".format(details["mvrv"]), "inline": True})

    recommendation = details.get("recommendation", "Review positions")
    fields.append({"name": "Action", "value": recommendation, "inline": False})

    return {
        "embeds": [{
            "title": "ALERT: %s" % alert_type,
            "description": "Severity: **%s**" % severity.upper(),
            "color": color,
            "fields": fields,
            "footer": {"text": "CryptoTrader Advisor"},
        }]
    }


def format_status_message(data: dict) -> dict:
    """Format a status check embed (no alert)."""
    fields = []
    if data.get("btc_price") is not None:
        change = data.get("btc_change", 0)
        fields.append({"name": "BTC", "value": "${:,.0f} ({:+.1f}%)".format(data["btc_price"], change), "inline": True})
    if data.get("eth_price") is not None:
        fields.append({"name": "ETH", "value": "${:,.0f}".format(data["eth_price"]), "inline": True})
    if data.get("fear_greed") is not None:
        fields.append({"name": "Fear & Greed", "value": str(data["fear_greed"]), "inline": True})
    if data.get("funding_rate") is not None:
        fields.append({"name": "Funding", "value": "{:.4f}%".format(data["funding_rate"] * 100), "inline": True})
    if data.get("mvrv") is not None:
        fields.append({"name": "ETH MVRV", "value": "{:.3f}".format(data["mvrv"]), "inline": True})

    return {
        "embeds": [{
            "title": "CryptoTrader Status",
            "description": "All signals within normal ranges. No action needed.",
            "color": 0x22C55E,
            "fields": fields,
            "footer": {"text": "CryptoTrader Advisor"},
        }]
    }


def send_discord_message(payload: dict) -> bool:
    """Send a message via Discord webhook."""
    webhook_url = settings.discord.webhook_url

    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False

    try:
        resp = http_requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Discord message sent successfully")
        return True
    except Exception as e:
        logger.error("Failed to send Discord message: %s", e)
        return False
