"""Discord alert system for CryptoTrader."""

import logging
from datetime import datetime, timezone, timedelta

import requests
from sqlalchemy import select, func

from config.settings import settings
from data.database import init_db, get_session
from data.market_data import fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_sp500_change
from data.models import AlertLog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert thresholds and DCA-out parameters
# Used by check_and_alert(), cmd_check() in main.py, and _evaluate_alerts()
# in dashboard/app.py. Single source of truth for all signal logic.
# ---------------------------------------------------------------------------

BTC_CRASH_THRESHOLD    = -15      # % drop in 24h that triggers crash alert
FUNDING_RATE_THRESHOLD = -0.0001  # -0.01% -- shorts paying longs (bullish)
ETH_MVRV_CRITICAL      = 0.8     # ETH MVRV below this = strong buy (red)
ETH_MVRV_LOW           = 1.0     # ETH MVRV below this = buy zone (yellow)
# BTC MVRV: shown as informational in weekly digest only.
# DISCARDED as buy signal: research7 found delta=-17.2pp at 30d, OOS WR=0% (btc_mvrv_research.py).

# S&P 500 crash: -7% over 5 trading days validated in research6 (N=13, p=0.003 at 4w)
SP500_CRASH_THRESHOLD  = -7      # % drop over 5 trading days

# BTC DCA-out: sell 3% every $20k above $80k
# Backtest: +62pp to +115pp vs hold after IRPF (research4.py, 2026-04)
# Break-even: DCA-out wins if BTC ends cycle below ~$108k
BTC_DCA_OUT_BASE = 80_000
BTC_DCA_OUT_STEP = 20_000
BTC_DCA_OUT_MAX  = 500_000
BTC_DCA_OUT_PCT  = 3

# ETH DCA-out: sell 3% every $1k above $3k (research4 analisis 4, 2026-04)
ETH_DCA_OUT_BASE = 3_000
ETH_DCA_OUT_STEP = 1_000
ETH_DCA_OUT_MAX  = 50_000
ETH_DCA_OUT_PCT  = 3

# Cooldown hours per alert type (deduplication window)
COOLDOWN_BTC_CRASH  = 6
COOLDOWN_FUNDING    = 24
COOLDOWN_MVRV       = 168   # 7 days
COOLDOWN_SP500      = 168   # 7 days
COOLDOWN_DCA_OUT    = 720   # 30 days

# Dead canary: alert if no successful check in this many hours
CANARY_THRESHOLD_HOURS = 10
COOLDOWN_DEAD_CANARY   = 6


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _format_embed(alert_type: str, severity: str, details: dict) -> dict:
    """Format a Discord webhook embed for an alert."""
    colors = {"red": 0xEF4444, "orange": 0xF59E0B, "yellow": 0xEAB308}
    color = colors.get(severity, 0x3B82F6)

    fields = []
    if details.get("btc_price") is not None:
        btc_eur = details.get("btc_price_eur")
        btc_val = "${:,.0f}".format(details["btc_price"])
        if btc_eur:
            btc_val += " / {:,.0f} EUR".format(btc_eur)
        fields.append({"name": "BTC Price", "value": btc_val, "inline": True})
    if details.get("btc_change") is not None:
        fields.append({"name": "BTC 24h", "value": "{:+.2f}%".format(details["btc_change"]), "inline": True})
    if details.get("eth_price") is not None:
        eth_eur = details.get("eth_price_eur")
        eth_val = "${:,.0f}".format(details["eth_price"])
        if eth_eur:
            eth_val += " / {:,.0f} EUR".format(eth_eur)
        fields.append({"name": "ETH Price", "value": eth_val, "inline": True})
    if details.get("funding_rate") is not None:
        fields.append({"name": "Funding Rate", "value": "{:.4f}%".format(details["funding_rate"] * 100), "inline": True})
    if details.get("mvrv") is not None:
        fields.append({"name": "ETH MVRV", "value": "{:.3f}".format(details["mvrv"]), "inline": True})
    if details.get("btc_mvrv") is not None:
        fields.append({"name": "BTC MVRV", "value": "{:.3f}".format(details["btc_mvrv"]), "inline": True})
    if details.get("sp500_change") is not None:
        fields.append({"name": "S&P500 5d", "value": "{:+.2f}%".format(details["sp500_change"]), "inline": True})

    fields.append({"name": "Accion", "value": details.get("recommendation", "Review positions"), "inline": False})

    return {
        "embeds": [{
            "title": "ALERT: %s" % alert_type,
            "description": "Severity: **%s**" % severity.upper(),
            "color": color,
            "fields": fields,
            "footer": {"text": "CryptoTrader Advisor"},
        }]
    }


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_discord_message(payload: dict) -> bool:
    """Send a message via Discord webhook."""
    webhook_url = settings.discord.webhook_url
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Set DISCORD_WEBHOOK_URL in .env")
        return False
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Discord message sent successfully")
        return True
    except Exception as e:
        logger.error("Failed to send Discord message: %s", e)
        return False


# ---------------------------------------------------------------------------
# Alert deduplication
# ---------------------------------------------------------------------------

def _already_alerted(session, alert_type: str, hours: int = 24) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(tzinfo=None)
    row = session.execute(
        select(AlertLog)
        .where(AlertLog.alert_type == alert_type, AlertLog.timestamp >= cutoff)
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


def _log_alert(session, alert_type, severity, btc_price, eth_price, metric_value, notified):
    entry = AlertLog(
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        alert_type=alert_type,
        severity=severity,
        message=alert_type,
        btc_price=btc_price,
        eth_price=eth_price,
        metric_value=metric_value,
        notified=1 if notified else 0,
    )
    session.add(entry)


# ---------------------------------------------------------------------------
# DCA-out helper (BTC and ETH share the same loop structure)
# ---------------------------------------------------------------------------

def _check_dca_out(
    session,
    asset: str,
    price: float | None,
    prices: dict,
    btc_price: float | None,
    eth_price: float | None,
    dca_base: int,
    dca_step: int,
    dca_max: int,
    extra_details: dict,
    recommendation_fn,
    triggered: list,
) -> None:
    """Check DCA-out levels for a given asset and append triggered alerts."""
    if price is None:
        return
    level = dca_base
    level_num = 1
    while level <= dca_max:
        if price >= level:
            alert_type = "{}_dca_out_{:d}k".format(asset, level // 1000)
            if not _already_alerted(session, alert_type, hours=COOLDOWN_DCA_OUT):
                price_eur = prices.get("{}_price_eur".format(asset)) or 0
                details = {
                    "btc_price": btc_price,
                    "btc_price_eur": prices.get("btc_price_eur"),
                    "eth_price": eth_price,
                    "eth_price_eur": prices.get("eth_price_eur"),
                    "recommendation": recommendation_fn(level_num, level, price_eur),
                    **extra_details,
                }
                sent = send_discord_message(
                    _format_embed(
                        "{} DCA-out nivel {:d} (${:,.0f})".format(asset.upper(), level_num, level),
                        "orange",
                        details,
                    )
                )
                _log_alert(session, alert_type, "orange", btc_price, eth_price, float(level), sent)
                triggered.append({"type": alert_type, "severity": "orange", "sent": sent})
        level += dca_step
        level_num += 1


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def check_and_alert() -> list[dict]:
    """
    Check all signal thresholds and send Discord alerts if triggered.
    Returns list of triggered alerts.
    """
    init_db()

    prices = fetch_prices()
    funding_rate = fetch_funding_rate()
    eth_mvrv = fetch_mvrv("eth")
    sp500_change = fetch_sp500_change()

    btc_price = prices.get("btc_price")
    btc_change = prices.get("btc_change_24h")
    eth_price = prices.get("eth_price")

    triggered = []

    with get_session() as session:
        # Dead canary: detect if previous checks stopped running silently
        last_hb = session.query(func.max(AlertLog.timestamp)).filter(
            AlertLog.alert_type == "heartbeat"
        ).scalar()
        if last_hb is not None:
            gap_h = (datetime.utcnow() - last_hb).total_seconds() / 3600
            if gap_h > CANARY_THRESHOLD_HOURS:
                if not _already_alerted(session, "dead_canary", COOLDOWN_DEAD_CANARY):
                    sent = send_discord_message(_format_embed(
                        "Dead Canary -- Sistema sin checks",
                        "red",
                        {"recommendation": "Ultimo check hace {:.1f}h (umbral: {}h). Verificar GitHub Actions y APIs.".format(gap_h, CANARY_THRESHOLD_HOURS)},
                    ))
                    _log_alert(session, "dead_canary", "red", btc_price, eth_price, gap_h, sent)
                    triggered.append({"type": "dead_canary", "severity": "red", "sent": sent})

        # Signal 1: BTC crash > 15% in 24h
        if btc_change is not None and btc_change <= BTC_CRASH_THRESHOLD:
            alert_type = "btc_crash"
            if not _already_alerted(session, alert_type, hours=COOLDOWN_BTC_CRASH):
                details = {
                    "btc_price": btc_price, "btc_change": btc_change, "eth_price": eth_price,
                    "recommendation": "Buy extra 100-150 EUR of BTC in Trade Republic. Crashes of this magnitude recover within 3-6 months.",
                }
                sent = send_discord_message(_format_embed("BTC Crash (>15% drop in 24h)", "red", details))
                _log_alert(session, alert_type, "red", btc_price, eth_price, btc_change, sent)
                triggered.append({"type": alert_type, "severity": "red", "sent": sent})

        # Signal 2: BTC funding rate < -0.01%
        if funding_rate is not None and funding_rate < FUNDING_RATE_THRESHOLD:
            alert_type = "funding_negative"
            if not _already_alerted(session, alert_type, hours=COOLDOWN_FUNDING):
                details = {
                    "btc_price": btc_price, "funding_rate": funding_rate, "eth_price": eth_price,
                    "recommendation": "Shorts paying longs (88% win rate historically). Buy extra 100 EUR of BTC.",
                }
                sent = send_discord_message(_format_embed("Negative BTC Funding Rate", "orange", details))
                _log_alert(session, alert_type, "orange", btc_price, eth_price, funding_rate, sent)
                triggered.append({"type": alert_type, "severity": "orange", "sent": sent})

        # Signal 3: ETH MVRV
        if eth_mvrv is not None:
            if eth_mvrv < ETH_MVRV_CRITICAL:
                alert_type = "mvrv_critical"
                if not _already_alerted(session, alert_type, hours=COOLDOWN_MVRV):
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": eth_mvrv,
                        "recommendation": "ETH muy infravalorado (61% win rate, +10.1% avg a 30d, re-validado 2018-2026). Aumenta el Sparplan de ETH lo que puedas permitirte este mes, luego resetea a 2 EUR (0 fees).",
                    }
                    sent = send_discord_message(_format_embed("ETH MVRV Critical (< 0.8)", "red", details))
                    _log_alert(session, alert_type, "red", btc_price, eth_price, eth_mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "red", "sent": sent})
            elif eth_mvrv < ETH_MVRV_LOW:
                alert_type = "mvrv_low"
                if not _already_alerted(session, alert_type, hours=COOLDOWN_MVRV):
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": eth_mvrv,
                        "recommendation": "ETH en zona infravalorada (54% win rate, +6.3% avg a 30d, re-validado 2018-2026). Considera aumentar el Sparplan de ETH lo que puedas permitirte este mes, luego resetea a 2 EUR (0 fees).",
                    }
                    sent = send_discord_message(_format_embed("ETH MVRV Low (< 1.0)", "yellow", details))
                    _log_alert(session, alert_type, "yellow", btc_price, eth_price, eth_mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "yellow", "sent": sent})

        # Signal 4: S&P 500 crash -- buy BTC/ETF during broad market panic
        # Validated in research6: -5% over 5 trading days, N=31, consistent edge
        if sp500_change is not None and sp500_change <= SP500_CRASH_THRESHOLD:
            alert_type = "sp500_crash"
            if not _already_alerted(session, alert_type, hours=COOLDOWN_SP500):
                details = {
                    "btc_price": btc_price, "btc_price_eur": prices.get("btc_price_eur"),
                    "eth_price": eth_price, "sp500_change": sp500_change,
                    "recommendation": (
                        "S&P500 cayo {:.1f}% en 5 dias. Panico macro validado como oportunidad DCA "
                        "(research6, N=31). Considera compra extra de 50-100 EUR en BTC y/o SP500 ETF.".format(sp500_change)
                    ),
                }
                sent = send_discord_message(_format_embed("S&P500 Crash ({:.1f}% en 5d)".format(sp500_change), "orange", details))
                _log_alert(session, alert_type, "orange", btc_price, eth_price, sp500_change, sent)
                triggered.append({"type": alert_type, "severity": "orange", "sent": sent})

        # Signals 6+: BTC DCA-out -- vender BTC_DCA_OUT_PCT% cada BTC_DCA_OUT_STEP por encima de BTC_DCA_OUT_BASE
        _check_dca_out(
            session, "btc", btc_price, prices, btc_price, eth_price,
            BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP, BTC_DCA_OUT_MAX,
            extra_details={"btc_change": btc_change},
            recommendation_fn=lambda n, lvl, eur: (
                "DCA-out nivel {:d} (${:,.0f}): vende el {}% de tus BTC en Trade Republic. "
                "Orden de mercado o limite a {:,.0f} EUR. "
                "Estrategia: -{}% por cada ${}k subida. "
                "No vendas mas de este porcentaje -- el resto sigue en DCA.".format(
                    n, lvl, BTC_DCA_OUT_PCT, eur, BTC_DCA_OUT_PCT, BTC_DCA_OUT_STEP // 1000,
                )
            ),
            triggered=triggered,
        )

        # Signals 7+: ETH DCA-out -- vender ETH_DCA_OUT_PCT% cada ETH_DCA_OUT_STEP por encima de ETH_DCA_OUT_BASE
        _check_dca_out(
            session, "eth", eth_price, prices, btc_price, eth_price,
            ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP, ETH_DCA_OUT_MAX,
            extra_details={"mvrv": eth_mvrv},
            recommendation_fn=lambda n, lvl, eur: (
                "DCA-out nivel {:d} (${:,.0f}): vende el {}% de tu ETH en Trade Republic. "
                "Precio aprox: {:,.0f} EUR. "
                "NOTA: confirma que el ETH stakeado se puede vender directamente en TR.".format(
                    n, lvl, ETH_DCA_OUT_PCT, eur,
                )
            ),
            triggered=triggered,
        )

        # Heartbeat: record successful run for dead canary detection
        _log_alert(session, "heartbeat", "green", btc_price, eth_price, float(len(triggered)), True)

    if not triggered:
        logger.info("No alerts triggered. All metrics within normal ranges.")

    return triggered

# Weekly digest lives in alerts/digest.py (extracted to keep this module focused on alert logic).
# Import with: from alerts.digest import send_weekly_digest
