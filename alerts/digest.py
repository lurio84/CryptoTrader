"""Weekly digest for CryptoTrader Discord alerts.

Extracted from discord_bot.py to keep that module focused on alert logic.
Imports private helpers from discord_bot (one-way dependency, no circular import).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from data.database import init_db, get_session
from data.market_data import (
    fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_sp500_change,
    fetch_price_history, fetch_sp500_history, calc_correlation,
)
from data.models import AlertLog
from alerts.discord_bot import (
    _already_alerted,
    _log_alert,
    send_discord_message,
    BTC_CRASH_THRESHOLD,
    BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP, BTC_DCA_OUT_MAX,
    ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP, ETH_DCA_OUT_MAX,
    SP500_CRASH_THRESHOLD,
)
from cli.constants import halving_cycle_info

logger = logging.getLogger(__name__)


def _get_portfolio_summary(btc_price_eur: float | None, eth_price_eur: float | None) -> dict:
    """Return portfolio value/PnL summary. Empty dict if no trades in DB."""
    from data.models import UserTrade
    from data.database import get_session
    from data.portfolio import calculate_portfolio_status
    from alerts.discord_bot import (
        BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP,
        ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP,
    )

    _RELEVANT_ASSETS = (
        "BTC", "ETH", "SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM",
    )

    with get_session() as session:
        rows = (
            session.query(UserTrade)
            .filter(UserTrade.asset.in_(_RELEVANT_ASSETS))
            .all()
        )
        trades_by_asset: dict[str, list[dict]] = {}
        for t in rows:
            trades_by_asset.setdefault(t.asset, []).append(t.to_dict())

    result = {}

    irpf_total = 0.0

    realized_gain_total = 0.0

    if btc_price_eur and trades_by_asset.get("BTC"):
        s = calculate_portfolio_status("BTC", trades_by_asset["BTC"], btc_price_eur,
                                       BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP)
        result["btc_value"] = s["current_value_eur"]
        result["btc_pnl"] = s["unrealized_gain_eur"] + s["realized_gain_eur"]
        irpf_total += s.get("irpf_estimate_eur") or 0.0
        realized_gain_total += s.get("realized_gain_eur") or 0.0

    if eth_price_eur and trades_by_asset.get("ETH"):
        s = calculate_portfolio_status("ETH", trades_by_asset["ETH"], eth_price_eur,
                                       ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP)
        result["eth_value"] = s["current_value_eur"]
        result["eth_pnl"] = s["unrealized_gain_eur"] + s["realized_gain_eur"]
        irpf_total += s.get("irpf_estimate_eur") or 0.0
        realized_gain_total += s.get("realized_gain_eur") or 0.0

    if not result:
        return {}

    result["irpf_total_eur"] = irpf_total
    result["realized_gain_eur"] = realized_gain_total

    # ETF prices (lazy yfinance, optional -- falls back gracefully in CI).
    # NOTE: fetch_prices was already called in send_weekly_digest, so here we
    # only need the ETF block (avoid duplicate CoinGecko hits).
    etf_prices: dict = {}
    try:
        from data.etf_prices import fetch_all_etf_prices_eur
        etf_prices = fetch_all_etf_prices_eur() or {}
    except ImportError:
        logger.info("yfinance not installed -- ETF prices skipped in digest")
    except Exception as exc:
        logger.warning("ETF price fetch failed in digest: %s", exc)

    etf_total = 0.0
    etf_invested = 0.0
    etf_key_map = {
        "SP500": "sp500_value",
        "SEMICONDUCTORS": "semis_value",
        "REALTY_INCOME": "realty_value",
        "URANIUM": "uranium_value",
    }
    for asset, value_key in etf_key_map.items():
        price = etf_prices.get(asset)
        if price and trades_by_asset.get(asset):
            s = calculate_portfolio_status(asset, trades_by_asset[asset], price,
                                           1_000_000, 1)
            val = s["current_value_eur"]
            result[value_key] = val
            etf_total += val
            etf_invested += s.get("total_invested_eur", 0.0)

    if etf_total > 0:
        result["etf_value"] = etf_total
        result["etf_pnl"] = etf_total - etf_invested

    # Staking yield YTD (ETH staking rewards, informational for IRPF)
    current_year = datetime.now(timezone.utc).year
    staking_ytd = sum(
        t["units"] * t["price_eur"]
        for t in trades_by_asset.get("ETH", [])
        if t.get("side") == "staking" and t.get("date") is not None
        and t["date"].year == current_year
    )
    if staking_ytd > 0:
        result["staking_ytd_eur"] = staking_ytd

    return result


def _halving_cycle_text() -> str:
    """Return a short description of the current halving cycle phase.
    Research3: fase mas debil meses 18-24 post-halving (30d=-7.2% vs baseline).
    """
    info = halving_cycle_info()
    months = info["months_elapsed"]
    if info["in_risk_zone"]:
        return "Mes {:.0f}/48 desde halving abr-2024 -- ZONA DE RIESGO (meses 18-24: -7.2% a 30d vs baseline)".format(months)
    return "Mes {:.0f}/48 desde halving abr-2024 -- fuera de zona de riesgo".format(months)


def _allocation_block(portfolio: dict) -> str | None:
    """Return formatted allocation vs Sparplan targets string, or None if insufficient data."""
    from cli.constants import SPARPLAN_TARGETS

    key_map = {
        "BTC": "btc_value",
        "ETH": "eth_value",
        "SP500": "sp500_value",
        "SEMICONDUCTORS": "semis_value",
        "REALTY_INCOME": "realty_value",
        "URANIUM": "uranium_value",
    }
    values = {asset: portfolio.get(key, 0.0) for asset, key in key_map.items()}
    total = sum(values.values())
    if total <= 0:
        return None

    lines = []
    for asset, target_pct in SPARPLAN_TARGETS.items():
        val = values.get(asset, 0.0)
        actual_pct = val / total * 100
        drift = actual_pct - target_pct
        drift_str = ""
        if abs(drift) >= 2:
            marker = "! " if abs(drift) >= 10 else ""
            drift_str = " ({}{:+.1f}pp)".format(marker, drift)
        lines.append("{}: {:.1f}%{} (target {:.1f}%)".format(
            asset, actual_pct, drift_str, target_pct
        ))
    return "\n".join(lines)


def send_weekly_digest() -> bool:
    """Send a weekly summary digest to Discord.

    Includes: prices, on-chain indicators, halving phase, and last-7d alert summary.
    Uses 6-day cooldown to prevent duplicate sends.
    Returns True if message was sent.
    """
    init_db()

    with get_session() as session:
        if _already_alerted(session, "weekly_digest", hours=144):  # 6 dias
            logger.info("Weekly digest already sent within last 6 days, skipping.")
            return False

    prices = fetch_prices()
    funding_rate = fetch_funding_rate()
    eth_mvrv = fetch_mvrv("eth")
    btc_mvrv = fetch_mvrv("btc")
    sp500_change = fetch_sp500_change()

    # Correlation data (non-blocking -- None if API fails)
    btc_hist = fetch_price_history("bitcoin", 30)
    eth_hist = fetch_price_history("ethereum", 30)
    sp500_hist = fetch_sp500_history(30)
    corr_btc_sp500 = calc_correlation(btc_hist, sp500_hist) if btc_hist and sp500_hist else None
    corr_eth_sp500 = calc_correlation(eth_hist, sp500_hist) if eth_hist and sp500_hist else None
    corr_btc_eth = calc_correlation(btc_hist, eth_hist) if btc_hist and eth_hist else None

    btc_price = prices.get("btc_price")
    btc_price_eur = prices.get("btc_price_eur")
    btc_change = prices.get("btc_change_24h")
    eth_price = prices.get("eth_price")
    eth_price_eur = prices.get("eth_price_eur")

    portfolio = _get_portfolio_summary(btc_price_eur, eth_price_eur)

    # Alerts from last 7 days
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    with get_session() as session:
        rows = session.execute(
            select(AlertLog)
            .where(AlertLog.timestamp >= week_ago)
            .where(AlertLog.alert_type != "weekly_digest")
            .order_by(AlertLog.timestamp.desc())
        ).scalars().all()
        recent_alerts = [
            {"timestamp": a.timestamp, "alert_type": a.alert_type, "severity": a.severity}
            for a in rows
        ]

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

    sp500_str = "{:+.2f}% (5d)".format(sp500_change) if sp500_change is not None else "N/A"
    if sp500_change is not None:
        if sp500_change <= SP500_CRASH_THRESHOLD:
            sp500_str += " -- CRASH activo"
        elif sp500_change <= -3:
            sp500_str += " -- caida notable"
    fields.append({"name": "S&P500", "value": sp500_str, "inline": True})

    # Block 2b: Correlacion 30d (informacional)
    def _corr_label(c: float | None) -> str:
        if c is None:
            return "N/A"
        label = "alta" if abs(c) >= 0.7 else ("media" if abs(c) >= 0.4 else "baja")
        return "{:.2f} ({})".format(c, label)

    corr_lines = [
        "BTC/SP500: {}".format(_corr_label(corr_btc_sp500)),
        "ETH/SP500: {}".format(_corr_label(corr_eth_sp500)),
        "BTC/ETH:   {}".format(_corr_label(corr_btc_eth)),
    ]
    fields.append({"name": "Correlacion 30d", "value": "\n".join(corr_lines), "inline": False})

    # Block 3: Halving cycle
    fields.append({"name": "Ciclo Halving", "value": _halving_cycle_text(), "inline": False})

    # Block 3b: Portfolio value
    if portfolio:
        btc_val = portfolio.get("btc_value", 0.0)
        eth_val = portfolio.get("eth_value", 0.0)
        total_crypto = btc_val + eth_val
        total_crypto_pnl = portfolio.get("btc_pnl", 0.0) + portfolio.get("eth_pnl", 0.0)
        lines = []
        if btc_val > 0:
            lines.append("BTC: {:,.0f} EUR (P&L: {:+,.0f})".format(btc_val, portfolio.get("btc_pnl", 0.0)))
        if eth_val > 0:
            lines.append("ETH: {:,.0f} EUR (P&L: {:+,.0f})".format(eth_val, portfolio.get("eth_pnl", 0.0)))
        if "etf_value" in portfolio:
            lines.append("ETFs: {:,.0f} EUR (P&L: {:+,.0f})".format(
                portfolio["etf_value"], portfolio.get("etf_pnl", 0.0)
            ))
            grand_total = total_crypto + portfolio["etf_value"]
            grand_pnl = total_crypto_pnl + portfolio.get("etf_pnl", 0.0)
            lines.append("**TOTAL: {:,.0f} EUR (P&L: {:+,.0f})**".format(grand_total, grand_pnl))
        else:
            lines.append("ETFs: no disponible (requiere yfinance local)")
            lines.append("Crypto total: {:,.0f} EUR (P&L: {:+,.0f})".format(total_crypto, total_crypto_pnl))
        irpf = portfolio.get("irpf_total_eur", 0.0)
        if irpf and irpf > 0:
            lines.append("IRPF est.: {:,.0f} EUR (si vendieras hoy)".format(irpf))
        realized = portfolio.get("realized_gain_eur", 0.0)
        if realized and realized > 0:
            from data.portfolio import compute_tax_headroom
            hroom = compute_tax_headroom(realized)
            if hroom["headroom_eur"] is not None:
                lines.append("Margen IRPF: {:,.0f} EUR hasta siguiente tramo ({})".format(
                    hroom["headroom_eur"], hroom["current_bracket_label"]
                ))
        staking_ytd = portfolio.get("staking_ytd_eur", 0.0)
        if staking_ytd and staking_ytd > 0:
            lines.append("Staking ETH {}: +{:.2f} EUR".format(
                datetime.now(timezone.utc).year, staking_ytd
            ))
        fields.append({"name": "Portfolio actual", "value": "\n".join(lines), "inline": False})

    # Block 3c: Allocation vs Sparplan targets
    if portfolio:
        alloc = _allocation_block(portfolio)
        if alloc:
            fields.append({"name": "Asignacion vs targets", "value": alloc, "inline": False})

    # Block 4: Proximas senales -- distancia a cada umbral de alerta
    signals_lines = []

    if btc_change is not None:
        gap_crash = btc_change - BTC_CRASH_THRESHOLD
        if gap_crash > 0:
            signals_lines.append("BTC crash: -{:.1f}pp para umbral (actual: {:+.1f}% 24h)".format(gap_crash, btc_change))
        else:
            signals_lines.append("BTC CRASH: umbral alcanzado ({:+.1f}% 24h)".format(btc_change))

    if eth_mvrv is not None:
        # ETH MVRV informativo solo (research13 descarto como senal de compra)
        signals_lines.append("ETH MVRV: {:.3f} (informativo)".format(eth_mvrv))

    if sp500_change is not None:
        gap_sp500 = sp500_change - SP500_CRASH_THRESHOLD
        if gap_sp500 > 0:
            signals_lines.append("S&P500: -{:.1f}pp para umbral -7% (actual {:+.1f}% 5d)".format(gap_sp500, sp500_change))
        else:
            signals_lines.append("S&P500: umbral CRASH alcanzado ({:+.1f}% 5d)".format(sp500_change))

    if btc_price is not None:
        next_btc = BTC_DCA_OUT_BASE
        while next_btc <= BTC_DCA_OUT_MAX and btc_price >= next_btc:
            next_btc += BTC_DCA_OUT_STEP
        if next_btc <= BTC_DCA_OUT_MAX:
            pct = (next_btc - btc_price) / btc_price * 100
            signals_lines.append("BTC DCA-out: proximo ${:,.0f} (+{:.1f}%)".format(next_btc, pct))
        else:
            signals_lines.append("BTC DCA-out: todos los niveles superados")

    if eth_price is not None:
        next_eth = ETH_DCA_OUT_BASE
        while next_eth <= ETH_DCA_OUT_MAX and eth_price >= next_eth:
            next_eth += ETH_DCA_OUT_STEP
        if next_eth <= ETH_DCA_OUT_MAX:
            pct = (next_eth - eth_price) / eth_price * 100
            signals_lines.append("ETH DCA-out: proximo ${:,.0f} (+{:.1f}%)".format(next_eth, pct))
        else:
            signals_lines.append("ETH DCA-out: todos los niveles superados")

    if signals_lines:
        fields.append({"name": "Proximas senales", "value": "\n".join(signals_lines), "inline": False})

    # Block 5: Alertas de la semana
    if recent_alerts:
        alert_lines = []
        for a in recent_alerts[:8]:  # max 8 para no exceder limite Discord
            ts = a["timestamp"].strftime("%d/%m %H:%M") if a["timestamp"] else "?"
            alert_lines.append("{} `{}` {}".format(ts, a["alert_type"], a["severity"].upper()))
        alerts_text = "\n".join(alert_lines)
    else:
        alerts_text = "Semana sin senales -- Sparplan corriendo con normalidad."
    fields.append({"name": "Alertas ultimos 7 dias ({:d})".format(len(recent_alerts)), "value": alerts_text, "inline": False})

    payload = {
        "embeds": [{
            "title": "Resumen Semanal CryptoTrader",
            "description": "Estado del mercado y senales de la semana.",
            "color": 0x3B82F6,
            "fields": fields,
            "footer": {"text": "CryptoTrader Advisor -- Domingo"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    sent = send_discord_message(payload)
    with get_session() as session:
        _log_alert(session, "weekly_digest", "blue", btc_price, eth_price, eth_mvrv, sent)

    if portfolio:
        _save_portfolio_snapshot(portfolio)

    logger.info("Weekly digest sent: %s", sent)
    return sent


def _save_portfolio_snapshot(portfolio: dict) -> None:
    """Save a weekly portfolio snapshot (idempotent per ISO week)."""
    import json
    from data.models import UserPortfolioSnapshot

    total = portfolio.get("btc_value", 0.0) + portfolio.get("eth_value", 0.0)
    if "etf_value" in portfolio:
        total += portfolio["etf_value"]

    if total <= 0:
        return

    week_str = datetime.now(timezone.utc).strftime("%G-W%V")  # ISO week e.g. "2026-W15"

    data = {
        "btc_value": portfolio.get("btc_value", 0.0),
        "eth_value": portfolio.get("eth_value", 0.0),
        "etf_value": portfolio.get("etf_value", 0.0),
        "total": total,
        "btc_pnl": portfolio.get("btc_pnl", 0.0),
        "eth_pnl": portfolio.get("eth_pnl", 0.0),
        "irpf_estimate": portfolio.get("irpf_total_eur", 0.0),
    }

    try:
        with get_session() as session:
            existing = session.query(UserPortfolioSnapshot).filter_by(snapshot_date=week_str).first()
            if not existing:
                snap = UserPortfolioSnapshot(
                    snapshot_date=week_str,
                    data_json=json.dumps(data),
                )
                session.add(snap)
        logger.info("Portfolio snapshot saved for %s", week_str)
    except Exception as exc:
        logger.warning("Failed to save portfolio snapshot: %s", exc)
