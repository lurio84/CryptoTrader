"""Portfolio tracker command: add-buy, add-sell, show, history, export."""

import argparse

from data.database import init_db, get_session
from cli.constants import SPARPLAN_TARGETS, detect_asset_class


def cmd_portfolio(args: argparse.Namespace) -> None:
    """Personal portfolio tracker with FIFO cost basis and IRPF estimation."""
    init_db()
    import requests as req
    from datetime import datetime as _dt
    from sqlalchemy import select as _select
    from data.models import UserTrade
    from data.portfolio import calculate_portfolio_status, trades_to_csv, calculate_tax_report

    sub = args.portfolio_cmd

    if sub == "add-buy" or sub == "add-sell":
        side = "buy" if sub == "add-buy" else "sell"
        trade_date = _dt.strptime(args.date, "%Y-%m-%d") if args.date else _dt.now()
        asset_upper = args.asset.upper()
        trade = UserTrade(
            date=trade_date,
            asset=asset_upper,
            asset_class=detect_asset_class(asset_upper),
            side=side,
            units=args.units,
            price_eur=args.price_eur,
            fee_eur=args.fee_eur,
            source=args.source,
            notes=args.notes,
        )
        with get_session() as session:
            session.add(trade)
        total_eur = args.units * args.price_eur + args.fee_eur
        print(f"Registered: {side.upper()} {args.units:.6f} {asset_upper} @ {args.price_eur:.2f} EUR/unit = {total_eur:.2f} EUR total (fee: {args.fee_eur:.2f} EUR, source: {args.source})")
        return

    if sub == "add-dividend":
        trade_date = _dt.strptime(args.date, "%Y-%m-%d") if args.date else _dt.now()
        asset_upper = args.asset.upper()
        trade = UserTrade(
            date=trade_date,
            asset=asset_upper,
            asset_class=detect_asset_class(asset_upper),
            side="dividend",
            units=0.0,
            price_eur=args.amount_eur,
            fee_eur=0.0,
            source="dividend",
            notes=args.notes,
        )
        with get_session() as session:
            session.add(trade)
        print(f"Registered: DIVIDEND {asset_upper} {args.amount_eur:.2f} EUR on {trade_date.strftime('%Y-%m-%d')}")
        return

    if sub == "add-staking":
        trade_date = _dt.strptime(args.date, "%Y-%m-%d") if args.date else _dt.now()
        trade = UserTrade(
            date=trade_date,
            asset="ETH",
            asset_class="crypto",
            side="staking",
            units=args.units,
            price_eur=args.price_eur,
            fee_eur=0.0,
            source="staking",
            notes=args.notes,
        )
        with get_session() as session:
            session.add(trade)
        total_eur = args.units * args.price_eur
        print(f"Registered: STAKING ETH {args.units:.6f} units @ {args.price_eur:.2f} EUR/unit = {total_eur:.2f} EUR")

    if sub == "import":
        from data.portfolio import csv_to_trades
        try:
            rows = csv_to_trades(args.file)
        except (ValueError, FileNotFoundError, OSError) as e:
            print(f"Error: {e}")
            return
        if args.dry_run:
            print(f"Dry-run: {len(rows)} trades parsed OK")
            for r in rows:
                print(f"  {r['date'].date()} {r['asset']:<16} {r['side']:<4} {r['units']:.6f} @ {r['price_eur']:.2f} EUR  [{r['source']}]")
            return
        inserted = 0
        with get_session() as session:
            for r in rows:
                ac = r["asset_class"] or detect_asset_class(r["asset"])
                session.add(UserTrade(
                    date=r["date"], asset=r["asset"], asset_class=ac,
                    side=r["side"], units=r["units"], price_eur=r["price_eur"],
                    fee_eur=r["fee_eur"], source=r["source"], notes=r["notes"],
                ))
                inserted += 1
        print(f"Imported {inserted} trades.")
        return

    btc_price_eur = None
    eth_price_eur = None
    etf_prices: dict = {}
    if sub in ("show", None):
        try:
            resp = req.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin,ethereum", "vs_currencies": "eur"},
                timeout=10,
            )
            resp.raise_for_status()
            cg = resp.json()
            btc_price_eur = cg["bitcoin"]["eur"]
            eth_price_eur = cg["ethereum"]["eur"]
        except Exception:
            pass
        try:
            from data.etf_prices import fetch_all_etf_prices_eur
            etf_prices = fetch_all_etf_prices_eur()
        except Exception:
            etf_prices = {}

    def _row_to_dict(t: UserTrade) -> dict:
        return {
            "id": t.id, "date": t.date, "asset": t.asset,
            "asset_class": getattr(t, "asset_class", "crypto") or "crypto",
            "side": t.side, "units": t.units, "price_eur": t.price_eur,
            "fee_eur": t.fee_eur, "source": t.source, "notes": t.notes,
        }

    with get_session() as session:
        rows = session.execute(_select(UserTrade).order_by(UserTrade.date)).scalars().all()
        all_trades = [_row_to_dict(t) for t in rows]

    crypto_trades = [t for t in all_trades if t.get("asset_class", "crypto") == "crypto"]
    etf_trades_all = [t for t in all_trades if t.get("asset_class", "crypto") == "etf"]
    btc_trades = [t for t in crypto_trades if t["asset"] == "BTC"]
    eth_trades = [t for t in crypto_trades if t["asset"] == "ETH"]

    if sub == "export":
        print(trades_to_csv(all_trades), end="")
        return

    if sub == "tax-report":
        year = args.year or _dt.now().year
        report = calculate_tax_report(all_trades, year)

        if args.csv:
            import io as _io
            import csv as _csv
            buf = _io.StringIO()
            writer = _csv.writer(buf)
            writer.writerow(["date", "asset", "units", "sale_price_eur", "cost_basis_eur", "proceeds_eur", "gain_eur"])
            for r in report["rows"]:
                d = r["date"]
                writer.writerow([
                    d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
                    r["asset"],
                    "{:.8f}".format(r["units"]),
                    "{:.2f}".format(r["sale_price_eur"]),
                    "{:.2f}".format(r["cost_basis_eur"]),
                    "{:.2f}".format(r["proceeds_eur"]),
                    "{:.2f}".format(r["gain_eur"]),
                ])
            print(buf.getvalue(), end="")
            return

        print(f"INFORME IRPF {year}")
        print("=" * 72)
        if not report["rows"]:
            print(f"  No hay ventas registradas en {year}.")
            return

        print(f"  {'Fecha':<12} {'Activo':<16} {'Unidades':>12} {'Precio EUR':>11} {'Coste FIFO':>11} {'Ganancia':>11}")
        print("  " + "-" * 70)
        for r in report["rows"]:
            d = r["date"]
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            sign = "+" if r["gain_eur"] >= 0 else ""
            print(f"  {date_str:<12} {r['asset']:<16} {r['units']:>12.6f} {r['sale_price_eur']:>10.2f}E {r['cost_basis_eur']:>10.2f}E {sign}{r['gain_eur']:>9.2f}E")
        print("  " + "-" * 70)
        total_sign = "+" if report["total_gain_eur"] >= 0 else ""
        print(f"\n  TOTAL GANANCIA REALIZADA {year}: {total_sign}{report['total_gain_eur']:>10,.2f} EUR")
        if report["total_gain_eur"] > 0:
            print(f"  IRPF ESTIMADO (tramos ES):  {report['total_irpf_eur']:>10,.2f} EUR  (~{report['effective_rate_pct']:.1f}% efectivo)")
            for b in report["bracket_breakdown"]:
                print(f"    Tramo {b['label']}: {b['rate_pct']:.0f}% sobre {b['taxable_eur']:,.2f} EUR -> {b['tax_eur']:,.2f} EUR")
        elif report["total_gain_eur"] < 0:
            print("  Perdida neta: no hay IRPF. Compensable con ganancias futuras.")
        else:
            print("  Ganancia neta cero: sin IRPF.")

        if report.get("income_rows"):
            print(f"\n  RENDIMIENTOS DEL CAPITAL MOBILIARIO {year} (dividendos + staking)")
            print("  " + "-" * 50)
            for r in report["income_rows"]:
                d = r["date"]
                date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                print(f"  {date_str:<12} {r['asset']:<16} {r['side']:<10} {r['amount_eur']:>8.2f} EUR")
            print("  " + "-" * 50)
            print(f"  Total rendimientos: {report['total_income_eur']:,.2f} EUR")
            print(f"  Retencion estimada (19%): {report['total_income_irpf_eur']:,.2f} EUR")
        return

    if sub == "history":
        if not all_trades:
            print("No trades registered. Use 'portfolio add-buy' to add your first trade.")
            return
        print(f"{'Date':<12} {'Asset':<16} {'Side':<5} {'Units':>12} {'Price EUR':>11} {'Fee':>6} {'Source':<12} Notes")
        print("-" * 90)
        for t in sorted(all_trades, key=lambda x: x["date"]):
            d = t["date"]
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            print(f"{date_str:<12} {t['asset']:<16} {t['side']:<5} {t['units']:>12.6f} {t['price_eur']:>10.2f}E {t['fee_eur']:>5.2f}E {(t['source'] or ''):.<12} {t['notes'] or ''}")
        return

    if sub == "history-chart":
        import json
        from data.models import UserPortfolioSnapshot
        with get_session() as session:
            snaps = session.query(UserPortfolioSnapshot).order_by(UserPortfolioSnapshot.snapshot_date).all()
            snap_list = [{"date": s.snapshot_date, **json.loads(s.data_json)} for s in snaps]
        if not snap_list:
            print("Sin snapshots guardados todavia. Los snapshots se guardan automaticamente con el digest semanal.")
            return
        print("Evolucion semanal del portfolio")
        print("=" * 80)
        print(f"  {'Semana':<12} {'Total EUR':>12} {'BTC P&L':>10} {'ETH P&L':>10} {'IRPF est.':>10}")
        print("  " + "-" * 56)
        for s in snap_list:
            print("  {:<12} {:>12,.0f} {:>+10,.0f} {:>+10,.0f} {:>10,.0f}".format(
                s["date"],
                s.get("total", 0),
                s.get("btc_pnl", 0),
                s.get("eth_pnl", 0),
                s.get("irpf_estimate", 0),
            ))
        return

    # show (default): 3 sections -- Crypto, ETF, Total portfolio
    print("PORTFOLIO PERSONAL")
    print("=" * 57)

    crypto_total_invested = 0.0
    crypto_total_value = 0.0
    crypto_unrealized = 0.0
    crypto_irpf = 0.0

    print("\n[ CRYPTO ]")
    for asset, trades, price_eur, dca_base, dca_step in [
        ("BTC", btc_trades, btc_price_eur, 80_000 / 1.10, 20_000 / 1.10),
        ("ETH", eth_trades, eth_price_eur, 3_000 / 1.10, 1_000 / 1.10),
    ]:
        if not trades:
            print(f"  {asset}: sin operaciones registradas")
            continue
        if price_eur is None:
            print(f"  {asset}: precio no disponible (sin conexion)")
            continue
        s = calculate_portfolio_status(asset, trades, price_eur, dca_base, dca_step)
        sign = "+" if s["unrealized_gain_eur"] >= 0 else ""
        print(f"\n  {asset}: {s['units_held']:.6f} u  ({s['buy_count']} compras, {s['sell_count']} ventas)")
        print(f"    Coste medio FIFO: {s['avg_cost_eur']:>10,.2f} EUR/{asset}")
        print(f"    Valor actual:     {s['current_price_eur']:>10,.2f} EUR/{asset}")
        print(f"    Valor cartera:    {s['current_value_eur']:>10,.2f} EUR")
        print(f"    Ganancia no real: {sign}{s['unrealized_gain_eur']:>8,.2f} EUR ({sign}{s['unrealized_pct']:.1f}%)")
        if s["realized_gain_eur"] != 0:
            print(f"    Ganancia real.:   {s['realized_gain_eur']:>10,.2f} EUR (ventas anteriores)")
        print(f"    IRPF si vendieras:{s['irpf_estimate_eur']:>9,.0f} EUR (~{s['irpf_rate_pct']:.0f}% efectivo)")
        from data.portfolio import build_xirr_cash_flows, calculate_xirr
        xirr_val = calculate_xirr(build_xirr_cash_flows(trades, price_eur))
        if xirr_val is not None:
            print(f"    IRR anualizada:   {xirr_val * 100:>+9.1f}%  (TIR considerando fechas y cash flows)")
        if s["next_dca_level_eur"]:
            pct_to_level = (s["next_dca_level_eur"] / price_eur - 1) * 100
            print(f"    Proximo DCA-out:  {asset} a {s['next_dca_level_eur']:,.0f} EUR ({pct_to_level:+.1f}%) -> vende {s['next_dca_units']:.6f} {asset} ({s['next_dca_eur']:,.0f} EUR)")
        crypto_total_invested += s["total_invested_eur"]
        crypto_total_value += s["current_value_eur"]
        crypto_unrealized += s["unrealized_gain_eur"]
        crypto_irpf += s["irpf_estimate_eur"]

    print("\n[ ETF / ACCIONES ]")
    etf_value_map: dict[str, float] = {}
    etf_invested_total = 0.0
    etf_value_total = 0.0

    etf_assets = sorted({t["asset"] for t in etf_trades_all})
    if not etf_assets:
        print("  Sin operaciones ETF registradas.")
        print("  Usa: python main.py portfolio add-buy --asset SP500 --units 1 --price-eur 480 --source sparplan")
    else:
        for asset in etf_assets:
            trades_for = [t for t in etf_trades_all if t["asset"] == asset]
            total_units = sum(t["units"] for t in trades_for if t["side"] == "buy")
            total_units -= sum(t["units"] for t in trades_for if t["side"] == "sell")
            total_invested = sum(
                t["units"] * t["price_eur"] + t["fee_eur"]
                for t in trades_for if t["side"] == "buy"
            )
            current_price = etf_prices.get(asset)
            if current_price is not None and total_units > 0:
                current_value = total_units * current_price
                etf_value_map[asset] = current_value
                pnl = current_value - total_invested
                pnl_pct = pnl / total_invested * 100 if total_invested > 0 else 0.0
                sign = "+" if pnl >= 0 else ""
                print(f"\n  {asset}: {total_units:.4f} u  ({len(trades_for)} operaciones)")
                print(f"    Precio actual:    {current_price:>10,.2f} EUR/u")
                print(f"    Valor cartera:    {current_value:>10,.2f} EUR")
                print(f"    Invertido:        {total_invested:>10,.2f} EUR")
                print(f"    P&L simple:       {sign}{pnl:>8,.2f} EUR ({sign}{pnl_pct:.1f}%)")
                etf_invested_total += total_invested
                etf_value_total += current_value
            else:
                etf_value_map[asset] = 0.0
                print(f"\n  {asset}: {total_units:.4f} u  ({len(trades_for)} operaciones)")
                print(f"    Precio no disponible (yfinance sin conexion). Invertido: {total_invested:,.2f} EUR")
                etf_invested_total += total_invested

    print(f"\n{'='*57}")
    print("TOTAL PORTFOLIO + ASIGNACION vs TARGET")
    print(f"{'='*57}")

    all_values: dict[str, float] = {
        "BTC": 0.0, "ETH": 0.0,
        "SP500": 0.0, "SEMICONDUCTORS": 0.0, "REALTY_INCOME": 0.0, "URANIUM": 0.0,
    }
    if btc_price_eur and btc_trades:
        s_btc = calculate_portfolio_status("BTC", btc_trades, btc_price_eur, 80_000/1.10, 20_000/1.10)
        all_values["BTC"] = s_btc["current_value_eur"]
    if eth_price_eur and eth_trades:
        s_eth = calculate_portfolio_status("ETH", eth_trades, eth_price_eur, 3_000/1.10, 1_000/1.10)
        all_values["ETH"] = s_eth["current_value_eur"]
    for asset, val in etf_value_map.items():
        if asset in all_values:
            all_values[asset] = val

    total_portfolio = sum(all_values.values())

    if btc_trades and not btc_price_eur:
        print("\n  [!] Precio BTC no disponible - BTC excluido del total (precio: 0)")
    if eth_trades and not eth_price_eur:
        print("  [!] Precio ETH no disponible - ETH excluido del total (precio: 0)")

    if total_portfolio > 0:
        THRESHOLD = 10.0
        print(f"\n  {'Activo':<16} {'Valor EUR':>10}  {'Actual%':>7}  {'Target%':>7}  {'Drift':>7}  Estado")
        print(f"  {'-'*16} {'-'*10}  {'-'*7}  {'-'*7}  {'-'*7}  ------")
        needs_rebalance = False
        for asset, target_pct in SPARPLAN_TARGETS.items():
            val = all_values.get(asset, 0.0)
            actual_pct = val / total_portfolio * 100
            drift = actual_pct - target_pct
            if abs(drift) > THRESHOLD:
                estado = "[REBALANCEAR]"
                needs_rebalance = True
            elif abs(drift) > THRESHOLD / 2:
                estado = "[WATCH]"
            else:
                estado = "[OK]"
            print(f"  {asset:<16} {val:>10,.0f}E  {actual_pct:>6.1f}%  {target_pct:>6.1f}%  {drift:>+6.1f}pp  {estado}")
        print(f"  {'TOTAL':<16} {total_portfolio:>10,.0f}E")
        if needs_rebalance:
            print(f"\n  Threshold de rebalanceo: >|{THRESHOLD:.0f}pp| de drift")
            print("  Research: rebalanceo anual mejora CAGR de 12.5% a 14.7% (datos 2018-2026)")
    else:
        total_invested_all = crypto_total_invested + etf_invested_total
        print(f"\n  Total invertido (precios no disponibles): {total_invested_all:,.2f} EUR")

    crypto_sign = "+" if crypto_unrealized >= 0 else ""
    print(f"\n  Crypto invertido: {crypto_total_invested:>10,.2f} EUR  |  Valor: {crypto_total_value:>10,.2f} EUR  |  PnL: {crypto_sign}{crypto_unrealized:,.2f} EUR")
    if etf_value_total > 0:
        etf_pnl = etf_value_total - etf_invested_total
        etf_sign = "+" if etf_pnl >= 0 else ""
        print(f"  ETF invertido:    {etf_invested_total:>10,.2f} EUR  |  Valor: {etf_value_total:>10,.2f} EUR  |  PnL: {etf_sign}{etf_pnl:,.2f} EUR")

    income_trades = [t for t in all_trades if t["side"] in ("dividend", "staking")]
    if income_trades:
        year_now = _dt.now().year
        income_year = [t for t in income_trades if hasattr(t["date"], "year") and t["date"].year == year_now]
        total_income = sum(t["price_eur"] for t in income_year)
        if total_income > 0:
            print(f"\n  Dividendos+Staking {year_now}: {total_income:,.2f} EUR (retencion estimada 19%: {total_income * 0.19:,.2f} EUR)")

    print("\n  Backup: python main.py portfolio export > mis_trades.csv")
    if not all_trades:
        print("\nNo hay operaciones registradas.")
        print("Usa: python main.py portfolio add-buy --asset BTC --units 0.001 --price-eur 45000 --source sparplan")


def cmd_tax_headroom(args: argparse.Namespace) -> None:
    """Show IRPF bracket headroom: realized gains vs margin to next bracket."""
    from datetime import datetime as _dt
    from data.database import init_db, get_session
    from data.models import UserTrade
    from data.portfolio import (
        calculate_portfolio_status, calculate_tax_report, compute_tax_headroom
    )
    from data.market_data import fetch_prices
    from alerts.discord_bot import (
        BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP,
        ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP,
    )

    year = args.year if args.year else _dt.now().year
    init_db()

    with get_session() as session:
        rows = session.query(UserTrade).all()
        all_trades = [
            {
                "date": t.date, "asset": t.asset, "asset_class": t.asset_class,
                "side": t.side, "units": t.units, "price_eur": t.price_eur,
                "fee_eur": t.fee_eur, "source": t.source, "notes": t.notes,
            }
            for t in rows
        ]

    if not all_trades:
        print("No hay operaciones registradas.")
        return

    report = calculate_tax_report(all_trades, year)
    realized = report["total_gain_eur"]
    realized_irpf = report["total_irpf_eur"]
    headroom_info = compute_tax_headroom(max(realized, 0.0))

    prices = fetch_prices()
    btc_price_eur = prices.get("btc_price_eur") or 0.0
    eth_price_eur = prices.get("eth_price_eur") or 0.0

    btc_trades = [t for t in all_trades if t["asset"] == "BTC"]
    eth_trades = [t for t in all_trades if t["asset"] == "ETH"]

    btc_unrealized = 0.0
    eth_unrealized = 0.0
    if btc_trades and btc_price_eur:
        s = calculate_portfolio_status("BTC", btc_trades, btc_price_eur,
                                       BTC_DCA_OUT_BASE, BTC_DCA_OUT_STEP)
        btc_unrealized = max(s["unrealized_gain_eur"], 0.0)
    if eth_trades and eth_price_eur:
        s = calculate_portfolio_status("ETH", eth_trades, eth_price_eur,
                                       ETH_DCA_OUT_BASE, ETH_DCA_OUT_STEP)
        eth_unrealized = max(s["unrealized_gain_eur"], 0.0)

    total_unrealized = btc_unrealized + eth_unrealized
    total_if_sold = realized + total_unrealized
    irpf_if_sold = calculate_tax_report(
        all_trades + [
            {"date": _dt.now(), "asset": "BTC", "side": "sell",
             "units": 0, "price_eur": 0, "fee_eur": 0, "asset_class": "crypto", "source": "manual", "notes": None},
        ],
        year
    )

    from data.portfolio import compute_spanish_tax
    irpf_if_sold_total = compute_spanish_tax(max(total_if_sold, 0.0))

    print("CryptoTrader - Margen IRPF {}".format(year))
    print("=" * 52)
    print()
    if realized <= 0:
        print("  Plusvalias realizadas {}: {:.0f} EUR (sin ganancias)".format(year, realized))
    else:
        print("  Plusvalias realizadas {}:  {:>10,.0f} EUR".format(year, realized))
        print("  IRPF sobre realizadas:    {:>10,.0f} EUR ({:.0f}%)".format(
            realized_irpf, report["effective_rate_pct"]))
        print("  Tramo actual:             {}".format(headroom_info["current_bracket_label"]))
        if headroom_info["headroom_eur"] is not None:
            print("  Margen hasta sig. tramo:  {:>10,.0f} EUR".format(headroom_info["headroom_eur"]))
        else:
            print("  Margen hasta sig. tramo:  (tramo maximo)")
    print()
    if total_unrealized > 0:
        print("  Plusvalias no realizadas (BTC+ETH): {:>8,.0f} EUR".format(total_unrealized))
        print("  Si vendieras todo BTC+ETH hoy:      {:>8,.0f} EUR adicionales".format(total_unrealized))
        print("  Total ganancias combinadas:          {:>8,.0f} EUR".format(total_if_sold))
        print("  IRPF estimado total:                 {:>8,.0f} EUR".format(irpf_if_sold_total))
    else:
        print("  Sin plusvalias no realizadas detectadas (precio no disponible o posicion en perdida).")
    print()

    # Discord notification if margin is below threshold
    if getattr(args, "notify", False) and realized > 0:
        headroom_eur = headroom_info.get("headroom_eur")
        threshold = getattr(args, "threshold", 2000)
        if headroom_eur is not None and headroom_eur < threshold:
            from alerts.discord_bot import (
                send_discord_message, _format_embed, _already_alerted, _log_alert,
                COOLDOWN_TAX_HEADROOM,
            )
            from data.database import init_db, get_session
            init_db()
            with get_session() as session:
                if not _already_alerted(session, "tax_headroom_low", COOLDOWN_TAX_HEADROOM):
                    details = (
                        "Margen IRPF: {:,.0f} EUR hasta tramo {} "
                        "(plusvalias realizadas: {:,.0f} EUR). "
                        "Revisa antes de ejecutar DCA-out.".format(
                            headroom_eur, headroom_info["current_bracket_label"], realized
                        )
                    )
                    embed = _format_embed("tax_headroom_low", "yellow", details)
                    sent = send_discord_message(embed)
                    _log_alert(session, "tax_headroom_low", "yellow",
                               btc_price_eur, eth_price_eur, headroom_eur, sent)
                    if sent:
                        print("  [Discord] Alerta enviada: margen {:,.0f} EUR < {:,.0f} EUR threshold.".format(
                            headroom_eur, threshold
                        ))
                    else:
                        print("  [Discord] Alerta en cooldown o fallo de envio.")
        elif headroom_eur is None:
            print("  [--notify] Tramo maximo alcanzado -- sin margen que notificar.")
        else:
            print("  [--notify] Margen {:,.0f} EUR >= threshold {:,.0f} EUR -- sin alerta.".format(
                headroom_eur, threshold
            ))
