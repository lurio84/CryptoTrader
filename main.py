"""CryptoTrader Bot - Entry point."""

import argparse
import sys
from datetime import datetime, timezone

from config.settings import settings
from data.database import init_db
from data.collector import DataCollector

# ---------------------------------------------------------------------------
# Portfolio allocation constants (from CLAUDE.md Sparplan amounts)
# BTC: 8 EUR/week = 32/month, ETH: 2/week = 8/month
# SP500: 16/week = 64/month, SEMIS: 4/week = 16/month
# REALTY: 4/week = 16/month, URANIUM: 1/week = 4/month
# Total: 35 EUR/week = 140 EUR/month
# ---------------------------------------------------------------------------

SPARPLAN_MONTHLY = {
    "BTC":           32.0,
    "ETH":            8.0,
    "SP500":         64.0,
    "SEMICONDUCTORS":16.0,
    "REALTY_INCOME": 16.0,
    "URANIUM":        4.0,
}
_SPARPLAN_TOTAL = sum(SPARPLAN_MONTHLY.values())  # 140 EUR

# Target allocation % for each asset (used in rebalance and portfolio show)
SPARPLAN_TARGETS = {k: v / _SPARPLAN_TOTAL * 100 for k, v in SPARPLAN_MONTHLY.items()}

_CRYPTO_ASSETS = {"BTC", "ETH"}


def _detect_asset_class(asset_name: str) -> str:
    """Return 'crypto' for BTC/ETH, 'etf' for all other assets."""
    return "crypto" if asset_name.upper() in _CRYPTO_ASSETS else "etf"


def cmd_collect(args: argparse.Namespace) -> None:
    """Download and store historical OHLCV data."""
    init_db()
    collector = DataCollector()

    symbols = args.symbols or settings.default_symbols
    timeframe = args.timeframe or settings.default_timeframe

    for symbol in symbols:
        print(f"Collecting {symbol} ({timeframe})...")
        since = None
        if args.since:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        df = collector.fetch_all_history(symbol, timeframe, since=since)
        inserted = collector.save_candles(df)
        print(f"  {len(df)} candles fetched, {inserted} new rows saved")


def cmd_update(args: argparse.Namespace) -> None:
    """Update candles with latest data."""
    init_db()
    collector = DataCollector()

    symbols = args.symbols or settings.default_symbols
    timeframe = args.timeframe or settings.default_timeframe

    for symbol in symbols:
        print(f"Updating {symbol} ({timeframe})...")
        inserted = collector.update_candles(symbol, timeframe)
        print(f"  {inserted} new candles added")


STRATEGIES = {
    "sma": "strategies.sma_crossover:SMACrossover",
    "rsi": "strategies.rsi_mean_reversion:RSIMeanReversion",
    "bollinger": "strategies.bollinger_breakout:BollingerBreakout",
}


def _load_strategy(name: str):
    """Dynamically load a strategy class by short name."""
    if name not in STRATEGIES:
        print(f"Unknown strategy: {name}. Available: {', '.join(STRATEGIES)}")
        sys.exit(1)
    module_path, class_name = STRATEGIES[name].rsplit(":", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def cmd_backtest(args: argparse.Namespace) -> None:
    """Run backtest on historical data."""
    from backtesting.data_loader import load_backtest_data
    from backtesting.engine import BacktestEngine

    symbol = args.symbol or settings.default_symbols[0]
    timeframe = args.timeframe or settings.default_timeframe
    capital = args.capital or 500.0
    strategy_names = args.strategies or list(STRATEGIES.keys())

    print(f"Loading data for {symbol} ({timeframe})...")
    df = load_backtest_data(symbol, timeframe, since=args.since, until=args.until)
    print(f"  {len(df)} candles loaded")

    engine = BacktestEngine(initial_capital=capital)

    for name in strategy_names:
        strategy = _load_strategy(name)
        print(f"\nRunning backtest: {strategy.name}...")
        result = engine.run(df, strategy)
        result.print_summary()


def cmd_sentiment(args: argparse.Namespace) -> None:
    """Download sentiment data (Fear & Greed + funding rates)."""
    init_db()
    from data.sentiment import SentimentCollector

    collector = SentimentCollector()
    days = 365
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")
        days = (datetime.now() - since).days + 1

    print(f"Collecting sentiment data ({days} days)...")
    collector.collect_all(days=days)


def cmd_dca_backtest(args: argparse.Namespace) -> None:
    """Run DCA backtest: Smart DCA vs Fixed DCA vs Buy & Hold."""
    init_db()
    from backtesting.data_loader import load_backtest_data
    from backtesting.dca_engine import DCABacktestEngine
    from data.sentiment import SentimentCollector

    symbols = args.symbols or settings.default_symbols
    timeframe = args.timeframe or settings.default_timeframe

    # Load sentiment
    sent_collector = SentimentCollector()
    since_dt = None
    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    df_sentiment = sent_collector.load_sentiment(since=since_dt)

    if df_sentiment.empty:
        print("No sentiment data. Run 'python main.py sentiment' first.")
        sys.exit(1)

    print(f"Sentiment data: {len(df_sentiment)} days loaded")

    engine = DCABacktestEngine()

    for symbol in symbols:
        print(f"\nLoading {symbol} ({timeframe})...")
        df_candles = load_backtest_data(symbol, timeframe, since=args.since)
        print(f"  {len(df_candles)} candles loaded")

        result = engine.run(df_candles, df_sentiment, symbol=symbol)
        print(result.summary())

        if not result.buy_log.empty:
            fg_dist = result.buy_log["fear_greed"].describe()
            print("\n  Sentiment distribution on buy days:")
            print(f"    Mean F&G:   {fg_dist['mean']:.0f}")
            print(f"    Min F&G:    {fg_dist['min']:.0f}")
            print(f"    Max F&G:    {fg_dist['max']:.0f}")
            print(f"    Avg mult:   {result.buy_log['multiplier'].mean():.2f}x")


def _halving_cycle_info() -> dict:
    """Return current halving cycle phase info.
    Research3: fase mas debil es meses 18-24 post-halving (30d=-7.2% vs baseline).
    Halving abril 2024 -> zona de riesgo: octubre 2025 - abril 2026.
    """
    from datetime import date as _date
    last_halving = _date(2024, 4, 19)
    today = _date.today()
    days_elapsed = (today - last_halving).days
    months_elapsed = days_elapsed / 30.44
    in_risk_zone = 18 <= months_elapsed < 24
    return {
        "months_elapsed": months_elapsed,
        "in_risk_zone": in_risk_zone,
        "halving_date": "abril 2024",
    }


def cmd_check(args: argparse.Namespace) -> None:
    """Quick check: fetch all signals and show current status."""
    init_db()
    from data.market_data import fetch_prices, fetch_mvrv, fetch_funding_rate, fetch_fear_greed
    from alerts.discord_bot import (
        BTC_CRASH_THRESHOLD, FUNDING_RATE_THRESHOLD,
        ETH_MVRV_CRITICAL, ETH_MVRV_LOW,
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

    # Display
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
        print(f"    ETH MVRV: {mvrv:.3f}")
    if btc_mvrv is not None:
        print(f"    BTC MVRV: {btc_mvrv:.3f}  (informativo, no es señal de venta)")

    # Halving cycle
    hc = _halving_cycle_info()
    print("\n  CICLO HALVING:")
    print(f"    Mes {hc['months_elapsed']:.1f}/48 desde halving {hc['halving_date']}")
    if hc["in_risk_zone"]:
        print("    [WATCH] Zona de menor retorno historico (meses 18-24): -7.2% a 30d vs baseline")
        print("            Informativo: continua el Sparplan normal, no vender por este motivo")
    else:
        print("    [OK] Fuera de zona de riesgo del ciclo")

    # Alerts
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

    if mvrv is not None and mvrv < ETH_MVRV_CRITICAL:
        print(f"    [RED] ETH MVRV at {mvrv:.3f} (< {ETH_MVRV_CRITICAL}) - deep value!")
        print("          -> Buy extra 100 EUR of ETH in Trade Republic")
        has_alert = True
    elif mvrv is not None and mvrv < ETH_MVRV_LOW:
        print(f"    [YELLOW] ETH MVRV at {mvrv:.3f} (< {ETH_MVRV_LOW}) - undervalued")
        print("          -> Consider increasing ETH Sparplan temporarily")
        has_alert = True

    # BTC DCA-out levels
    if btc_price is not None:
        level = BTC_DCA_OUT_BASE
        level_num = 1
        while level <= BTC_DCA_OUT_MAX:
            if btc_price >= level:
                print(f"    [ORANGE] BTC DCA-out nivel {level_num} (${level:,.0f}): vende el {BTC_DCA_OUT_PCT}% de tus BTC en TR")
                has_alert = True
            level += BTC_DCA_OUT_STEP
            level_num += 1

    # ETH DCA-out levels
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
        triggered = check_and_alert()
        if triggered:
            sent = sum(1 for a in triggered if a.get("sent"))
            print(f"\n  Discord alerts sent: {sent}/{len(triggered)}")
        else:
            print("\n  No alerts triggered.")

    print(f"\n{'='*55}")


def cmd_portfolio(args: argparse.Namespace) -> None:
    """Personal portfolio tracker with FIFO cost basis and IRPF estimation."""
    init_db()
    import requests as req
    from datetime import datetime as _dt
    from sqlalchemy import select as _select
    from data.models import UserTrade
    from data.portfolio import calculate_portfolio_status, trades_to_csv
    from data.database import get_session

    sub = args.portfolio_cmd

    if sub == "add-buy" or sub == "add-sell":
        side = "buy" if sub == "add-buy" else "sell"
        trade_date = _dt.strptime(args.date, "%Y-%m-%d") if args.date else _dt.now()
        asset_upper = args.asset.upper()
        trade = UserTrade(
            date=trade_date,
            asset=asset_upper,
            asset_class=_detect_asset_class(asset_upper),
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

    # Fetch current prices for show command
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

    # -----------------------------------------------------------------------
    # show (default): 3 sections -- Crypto, ETF, Total portfolio
    # -----------------------------------------------------------------------
    print("PORTFOLIO PERSONAL")
    print("=" * 57)

    crypto_total_invested = 0.0
    crypto_total_value = 0.0
    crypto_unrealized = 0.0
    crypto_irpf = 0.0

    # --- SECTION 1: Crypto (FIFO + IRPF completo) --------------------------
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
        if s["next_dca_level_eur"]:
            pct_to_level = (s["next_dca_level_eur"] / price_eur - 1) * 100
            print(f"    Proximo DCA-out:  {asset} a {s['next_dca_level_eur']:,.0f} EUR ({pct_to_level:+.1f}%) -> vende {s['next_dca_units']:.6f} {asset} ({s['next_dca_eur']:,.0f} EUR)")
        crypto_total_invested += s["total_invested_eur"]
        crypto_total_value += s["current_value_eur"]
        crypto_unrealized += s["unrealized_gain_eur"]
        crypto_irpf += s["irpf_estimate_eur"]

    # --- SECTION 2: ETF (coste medio simple, sin FIFO complejo) ------------
    print("\n[ ETF / ACCIONES ]")
    etf_value_map: dict[str, float] = {}   # asset -> current value EUR
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
            # Price: from yfinance (asset name must match ETF_TICKERS key)
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

    # --- SECTION 3: Total portfolio + allocation vs target -----------------
    print(f"\n{'='*57}")
    print("TOTAL PORTFOLIO + ASIGNACION vs TARGET")
    print(f"{'='*57}")

    # Build value map for all 6 assets
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

    # Warn explicitly when crypto prices were unavailable so the user knows
    # the TOTAL below is understated (crypto counted as 0).
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

    # Summary lines
    crypto_sign = "+" if crypto_unrealized >= 0 else ""
    print(f"\n  Crypto invertido: {crypto_total_invested:>10,.2f} EUR  |  Valor: {crypto_total_value:>10,.2f} EUR  |  PnL: {crypto_sign}{crypto_unrealized:,.2f} EUR")
    if etf_value_total > 0:
        etf_pnl = etf_value_total - etf_invested_total
        etf_sign = "+" if etf_pnl >= 0 else ""
        print(f"  ETF invertido:    {etf_invested_total:>10,.2f} EUR  |  Valor: {etf_value_total:>10,.2f} EUR  |  PnL: {etf_sign}{etf_pnl:,.2f} EUR")
    print("\n  Backup: python main.py portfolio export > mis_trades.csv")
    if not all_trades:
        print("\nNo hay operaciones registradas.")
        print("Usa: python main.py portfolio add-buy --asset BTC --units 0.001 --price-eur 45000 --source sparplan")


def cmd_digest(args: argparse.Namespace) -> None:
    """Send weekly digest to Discord (or print preview without --notify)."""
    init_db()
    if args.notify:
        from alerts.discord_bot import send_weekly_digest
        sent = send_weekly_digest()
        if sent:
            print("Weekly digest sent to Discord.")
        else:
            print("Digest not sent (already sent within last 6 days, or webhook not configured).")
    else:
        # Preview mode: show what would be sent
        from datetime import date as _date
        last_halving = _date(2024, 4, 19)
        months = (_date.today() - last_halving).days / 30.44
        print("CryptoTrader - Digest Preview (use --notify to send)")
        print("=" * 55)
        print(f"  Ciclo halving: mes {months:.1f}/48 desde halving abr-2024")
        in_risk = 18 <= months < 24
        if in_risk:
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


def cmd_rebalance(args: argparse.Namespace) -> None:
    """Calculate if annual portfolio rebalancing is needed (all 6 assets)."""
    import requests as req

    THRESHOLD_PP = 10.0

    print("CryptoTrader - Rebalanceo Anual (6 activos)")
    print("=" * 60)

    # Fetch current EUR prices for crypto
    try:
        resp = req.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "eur"},
            timeout=10,
        )
        resp.raise_for_status()
        cg = resp.json()
        btc_eur = cg["bitcoin"]["eur"]
        eth_eur = cg["ethereum"]["eur"]
    except Exception as e:
        print(f"Error fetching prices from CoinGecko: {e}")
        sys.exit(1)

    # Compute values for all 6 assets
    btc_value  = args.btc * btc_eur
    eth_value  = args.eth * eth_eur
    sp500_value = args.sp500
    semis_value = args.semis
    realty_value = args.realty
    uranium_value = args.uranium

    values = {
        "BTC":           btc_value,
        "ETH":           eth_value,
        "SP500":         sp500_value,
        "SEMICONDUCTORS":semis_value,
        "REALTY_INCOME": realty_value,
        "URANIUM":       uranium_value,
    }
    total = sum(values.values())

    if total <= 0:
        print("Error: el total de la cartera es 0.")
        sys.exit(1)

    print("\n  Precios crypto actuales:")
    print(f"    BTC: {btc_eur:>10,.0f} EUR  |  ETH: {eth_eur:>10,.0f} EUR")

    print(f"\n  {'Activo':<16} {'Valor EUR':>10}  {'Actual%':>7}  {'Target%':>7}  {'Drift':>7}  Estado")
    print(f"  {'-'*16} {'-'*10}  {'-'*7}  {'-'*7}  {'-'*7}  ------")

    actions = []

    for asset, target_pct in SPARPLAN_TARGETS.items():
        val = values.get(asset, 0.0)
        actual_pct = val / total * 100
        drift = actual_pct - target_pct
        if abs(drift) > THRESHOLD_PP:
            estado = "[REBALANCEAR]"
            actions.append((asset, drift, val, target_pct, total))
        elif abs(drift) > THRESHOLD_PP / 2:
            estado = "[WATCH]"
        else:
            estado = "[OK]"
        print(f"  {asset:<16} {val:>10,.0f}E  {actual_pct:>6.1f}%  {target_pct:>6.1f}%  {drift:>+6.1f}pp  {estado}")

    print(f"  {'TOTAL':<16} {total:>10,.0f}E")

    if actions:
        print(f"\n  Acciones recomendadas (threshold: |drift| > {THRESHOLD_PP:.0f}pp):")
        for asset, drift, val, target_pct, total_v in actions:
            target_value = total_v * target_pct / 100
            if drift > 0:
                diff_eur = val - target_value
                print(f"    [VENDER] {asset}: sobrepesado {drift:+.1f}pp -> vende ~{diff_eur:,.0f} EUR en TR")
                print("             Reinvertir en activos bajo su target")
            else:
                diff_eur = target_value - val
                print(f"    [COMPRAR] {asset}: infrapesado {drift:.1f}pp -> compra ~{diff_eur:,.0f} EUR extra en TR")
        print("\n  Costes: ~1 EUR flat fee por operacion en TR")
        print("  IRPF: tributa la plusvalia en ventas (precio venta - coste FIFO)")
        print("  Research: rebalanceo anual mejora CAGR de 12.5%% a 14.7%% (datos 2018-2026)")
    else:
        print("\n  Cartera dentro de rangos normales. No es necesario rebalancear.")

    print(f"\n{'='*60}")


def cmd_retirement_plan(args: argparse.Namespace) -> None:
    """Monte Carlo retirement projection using bootstrap resampling of historical returns."""
    from analysis.monte_carlo import run_monte_carlo

    n_years = args.retire_age - args.age
    if n_years <= 0:
        print("Error: retire-age debe ser mayor que age.")
        sys.exit(1)

    print("Monte Carlo - Proyeccion de Jubilacion")
    print("=" * 60)
    print(f"  Edad actual: {args.age}  |  Jubilacion: {args.retire_age}  |  Horizonte: {n_years} anos")
    print(f"  DCA mensual: {args.monthly:.0f} EUR  |  Objetivo: {args.target_eur:,.0f} EUR")
    print(f"  Simulaciones: {args.simulations:,}  |  Metodo: bootstrap resampling retornos historicos")
    print("  Activos: BTC/ETH (yfinance), SPY/SOXX/O/URA (yfinance)")
    print()
    print("  Ejecutando simulacion (puede tardar ~20-30s)...")

    result = run_monte_carlo(
        n_years=n_years,
        monthly_contribution_eur=args.monthly,
        target_eur=args.target_eur,
        n_simulations=args.simulations,
        current_portfolio_eur=0.0,
    )

    print()
    print(f"  {'Ano':>3}  {'Edad':>4}  {'P10 (EUR)':>12}  {'P25 (EUR)':>12}  {'Mediana':>12}  {'P75 (EUR)':>12}  {'P90 (EUR)':>12}")
    print(f"  {'-'*3}  {'-'*4}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")

    step = max(1, n_years // 15)
    for i, yr in enumerate(result.years):
        if yr % step != 0 and yr != n_years:
            continue
        age_at = args.age + yr
        print(
            f"  {yr:>3}  {age_at:>4}  "
            f"{result.p10[i]:>11,.0f}E  "
            f"{result.p25[i]:>11,.0f}E  "
            f"{result.p50[i]:>11,.0f}E  "
            f"{result.p75[i]:>11,.0f}E  "
            f"{result.p90[i]:>11,.0f}E"
        )

    print(f"\n{'='*60}")
    print(f"RESUMEN AL RETIRO (ano {n_years}, edad {args.retire_age})")
    print(f"{'='*60}")
    print(f"  Mediana cartera:        {result.median_at_retirement:>12,.0f} EUR")
    print(f"  Prob. alcanzar objetivo:{result.prob_reach_target * 100:>11.1f}%")
    print(f"  Retiro mensual (4%):    {result.safe_withdrawal_rate_4pct:>12,.0f} EUR/mes")
    print(f"  Datos historicos:       {result.data_start_year}-{result.data_end_year}  "
          f"({result.data_months} meses alineados)")
    print("\n  NOTA: Proyeccion basada en retornos historicos. El futuro puede diferir.")
    print("  Sin impuestos intermedios, sin inflacion ajustada.")
    print(f"  Dataset limitado a {result.data_start_year}-{result.data_end_year} "
          f"(inicio datos ETH). Incluye bull run crypto 2020-2021 y 2023-2024.")
    print(f"{'='*60}")


def cmd_info(args: argparse.Namespace) -> None:
    """Show current configuration and status."""
    print("CryptoTrader Bot v0.1.0")
    print(f"  Mode:      {settings.trading_mode}")
    print(f"  Exchange:  {settings.default_exchange}")
    print(f"  Symbols:   {', '.join(settings.default_symbols)}")
    print(f"  Timeframe: {settings.default_timeframe}")
    print(f"  Database:  {settings.database_url}")
    print(f"  Maker fee: {settings.maker_fee_pct * 100}%")
    print(f"  Taker fee: {settings.taker_fee_pct * 100}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader Bot")
    subparsers = parser.add_subparsers(dest="command")

    # collect
    p_collect = subparsers.add_parser("collect", help="Download historical data")
    p_collect.add_argument("--symbols", nargs="+", help="Trading pairs (e.g. BTC/USDT ETH/USDT)")
    p_collect.add_argument("--timeframe", help="Candle timeframe (e.g. 1h, 4h)")
    p_collect.add_argument("--since", help="Start date YYYY-MM-DD")

    # update
    p_update = subparsers.add_parser("update", help="Update with latest candles")
    p_update.add_argument("--symbols", nargs="+")
    p_update.add_argument("--timeframe")

    # backtest
    p_bt = subparsers.add_parser("backtest", help="Run strategy backtest")
    p_bt.add_argument("--symbol", help="Trading pair (e.g. BTC/USDT)")
    p_bt.add_argument("--timeframe", help="Candle timeframe (e.g. 1h, 4h)")
    p_bt.add_argument("--since", help="Start date YYYY-MM-DD")
    p_bt.add_argument("--until", help="End date YYYY-MM-DD")
    p_bt.add_argument("--capital", type=float, help="Initial capital in USDT (default: 500)")
    p_bt.add_argument("--strategies", nargs="+", choices=list(STRATEGIES.keys()),
                       help="Strategies to test (default: all)")

    # sentiment
    p_sent = subparsers.add_parser("sentiment", help="Download sentiment data")
    p_sent.add_argument("--since", help="Start date YYYY-MM-DD")

    # dca-backtest
    p_dca = subparsers.add_parser("dca-backtest", help="Run DCA backtest")
    p_dca.add_argument("--symbols", nargs="+", help="Trading pairs")
    p_dca.add_argument("--timeframe", help="Candle timeframe")
    p_dca.add_argument("--since", help="Start date YYYY-MM-DD")

    # check
    p_check = subparsers.add_parser("check", help="Quick signal check")
    p_check.add_argument("--notify", action="store_true", help="Send Discord alert if signal triggered")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Run web dashboard")
    p_dash.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Run alert monitor")
    p_mon.add_argument("--interval", type=int, default=1, help="Check interval in hours (default: 1)")

    # rebalance
    p_reb = subparsers.add_parser("rebalance", help="Check if annual rebalancing is needed (all 6 assets)")
    p_reb.add_argument("--btc", type=float, required=True, help="BTC holdings in units (e.g. 0.05)")
    p_reb.add_argument("--eth", type=float, required=True, help="ETH holdings in units (e.g. 0.5)")
    p_reb.add_argument("--sp500", type=float, default=0.0, help="S&P500 ETF current value in EUR")
    p_reb.add_argument("--semis", type=float, default=0.0, help="Semiconductors ETF current value in EUR")
    p_reb.add_argument("--realty", type=float, default=0.0, help="Realty Income current value in EUR")
    p_reb.add_argument("--uranium", type=float, default=0.0, help="Uranium ETF current value in EUR")

    # portfolio
    p_port = subparsers.add_parser("portfolio", help="Personal portfolio tracker (FIFO / IRPF)")
    port_sub = p_port.add_subparsers(dest="portfolio_cmd")

    _all_assets = [
        "BTC", "ETH",
        "SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM",
        "btc", "eth",
        "sp500", "semiconductors", "realty_income", "uranium",
    ]
    _trade_sources = ["sparplan", "crash_buy", "mvrv_buy", "dca_out", "rebalance", "manual"]

    # portfolio add-buy
    p_buy = port_sub.add_parser("add-buy", help="Register a buy trade")
    p_buy.add_argument("--asset", required=True, choices=_all_assets,
                       help="Asset: BTC, ETH, SP500, SEMICONDUCTORS, REALTY_INCOME, URANIUM")
    p_buy.add_argument("--units", type=float, required=True, help="Units bought (e.g. 0.001 for BTC, 1.5 for SPY)")
    p_buy.add_argument("--price-eur", type=float, required=True, help="Price in EUR per unit")
    p_buy.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    p_buy.add_argument("--fee-eur", type=float, default=0.0, help="Fee in EUR (default 0; use 1 for manual TR buy)")
    p_buy.add_argument("--source", default="sparplan", choices=_trade_sources, help="Origin of the trade")
    p_buy.add_argument("--notes", help="Optional comment")

    # portfolio add-sell
    p_sell = port_sub.add_parser("add-sell", help="Register a sell trade")
    p_sell.add_argument("--asset", required=True, choices=_all_assets,
                        help="Asset: BTC, ETH, SP500, SEMICONDUCTORS, REALTY_INCOME, URANIUM")
    p_sell.add_argument("--units", type=float, required=True, help="Units sold")
    p_sell.add_argument("--price-eur", type=float, required=True, help="Price in EUR per unit")
    p_sell.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    p_sell.add_argument("--fee-eur", type=float, default=1.0, help="Fee in EUR (default 1 EUR flat in TR)")
    p_sell.add_argument("--source", default="dca_out", choices=_trade_sources)
    p_sell.add_argument("--notes", help="Optional comment")

    # portfolio show
    port_sub.add_parser("show", help="Show portfolio status with FIFO P&L and IRPF estimate")

    # portfolio history
    port_sub.add_parser("history", help="List all registered trades")

    # portfolio export
    port_sub.add_parser("export", help="Export all trades as CSV (for backup)")

    # digest
    p_digest = subparsers.add_parser("digest", help="Send weekly digest to Discord")
    p_digest.add_argument("--notify", action="store_true", help="Actually send to Discord (default: preview only)")

    # retirement-plan
    p_ret = subparsers.add_parser("retirement-plan", help="Monte Carlo retirement projection")
    p_ret.add_argument("--age",         type=int,   default=30,         help="Edad actual (default 30)")
    p_ret.add_argument("--retire-age",  type=int,   default=65,         help="Edad de jubilacion (default 65)")
    p_ret.add_argument("--target-eur",  type=float, default=1_000_000,  help="Objetivo de cartera en EUR (default 1000000)")
    p_ret.add_argument("--monthly",     type=float, default=140.0,      help="DCA mensual en EUR (default 140)")
    p_ret.add_argument("--simulations", type=int,   default=5000,       help="Numero de simulaciones (default 5000)")

    # info
    subparsers.add_parser("info", help="Show configuration")

    args = parser.parse_args()

    commands = {
        "collect": cmd_collect,
        "update": cmd_update,
        "backtest": cmd_backtest,
        "sentiment": cmd_sentiment,
        "dca-backtest": cmd_dca_backtest,
        "check": cmd_check,
        "portfolio": cmd_portfolio,
        "digest": cmd_digest,
        "dashboard": cmd_dashboard,
        "monitor": cmd_monitor,
        "rebalance": cmd_rebalance,
        "retirement-plan": cmd_retirement_plan,
        "info": cmd_info,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
