"""Discord alert system for CryptoTrader."""

import logging
from datetime import datetime, timezone, timedelta

import requests
from sqlalchemy import select

from config.settings import settings
from data.database import init_db, get_session
from data.models import AlertLog

logger = logging.getLogger(__name__)


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


def _format_status_embed(data: dict) -> dict:
    """Format a status check embed (no alert triggered)."""
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
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_prices() -> dict:
    """Fetch BTC and ETH prices (USD + EUR) from CoinGecko."""
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
            "btc_change": data["bitcoin"]["usd_24h_change"],
            "eth_price": data["ethereum"]["usd"],
            "eth_price_eur": data["ethereum"]["eur"],
        }
    except Exception as e:
        logger.error("Failed to fetch prices from CoinGecko: %s", e)
        return {
            "btc_price": None, "btc_price_eur": None,
            "btc_change": None,
            "eth_price": None, "eth_price_eur": None,
        }


def _fetch_funding_rate() -> float | None:
    """Fetch current BTC funding rate from OKX (no geo-restrictions from GitHub)."""
    try:
        resp = requests.get(
            "https://www.okx.com/api/v5/public/funding-rate",
            params={"instId": "BTC-USDT-SWAP"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return float(data[0]["fundingRate"])
        return None
    except Exception as e:
        logger.error("Failed to fetch funding rate: %s", e)
        return None


def _fetch_eth_mvrv() -> float | None:
    try:
        resp = requests.get(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={"assets": "eth", "metrics": "CapMVRVCur", "frequency": "1d", "page_size": "1", "paging_from": "end"},
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
    """Fetch BTC MVRV from CoinMetrics (informativo, no es senial de venta)."""
    try:
        resp = requests.get(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={"assets": "btc", "metrics": "CapMVRVCur", "frequency": "1d", "page_size": "1", "paging_from": "end"},
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
# Main check
# ---------------------------------------------------------------------------

def check_and_alert() -> list[dict]:
    """
    Check all signal thresholds and send Discord alerts if triggered.
    Returns list of triggered alerts.
    """
    init_db()

    prices = _fetch_prices()
    funding_rate = _fetch_funding_rate()
    mvrv = _fetch_eth_mvrv()

    btc_price = prices.get("btc_price")
    btc_change = prices.get("btc_change")
    eth_price = prices.get("eth_price")

    triggered = []

    with get_session() as session:
        # Signal 1: BTC crash > 15% in 24h
        if btc_change is not None and btc_change <= -15:
            alert_type = "btc_crash"
            if not _already_alerted(session, alert_type, hours=6):
                details = {
                    "btc_price": btc_price, "btc_change": btc_change, "eth_price": eth_price,
                    "recommendation": "Buy extra 100-150 EUR of BTC in Trade Republic. Crashes of this magnitude recover within 3-6 months.",
                }
                sent = send_discord_message(_format_embed("BTC Crash (>15% drop in 24h)", "red", details))
                _log_alert(session, alert_type, "red", btc_price, eth_price, btc_change, sent)
                triggered.append({"type": alert_type, "severity": "red", "sent": sent})

        # Signal 2: BTC funding rate < -0.01%
        if funding_rate is not None and funding_rate < -0.0001:
            alert_type = "funding_negative"
            if not _already_alerted(session, alert_type, hours=24):
                details = {
                    "btc_price": btc_price, "funding_rate": funding_rate, "eth_price": eth_price,
                    "recommendation": "Shorts paying longs (88% win rate historically). Buy extra 100 EUR of BTC.",
                }
                sent = send_discord_message(_format_embed("Negative BTC Funding Rate", "orange", details))
                _log_alert(session, alert_type, "orange", btc_price, eth_price, funding_rate, sent)
                triggered.append({"type": alert_type, "severity": "orange", "sent": sent})

        # Signal 3: ETH MVRV
        if mvrv is not None:
            if mvrv < 0.8:
                alert_type = "mvrv_critical"
                if not _already_alerted(session, alert_type, hours=168):  # 7 dias
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": mvrv,
                        "recommendation": "ETH muy infravalorado (61% win rate, +10.1% avg a 30d, re-validado 2018-2026). Aumenta el Sparplan de ETH lo que puedas permitirte este mes, luego resetea a 2 EUR (0 fees).",
                    }
                    sent = send_discord_message(_format_embed("ETH MVRV Critical (< 0.8)", "red", details))
                    _log_alert(session, alert_type, "red", btc_price, eth_price, mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "red", "sent": sent})
            elif mvrv < 1.0:
                alert_type = "mvrv_low"
                if not _already_alerted(session, alert_type, hours=168):  # 7 dias
                    details = {
                        "btc_price": btc_price, "eth_price": eth_price, "mvrv": mvrv,
                        "recommendation": "ETH en zona infravalorada (54% win rate, +6.3% avg a 30d, re-validado 2018-2026). Considera aumentar el Sparplan de ETH lo que puedas permitirte este mes, luego resetea a 2 EUR (0 fees).",
                    }
                    sent = send_discord_message(_format_embed("ETH MVRV Low (< 1.0)", "yellow", details))
                    _log_alert(session, alert_type, "yellow", btc_price, eth_price, mvrv, sent)
                    triggered.append({"type": alert_type, "severity": "yellow", "sent": sent})

        # Signals 4+: BTC DCA-out -- vender 3% cada $20k por encima de $80k
        # Cada nivel tiene su propia deduplicacion de 30 dias (cooldown independiente).
        # Backtest: +62pp a +115pp vs hold despues de impuestos IRPF (research4.py).
        # Break-even: DCA-out gana si BTC termina el ciclo por debajo de ~$108k.
        if btc_price is not None:
            BTC_DCA_OUT_BASE  = 80_000   # primer nivel a partir del cual empezar
            BTC_DCA_OUT_STEP  = 20_000   # escalon entre niveles
            BTC_DCA_OUT_MAX   = 500_000  # limite superior (no se esperan alertas reales tan altas)
            BTC_DCA_OUT_PCT   = 3        # % de holdings a vender por nivel

            level = BTC_DCA_OUT_BASE
            level_num = 1
            while level <= BTC_DCA_OUT_MAX:
                if btc_price >= level:
                    alert_type = "btc_dca_out_{:d}k".format(level // 1000)
                    if not _already_alerted(session, alert_type, hours=720):  # 30 dias
                        details = {
                            "btc_price": btc_price,
                            "btc_price_eur": prices.get("btc_price_eur"),
                            "btc_change": btc_change,
                            "eth_price": eth_price,
                            "eth_price_eur": prices.get("eth_price_eur"),
                            "recommendation": (
                                "DCA-out nivel {:d} (${:,.0f}): vende el {}% de tus BTC en Trade Republic. "
                                "Orden de mercado o limite a {:,.0f} EUR. "
                                "Estrategia: -3% por cada ${}k subida. "
                                "No vendas mas de este porcentaje -- el resto sigue en DCA.".format(
                                    level_num,
                                    level,
                                    BTC_DCA_OUT_PCT,
                                    prices.get("btc_price_eur") or 0,
                                    BTC_DCA_OUT_STEP // 1000,
                                )
                            ),
                        }
                        sent = send_discord_message(
                            _format_embed(
                                "BTC DCA-out nivel {:d} (${:,.0f})".format(level_num, level),
                                "orange",
                                details,
                            )
                        )
                        _log_alert(session, alert_type, "orange", btc_price, eth_price, float(level), sent)
                        triggered.append({"type": alert_type, "severity": "orange", "sent": sent})
                level += BTC_DCA_OUT_STEP
                level_num += 1

        # Signals 5+: ETH DCA-out -- vender 3% cada $1k por encima de $3k
        if eth_price is not None:
            ETH_DCA_OUT_BASE = 3_000
            ETH_DCA_OUT_STEP = 1_000
            ETH_DCA_OUT_MAX  = 50_000
            ETH_DCA_OUT_PCT  = 3

            level = ETH_DCA_OUT_BASE
            level_num = 1
            while level <= ETH_DCA_OUT_MAX:
                if eth_price >= level:
                    alert_type = "eth_dca_out_{:d}k".format(level // 1000)
                    if not _already_alerted(session, alert_type, hours=720):  # 30 dias
                        details = {
                            "btc_price": btc_price,
                            "btc_price_eur": prices.get("btc_price_eur"),
                            "eth_price": eth_price,
                            "eth_price_eur": prices.get("eth_price_eur"),
                            "mvrv": mvrv,
                            "recommendation": (
                                "DCA-out nivel {:d} (${:,.0f}): vende el {}% de tu ETH en Trade Republic. "
                                "Precio aprox: {:,.0f} EUR. "
                                "NOTA: confirma que el ETH stakeado se puede vender directamente en TR.".format(
                                    level_num,
                                    level,
                                    ETH_DCA_OUT_PCT,
                                    prices.get("eth_price_eur") or 0,
                                )
                            ),
                        }
                        sent = send_discord_message(
                            _format_embed(
                                "ETH DCA-out nivel {:d} (${:,.0f})".format(level_num, level),
                                "orange",
                                details,
                            )
                        )
                        _log_alert(session, alert_type, "orange", btc_price, eth_price, float(level), sent)
                        triggered.append({"type": alert_type, "severity": "orange", "sent": sent})
                level += ETH_DCA_OUT_STEP
                level_num += 1

    if not triggered:
        logger.info("No alerts triggered. All metrics within normal ranges.")

    return triggered


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------

def _halving_cycle_text() -> str:
    """Return a short description of the current halving cycle phase.
    Research3: fase mas debil meses 18-24 post-halving (30d=-7.2% vs baseline).
    """
    from datetime import date as _date
    last_halving = _date(2024, 4, 19)
    today = _date.today()
    months_elapsed = (today - last_halving).days / 30.44
    if 18 <= months_elapsed < 24:
        return "Mes {:.0f}/48 desde halving abr-2024 -- ZONA DE RIESGO (meses 18-24: -7.2% a 30d vs baseline)".format(months_elapsed)
    return "Mes {:.0f}/48 desde halving abr-2024 -- fuera de zona de riesgo".format(months_elapsed)


def send_weekly_digest() -> bool:
    """
    Send a weekly summary digest to Discord.
    Includes: prices, on-chain indicators, halving phase, and last-7d alert summary.
    Uses 6-day cooldown to prevent duplicate sends.
    Returns True if message was sent.
    """
    init_db()

    with get_session() as session:
        if _already_alerted(session, "weekly_digest", hours=144):  # 6 dias
            logger.info("Weekly digest already sent within last 6 days, skipping.")
            return False

    prices = _fetch_prices()
    funding_rate = _fetch_funding_rate()
    eth_mvrv = _fetch_eth_mvrv()
    btc_mvrv = _fetch_btc_mvrv()

    btc_price = prices.get("btc_price")
    btc_price_eur = prices.get("btc_price_eur")
    btc_change = prices.get("btc_change")
    eth_price = prices.get("eth_price")
    eth_price_eur = prices.get("eth_price_eur")

    # Alerts from last 7 days
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    with get_session() as session:
        recent_alerts = session.execute(
            select(AlertLog)
            .where(AlertLog.timestamp >= week_ago)
            .where(AlertLog.alert_type != "weekly_digest")
            .order_by(AlertLog.timestamp.desc())
        ).scalars().all()

    fields = []

    # Block 1: Precios
    btc_str = "N/A"
    if btc_price:
        change_str = "{:+.1f}%".format(btc_change) if btc_change is not None else ""
        btc_str = "${:,.0f}".format(btc_price)
        if btc_price_eur:
            btc_str += " / {:,.0f} EUR".format(btc_price_eur)
        if change_str:
            btc_str += " ({})".format(change_str)
    fields.append({"name": "BTC", "value": btc_str, "inline": True})

    eth_str = "N/A"
    if eth_price:
        eth_str = "${:,.0f}".format(eth_price)
        if eth_price_eur:
            eth_str += " / {:,.0f} EUR".format(eth_price_eur)
    fields.append({"name": "ETH", "value": eth_str, "inline": True})

    fields.append({"name": "\u200b", "value": "\u200b", "inline": True})  # spacer

    # Block 2: Indicadores on-chain
    eth_mvrv_str = "{:.3f}".format(eth_mvrv) if eth_mvrv is not None else "N/A"
    if eth_mvrv is not None:
        if eth_mvrv < 0.8:
            eth_mvrv_str += " -- INFRAVALORADO (zona compra)"
        elif eth_mvrv < 1.0:
            eth_mvrv_str += " -- bajo valor realizado"
        elif eth_mvrv < 2.0:
            eth_mvrv_str += " -- rango normal"
        else:
            eth_mvrv_str += " -- zona caliente"
    fields.append({"name": "ETH MVRV", "value": eth_mvrv_str, "inline": True})

    btc_mvrv_str = "{:.3f}".format(btc_mvrv) if btc_mvrv is not None else "N/A"
    if btc_mvrv is not None:
        if btc_mvrv < 1.0:
            btc_mvrv_str += " -- bajo valor realizado"
        elif btc_mvrv < 2.0:
            btc_mvrv_str += " -- rango normal"
        elif btc_mvrv < 3.0:
            btc_mvrv_str += " -- zona caliente"
        else:
            btc_mvrv_str += " -- muy caliente (historicamente raro)"
    fields.append({"name": "BTC MVRV (info)", "value": btc_mvrv_str, "inline": True})

    funding_str = "{:.4f}%".format(funding_rate * 100) if funding_rate is not None else "N/A"
    fields.append({"name": "BTC Funding", "value": funding_str, "inline": True})

    # Block 3: Halving cycle
    fields.append({"name": "Ciclo Halving", "value": _halving_cycle_text(), "inline": False})

    # Block 4: Alertas de la semana
    if recent_alerts:
        alert_lines = []
        for a in recent_alerts[:8]:  # max 8 para no exceder limite Discord
            ts = a.timestamp.strftime("%d/%m %H:%M") if a.timestamp else "?"
            alert_lines.append("{} `{}` {}".format(ts, a.alert_type, a.severity.upper()))
        alerts_text = "\n".join(alert_lines)
    else:
        alerts_text = "Semana sin seniales -- Sparplan corriendo con normalidad."
    fields.append({"name": "Alertas ultimos 7 dias ({:d})".format(len(recent_alerts)), "value": alerts_text, "inline": False})

    payload = {
        "embeds": [{
            "title": "Resumen Semanal CryptoTrader",
            "description": "Estado del mercado y seniales de la semana.",
            "color": 0x3B82F6,
            "fields": fields,
            "footer": {"text": "CryptoTrader Advisor -- Domingo"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    sent = send_discord_message(payload)
    with get_session() as session:
        _log_alert(session, "weekly_digest", "blue", btc_price, eth_price, eth_mvrv, sent)
    logger.info("Weekly digest sent: %s", sent)
    return sent
