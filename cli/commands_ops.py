"""Operational commands: check, digest, dashboard, monitor."""

import argparse

from data.database import init_db
from cli.constants import halving_cycle_info


def cmd_check(args: argparse.Namespace) -> None:
    """Quick check: fetch all signals and show current status."""
    init_db()
    from data.market_data import fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_fear_greed
    from alerts.discord_bot import (
        BTC_CRASH_THRESHOLD, FUNDING_RATE_THRESHOLD,
        BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP, BTC_DCA_OUT_MAX, BTC_DCA_OUT_PCT,
        ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP, ETH_DCA_OUT_MAX, ETH_DCA_OUT_PCT,
    )

    print("CryptoTrader Advisor - Quick Check")
    print("=" * 55)

    prices   = fetch_prices()
    fg       = fetch_fear_greed()
    mvrv     = fetch_mvrv("eth")
    btc_mvrv = fetch_mvrv("btc")
    funding  = fetch_funding_rate()

    btc_price  = prices.get("btc_price")
    btc_change = prices.get("btc_change_24h")
    eth_price  = prices.get("eth_price")
    eth_change = prices.get("eth_change_24h")
    fg_val     = fg.get("fear_greed_value")
    fg_label   = fg.get("fear_greed_label")

    print("\n  MARKET STATUS:")
    if btc_price:
        color = "+" if btc_change and btc_change > 0 else ""
        print(f"    BTC:  ${btc_price:,.2f}  ({color}{btc_change:.1f}% 24h)")
    if eth_price:
        color = "+" if eth_change and eth_change > 0 else ""
        print(f"    ETH:  ${eth_price:,.2f}  ({color}{eth_change:.1f}% 24h)")
    if fg_val is not None:
        print(f"    F&G:  {fg_val} ({fg_label})")
    if funding is not None:
        print(f"    Funding: {funding*100:.4f}%")
    if mvrv is not None:
        print(f"    ETH MVRV: {mvrv:.3f}  (informativo, no es senal de compra -- research13)")
    if btc_mvrv is not None:
        print(f"    BTC MVRV: {btc_mvrv:.3f}  (informativo, no es senal de venta)")

    hc = halving_cycle_info()
    print("\n  CICLO HALVING:")
    print(f"    Mes {hc['months_elapsed']:.1f}/48 desde halving {hc['halving_date']}")
    if hc["in_risk_zone"]:
        print("    [WATCH] Zona de menor retorno historico (meses 18-24): -7.2% a 30d vs baseline")
        print("            Informativo: continua el Sparplan normal, no vender por este motivo")
    else:
        print("    [OK] Fuera de zona de riesgo del ciclo")

    print("\n  SIGNALS:")
    has_alert = False

    if btc_change is not None and btc_change <= BTC_CRASH_THRESHOLD:
        print(f"    [RED] BTC CRASH: {btc_change:.1f}% in 24h")
        print("          -> Buy extra 100-150 EUR of BTC in Trade Republic")
        has_alert = True

    if btc_change is not None and btc_change <= -10 and btc_change > BTC_CRASH_THRESHOLD:
        print(f"    [WATCH] BTC dropped {btc_change:.1f}% - monitoring for further drop")
        has_alert = True

    if funding is not None and funding < FUNDING_RATE_THRESHOLD:
        print(f"    [ORANGE] Negative funding ({funding*100:.4f}%)")
        print("          -> Bullish signal, consider extra BTC buy")
        has_alert = True

    if btc_price is not None:
        level = BTC_DCA_OUT_BASE
        level_num = 1
        while level <= BTC_DCA_OUT_MAX:
            if btc_price >= level:
                print(f"    [ORANGE] BTC DCA-out nivel {level_num} (${level:,.0f}): vende el {BTC_DCA_OUT_PCT}% de tus BTC en TR")
                has_alert = True
            level += BTC_DCA_OUT_STEP
            level_num += 1

    if eth_price is not None:
        level = ETH_DCA_OUT_BASE
        level_num = 1
        while level <= ETH_DCA_OUT_MAX:
            if eth_price >= level:
                print(f"    [ORANGE] ETH DCA-out nivel {level_num} (${level:,.0f}): vende el {ETH_DCA_OUT_PCT}% de tu ETH en TR")
                has_alert = True
            level += ETH_DCA_OUT_STEP
            level_num += 1

    if not has_alert:
        print("    [OK] No action needed. Sparplan running as usual.")

    if args.notify:
        from alerts.discord_bot import check_and_alert
        triggered = check_and_alert(prices=prices)
        if triggered:
            sent = sum(1 for a in triggered if a.get("sent"))
            print(f"\n  Discord alerts sent: {sent}/{len(triggered)}")
        else:
            print("\n  No alerts triggered.")

    print(f"\n{'='*55}")


def cmd_digest(args: argparse.Namespace) -> None:
    """Send weekly digest to Discord (or print preview without --notify)."""
    init_db()
    if args.notify:
        from alerts.digest import send_weekly_digest
        sent = send_weekly_digest()
        if sent:
            print("Weekly digest sent to Discord.")
        else:
            print("Digest not sent (already sent within last 6 days, or webhook not configured).")
    else:
        hc = halving_cycle_info()
        months = hc["months_elapsed"]
        print("CryptoTrader - Digest Preview (use --notify to send)")
        print("=" * 55)
        print(f"  Ciclo halving: mes {months:.1f}/48 desde halving abr-2024")
        if hc["in_risk_zone"]:
            print("  [WATCH] Zona de menor retorno historico (meses 18-24): -7.2% a 30d vs baseline")
        else:
            print("  [OK] Fuera de zona de riesgo del ciclo")
        print("  Use --notify para enviar el embed completo a Discord.")
        print("=" * 55)


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Run the web dashboard on localhost."""
    import uvicorn
    host = args.host or "127.0.0.1"
    port = args.port or 8000
    print(f"Starting CryptoTrader Dashboard at http://{host}:{port}")
    uvicorn.run("dashboard.app:app", host=host, port=port, reload=False)


def cmd_monitor(args: argparse.Namespace) -> None:
    """Run the background alert monitor."""
    init_db()
    from alerts.monitor import start_monitor
    interval = args.interval or 1
    start_monitor(interval_hours=interval)


def cmd_drift_check(args: argparse.Namespace) -> None:
    """Check portfolio drift vs Sparplan targets. Sends Discord alert if >10pp drift."""
    import logging
    from data.market_data import fetch_prices
    from data.models import UserTrade
    from data.database import get_session
    from cli.constants import SPARPLAN_TARGETS, DRIFT_THRESHOLD

    COOLDOWN_DRIFT = 168  # 7 days
    _logger = logging.getLogger(__name__)

    init_db()
    prices = fetch_prices()
    btc_price_eur = prices.get("btc_price_eur") or 0.0
    eth_price_eur = prices.get("eth_price_eur") or 0.0

    etf_prices = {}
    try:
        from data.etf_prices import fetch_all_etf_prices_eur
        etf_prices = fetch_all_etf_prices_eur() or {}
    except ImportError:
        _logger.info("yfinance not installed -- ETF prices skipped in drift-check")
    except Exception as exc:
        _logger.warning("ETF price fetch failed in drift-check: %s", exc)

    asset_prices_eur = {
        "BTC": btc_price_eur,
        "ETH": eth_price_eur,
        "SP500": etf_prices.get("SP500") or 0.0,
        "SEMICONDUCTORS": etf_prices.get("SEMICONDUCTORS") or 0.0,
        "REALTY_INCOME": etf_prices.get("REALTY_INCOME") or 0.0,
        "URANIUM": etf_prices.get("URANIUM") or 0.0,
    }

    with get_session() as session:
        rows = session.query(UserTrade).all()
        trades_list = [{"asset": t.asset, "side": t.side, "units": t.units} for t in rows]

    units_held = {}
    for t in trades_list:
        delta = t["units"] if t["side"] == "buy" else -t["units"]
        units_held[t["asset"]] = units_held.get(t["asset"], 0.0) + delta

    values = {
        asset: units_held.get(asset, 0.0) * asset_prices_eur.get(asset, 0.0)
        for asset in SPARPLAN_TARGETS
    }
    total = sum(values.values())

    print("CryptoTrader - Drift Check vs Sparplan Targets")
    print("=" * 57)

    missing_prices = [a for a in SPARPLAN_TARGETS if asset_prices_eur.get(a, 0.0) == 0.0]
    if missing_prices:
        print("  [AVISO] Sin precio para: {} -- instala yfinance o revisa la conexion".format(
            ", ".join(missing_prices)
        ))

    if total == 0.0:
        print("  Portfolio vacio o sin precios disponibles. Agrega trades con 'portfolio add-buy'.")
        print("=" * 57)
        return

    print("  Total portfolio: {:,.0f} EUR".format(total))
    print()
    print("  {:<16} {:>7} {:>7} {:>8}  {}".format("Asset", "Target", "Actual", "Drift", "Status"))
    print("  " + "-" * 52)

    alerts_to_send = []
    for asset, target_pct in SPARPLAN_TARGETS.items():
        actual_pct = values[asset] / total * 100
        drift = actual_pct - target_pct
        price_known = asset_prices_eur.get(asset, 0.0) > 0.0
        if abs(drift) > DRIFT_THRESHOLD and price_known:
            status = "[REBALANCEAR]"
            alerts_to_send.append((asset, drift, values[asset]))
        elif abs(drift) > 5.0 and price_known:
            status = "[WATCH]"
        elif not price_known:
            status = "[SIN PRECIO]"
        else:
            status = "[OK]"
        print("  {:<16} {:>6.1f}%  {:>6.1f}%  {:>+7.1f}pp  {}".format(
            asset, target_pct, actual_pct, drift, status
        ))

    print("=" * 57)

    if alerts_to_send:
        print("\n  Para rebalancear:")
        for asset, drift, val in alerts_to_send:
            target_value = total * SPARPLAN_TARGETS[asset] / 100
            delta_eur = target_value - val
            action = "Compra" if delta_eur > 0 else "Vende"
            print("    {} {:.0f} EUR de {}".format(action, abs(delta_eur), asset))
        print()

    if not args.notify:
        if alerts_to_send:
            print("  [!] {} activo(s) con drift >10pp. Usa --notify para enviar a Discord.".format(
                len(alerts_to_send)
            ))
        return

    if not alerts_to_send:
        print("  Sin drift significativo. No se enviaron alertas.")
        return

    from alerts.discord_bot import _already_alerted, _log_alert, send_discord_message, _format_embed
    btc_price = prices.get("btc_price")
    eth_price = prices.get("eth_price")

    with get_session() as session:
        for asset, drift, val in alerts_to_send:
            alert_type = "rebalance_drift_{}".format(asset.lower())
            if not _already_alerted(session, alert_type, COOLDOWN_DRIFT):
                direction = "sobre-ponderado" if drift > 0 else "infra-ponderado"
                sent = send_discord_message(_format_embed(
                    "Drift Rebalanceo -- {}".format(asset),
                    "orange",
                    {
                        "btc_price": btc_price,
                        "btc_price_eur": prices.get("btc_price_eur"),
                        "eth_price": eth_price,
                        "eth_price_eur": prices.get("eth_price_eur"),
                        "recommendation": (
                            "{} {} en {:+.1f}pp vs target. "
                            "Valor actual: {:,.0f} EUR. "
                            "Considera rebalancear en tu proxima revision anual.".format(
                                asset, direction, drift, val
                            )
                        ),
                    },
                ))
                _log_alert(session, alert_type, "orange", btc_price, eth_price, drift, sent)
                print("  Discord alert enviado: {} ({:+.1f}pp)".format(alert_type, drift))
            else:
                print("  Alert {} ya enviado recientemente (cooldown {}h).".format(
                    alert_type, COOLDOWN_DRIFT
                ))


def cmd_db_cleanup(args: argparse.Namespace) -> None:
    """Purge old alert_log records to keep DB size under control."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from data.database import get_session
    from data.models import AlertLog

    keep_days = getattr(args, "keep_days", 90)
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).replace(tzinfo=None)
    with get_session() as session:
        result = session.execute(
            delete(AlertLog).where(AlertLog.timestamp < cutoff)
        )
        deleted = result.rowcount
    print("db-cleanup: {} registros eliminados (anteriores a {})".format(deleted, cutoff.date()))
