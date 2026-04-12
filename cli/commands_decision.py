"""Decision-support CLI commands: tax-simulate, what-if, health-check, explain-alert.

These are local-only commands meant for interactive decision support before
executing DCA-out sales, rebalancing, or understanding alert history.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone, timedelta

from data.database import init_db, get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# tax-simulate: "if I sold X units of ASSET at price Y today, how much IRPF?"
# ---------------------------------------------------------------------------

def cmd_tax_simulate(args: argparse.Namespace) -> None:
    """Simulate a hypothetical sale and compute resulting FIFO cost basis + IRPF.

    Reuses calculate_tax_report (adds synthetic sell) and compute_spanish_tax.
    Does NOT persist anything. Purely read-only.
    """
    from data.models import UserTrade
    from data.portfolio import (
        calculate_tax_report,
        compute_spanish_tax,
        compute_tax_headroom,
    )

    init_db()
    asset = args.asset.upper()
    units = float(args.units)
    price_eur = float(args.price_eur)
    year = args.year or datetime.now().year

    if units <= 0 or price_eur <= 0:
        print("Error: --units y --price-eur deben ser positivos.")
        return

    with get_session() as session:
        rows = session.query(UserTrade).all()
        real_trades = [t.to_dict() for t in rows]

    if not real_trades:
        print("No hay operaciones registradas. Agrega trades con 'portfolio add-buy' primero.")
        return

    # Baseline: real IRPF for the year
    real_report = calculate_tax_report(real_trades, year)
    real_gain = real_report["total_gain_eur"]
    real_irpf = real_report["total_irpf_eur"]

    # Simulated trade appended at today (no persistence)
    synth = UserTrade(
        date=datetime.now(),
        asset=asset,
        asset_class="crypto" if asset in ("BTC", "ETH") else "etf",
        side="sell",
        units=units,
        price_eur=price_eur,
        fee_eur=0.0,
        source="dca_out",
        notes="SIMULATION",
    ).to_dict()
    sim_report = calculate_tax_report(real_trades + [synth], year)
    sim_gain = sim_report["total_gain_eur"]
    sim_irpf = sim_report["total_irpf_eur"]

    delta_gain = sim_gain - real_gain
    delta_irpf = sim_irpf - real_irpf
    proceeds = units * price_eur
    net_cash = proceeds - delta_irpf

    headroom_before = compute_tax_headroom(max(real_gain, 0))
    headroom_after = compute_tax_headroom(max(sim_gain, 0))

    print(f"SIMULACION VENTA -- {asset}")
    print("=" * 57)
    print(f"  Hipotesis: vender {units:.6f} {asset} a {price_eur:,.2f} EUR/u")
    print(f"  Ingresos brutos (proceeds):       {proceeds:>12,.2f} EUR")
    print()
    print(f"  Plusvalias {year} ANTES:          {real_gain:>12,.2f} EUR")
    print(f"  Plusvalias {year} DESPUES:        {sim_gain:>12,.2f} EUR")
    print(f"  Delta plusvalia:                  {delta_gain:>+12,.2f} EUR")
    print()
    print(f"  IRPF {year} antes:                {real_irpf:>12,.2f} EUR")
    print(f"  IRPF {year} despues:              {sim_irpf:>12,.2f} EUR")
    print(f"  Delta IRPF (coste fiscal venta):  {delta_irpf:>+12,.2f} EUR")
    print()
    print(f"  Net cash (proceeds - delta IRPF): {net_cash:>12,.2f} EUR")
    print(f"  Retencion efectiva:               {(delta_irpf / proceeds * 100 if proceeds > 0 else 0):>11.1f}%")
    print()
    print(f"  Tramo IRPF antes:                 {headroom_before['current_bracket_label']}")
    print(f"  Tramo IRPF despues:               {headroom_after['current_bracket_label']}")
    if headroom_after["headroom_eur"] is not None:
        print(f"  Margen tras venta hasta sig.:     {headroom_after['headroom_eur']:>12,.0f} EUR")
    else:
        print("  Margen tras venta hasta sig.:     (tramo maximo)")
    print()
    print("  Nota: SIMULACION no persiste nada en la base de datos.")


# ---------------------------------------------------------------------------
# what-if: "if BTC reaches price X, what would drift + DCA levels look like?"
# ---------------------------------------------------------------------------

def cmd_what_if(args: argparse.Namespace) -> None:
    """Project drift and DCA-out implications if an asset hits a target price.

    Purely read-only. Uses current holdings but substitutes price for the target asset.
    """
    from cli.constants import SPARPLAN_TARGETS, DRIFT_THRESHOLD, DRIFT_WATCH_THRESHOLD, EUR_USD_AVG
    from data.market_data import fetch_portfolio_prices_eur
    from data.models import UserTrade
    from data.portfolio import calculate_portfolio_status, compute_spanish_tax
    from alerts.discord_bot import (
        BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP, BTC_DCA_OUT_MAX,
        ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP, ETH_DCA_OUT_MAX,
        BTC_DCA_OUT_PCT, ETH_DCA_OUT_PCT,
    )

    init_db()
    asset = args.asset.upper()
    target_price_usd = float(args.price)
    eur_usd = EUR_USD_AVG
    target_price_eur = target_price_usd / eur_usd

    prices = fetch_portfolio_prices_eur(include_etfs=True)
    btc_price_eur = prices["btc_eur"] or 0.0
    eth_price_eur = prices["eth_eur"] or 0.0
    etf_prices = prices["etf_prices"]

    with get_session() as session:
        rows = session.query(UserTrade).all()
        all_trades = [t.to_dict() for t in rows]

    if not all_trades:
        print("No hay operaciones registradas.")
        return

    btc_trades = [t for t in all_trades if t["asset"] == "BTC"]
    eth_trades = [t for t in all_trades if t["asset"] == "ETH"]

    if asset == "BTC":
        btc_price_eur = target_price_eur
    elif asset == "ETH":
        eth_price_eur = target_price_eur

    all_values: dict[str, float] = {k: 0.0 for k in SPARPLAN_TARGETS}

    if btc_price_eur and btc_trades:
        s = calculate_portfolio_status(
            "BTC", btc_trades, btc_price_eur,
            BTC_DCA_OUT_BASE / eur_usd, BTC_DCA_OUT_STEP / eur_usd,
        )
        all_values["BTC"] = s["current_value_eur"]
        btc_unrealized = s["unrealized_gain_eur"]
    else:
        btc_unrealized = 0.0

    if eth_price_eur and eth_trades:
        s = calculate_portfolio_status(
            "ETH", eth_trades, eth_price_eur,
            ETH_DCA_OUT_BASE / eur_usd, ETH_DCA_OUT_STEP / eur_usd,
        )
        all_values["ETH"] = s["current_value_eur"]
        eth_unrealized = s["unrealized_gain_eur"]
    else:
        eth_unrealized = 0.0

    # ETFs from real prices
    etf_trades_all = [t for t in all_trades if t.get("asset_class") == "etf"]
    for etf_asset in ("SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM"):
        trades_for = [t for t in etf_trades_all if t["asset"] == etf_asset]
        total_units = (
            sum(t["units"] for t in trades_for if t["side"] == "buy")
            - sum(t["units"] for t in trades_for if t["side"] == "sell")
        )
        price = etf_prices.get(etf_asset)
        if price is not None and total_units > 0:
            all_values[etf_asset] = total_units * price

    total = sum(all_values.values())

    print(f"WHAT-IF -- Si {asset} llega a ${target_price_usd:,.0f}")
    print("=" * 64)
    print(f"  Precio objetivo: ${target_price_usd:,.0f} ({target_price_eur:,.0f} EUR con EUR/USD={eur_usd})")
    print()

    if total <= 0:
        print("  Portfolio total = 0. Revisa precios y trades.")
        return

    print(
        f"  {'Activo':<16} {'Valor EUR':>11}  {'Actual%':>7}  "
        f"{'Target%':>7}  {'Drift':>7}  Estado"
    )
    print(f"  {'-'*16} {'-'*11}  {'-'*7}  {'-'*7}  {'-'*7}  ------")
    for a, target_pct in SPARPLAN_TARGETS.items():
        val = all_values.get(a, 0.0)
        actual_pct = val / total * 100
        drift = actual_pct - target_pct
        if abs(drift) > DRIFT_THRESHOLD:
            estado = "[REBALANCEAR]"
        elif abs(drift) > DRIFT_WATCH_THRESHOLD:
            estado = "[WATCH]"
        else:
            estado = "[OK]"
        print(
            f"  {a:<16} {val:>11,.0f}  {actual_pct:>6.1f}%  "
            f"{target_pct:>6.1f}%  {drift:>+6.1f}pp  {estado}"
        )
    print(f"  {'TOTAL':<16} {total:>11,.0f}")

    print()
    if asset == "BTC":
        unrealized_delta = btc_unrealized
        print(f"  BTC unrealized P&L a {target_price_usd:,.0f}: {unrealized_delta:+,.0f} EUR")
    elif asset == "ETH":
        unrealized_delta = eth_unrealized
        print(f"  ETH unrealized P&L a {target_price_usd:,.0f}: {unrealized_delta:+,.0f} EUR")
    else:
        unrealized_delta = 0.0

    if unrealized_delta > 0:
        est_tax = compute_spanish_tax(unrealized_delta)
        print(f"  IRPF estimado si vendieras todo: {est_tax:>+,.0f} EUR")

    # DCA-out levels hit
    print()
    if asset == "BTC":
        levels_hit = []
        level = BTC_DCA_OUT_BASE
        n = 1
        while level <= BTC_DCA_OUT_MAX and target_price_usd >= level:
            levels_hit.append((n, level))
            level += BTC_DCA_OUT_STEP
            n += 1
        if levels_hit:
            print(f"  DCA-out BTC niveles activados ({BTC_DCA_OUT_PCT}% cada uno):")
            for n, lvl in levels_hit:
                print(f"    Nivel {n}: ${lvl:,.0f}")
        else:
            print(f"  DCA-out BTC: ningun nivel activado (base ${BTC_DCA_OUT_BASE:,.0f})")
    elif asset == "ETH":
        levels_hit = []
        level = ETH_DCA_OUT_BASE
        n = 1
        while level <= ETH_DCA_OUT_MAX and target_price_usd >= level:
            levels_hit.append((n, level))
            level += ETH_DCA_OUT_STEP
            n += 1
        if levels_hit:
            print(f"  DCA-out ETH niveles activados ({ETH_DCA_OUT_PCT}% cada uno):")
            for n, lvl in levels_hit:
                print(f"    Nivel {n}: ${lvl:,.0f}")
        else:
            print(f"  DCA-out ETH: ningun nivel activado (base ${ETH_DCA_OUT_BASE:,.0f})")


# ---------------------------------------------------------------------------
# health-check: validate DB + APIs + last heartbeat
# ---------------------------------------------------------------------------

def _check_db() -> dict:
    """Check DB accessibility and last heartbeat. Returns {"ok": bool, "lines": [str]}."""
    from data.models import AlertLog
    try:
        with get_session() as session:
            alert_count = session.query(AlertLog).count()
            last_hb_row = (
                session.query(AlertLog)
                .filter(AlertLog.alert_type == "heartbeat")
                .order_by(AlertLog.timestamp.desc())
                .first()
            )
            last_hb = last_hb_row.timestamp if last_hb_row else None
    except Exception as exc:
        return {"ok": False, "lines": [f"  [RED] DB: ERROR {exc}"]}

    lines = [f"  [OK]  DB: accesible ({alert_count} alertas en alert_log)"]
    if last_hb is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        gap_h = (now - last_hb).total_seconds() / 3600
        status = "OK" if gap_h < 10 else ("WATCH" if gap_h < 24 else "RED")
        lines.append(
            f"  [{status:<3}] Heartbeat: ultimo hace {gap_h:.1f}h (umbral canary: 10h)"
        )
    else:
        lines.append("  [WATCH] Heartbeat: ninguno registrado aun")
    return {"ok": True, "lines": lines}


def _check_apis() -> dict:
    """Check external APIs in parallel. Returns {"ok": bool, "lines": [str]}."""
    from concurrent.futures import ThreadPoolExecutor
    from data.market_data import (
        fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_sp500_change,
    )

    def _result(future):
        try:
            return future.result(timeout=15), None
        except Exception as exc:
            return None, str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_prices = pool.submit(fetch_prices)
        f_mvrv = pool.submit(fetch_mvrv, "eth")
        f_funding = pool.submit(fetch_funding_rate)
        f_sp500 = pool.submit(fetch_sp500_change)

    lines = []
    all_ok = True

    prices, err = _result(f_prices)
    if prices and prices.get("btc_price"):
        lines.append(f"  [OK]  CoinGecko (prices): BTC=${prices['btc_price']:,.0f}")
    else:
        lines.append(f"  [RED] CoinGecko (prices): {err or 'no data'}")
        all_ok = False

    mvrv, err = _result(f_mvrv)
    if mvrv is not None:
        lines.append(f"  [OK]  CoinMetrics (ETH MVRV): {mvrv:.3f}")
    else:
        lines.append(f"  [RED] CoinMetrics (ETH MVRV): {err or 'no data'}")
        all_ok = False

    funding, err = _result(f_funding)
    if funding is not None:
        lines.append(f"  [OK]  OKX (funding rate): {funding * 100:.4f}%")
    else:
        lines.append(f"  [RED] OKX (funding rate): {err or 'no data'}")
        all_ok = False

    sp500, err = _result(f_sp500)
    if sp500 is not None:
        lines.append(f"  [OK]  Stooq (S&P 500 5d): {sp500:+.2f}%")
    else:
        lines.append(f"  [RED] Stooq (S&P 500 5d): {err or 'no data'}")
        all_ok = False

    return {"ok": all_ok, "lines": lines}


def _check_webhook() -> dict:
    """Check Discord webhook configuration. Returns {"ok": bool, "line": str}."""
    try:
        from config.settings import settings
        webhook_set = bool(getattr(settings.discord, "webhook_url", None))
        status = "OK" if webhook_set else "WATCH"
        return {
            "ok": webhook_set,
            "line": f"  [{status:<3}] Discord webhook: {'configurado' if webhook_set else 'NO configurado (.env)'}",
        }
    except Exception as exc:
        return {"ok": False, "line": f"  [RED] Discord webhook: {exc}"}


def cmd_health_check(args: argparse.Namespace) -> None:
    """Run a health check on DB, external APIs and monitoring subsystem."""
    init_db()
    print("CryptoTrader - Health Check")
    print("=" * 55)

    db = _check_db()
    for line in db["lines"]:
        print(line)

    print()
    print("  Fuentes externas (paralelas, timeout 10s):")
    apis = _check_apis()
    for line in apis["lines"]:
        print(line)

    print()
    wh = _check_webhook()
    print(wh["line"])

    print("=" * 55)


# ---------------------------------------------------------------------------
# explain-alert: pretty-print a historical alert record
# ---------------------------------------------------------------------------

def cmd_explain_alert(args: argparse.Namespace) -> None:
    """Pretty-print details of a historical alert by id or by most recent of type."""
    from data.models import AlertLog

    init_db()

    with get_session() as session:
        row: AlertLog | None
        if args.id is not None:
            row = session.get(AlertLog, int(args.id))
        elif args.type:
            row = (
                session.query(AlertLog)
                .filter(AlertLog.alert_type == args.type)
                .order_by(AlertLog.timestamp.desc())
                .first()
            )
        else:
            print("Usa --id N o --type <alert_type>.")
            return

        if row is None:
            print("Alerta no encontrada.")
            return

        payload = {
            "id": row.id,
            "timestamp": row.timestamp,
            "alert_type": row.alert_type,
            "severity": row.severity,
            "message": row.message,
            "btc_price": row.btc_price,
            "eth_price": row.eth_price,
            "metric_value": row.metric_value,
            "notified": row.notified,
        }

        # Context: closest alerts in time (same session)
        ts = payload["timestamp"]
        if ts is not None:
            window = timedelta(hours=24)
            nearby_rows = (
                session.query(AlertLog)
                .filter(AlertLog.timestamp >= ts - window)
                .filter(AlertLog.timestamp <= ts + window)
                .filter(AlertLog.id != payload["id"])
                .filter(AlertLog.alert_type != "heartbeat")
                .order_by(AlertLog.timestamp.asc())
                .limit(10)
                .all()
            )
            nearby = [
                {"timestamp": n.timestamp, "alert_type": n.alert_type, "severity": n.severity}
                for n in nearby_rows
            ]
        else:
            nearby = []

    print("ALERT EXPLANATION")
    print("=" * 57)
    print(f"  id:         {payload['id']}")
    print(f"  timestamp:  {payload['timestamp']}")
    print(f"  type:       {payload['alert_type']}")
    print(f"  severity:   {payload['severity'].upper()}")
    print(f"  message:    {payload['message']}")
    print(f"  notified:   {'yes' if payload['notified'] else 'NO (skip or dedup)'}")
    if payload["btc_price"] is not None:
        print(f"  BTC price:  ${payload['btc_price']:,.2f}")
    if payload["eth_price"] is not None:
        print(f"  ETH price:  ${payload['eth_price']:,.2f}")
    if payload["metric_value"] is not None:
        print(f"  metric:     {payload['metric_value']}")

    if nearby:
        print()
        print(f"  Alertas cercanas (+-24h, max 10):")
        for n in nearby:
            print(f"    {n['timestamp']}  {n['alert_type']:<22} {n['severity']:<7}")
