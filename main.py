"""CryptoTrader Bot - Entry point."""

import argparse
import sys
from datetime import datetime, timezone

from config.settings import settings
from data.database import init_db
from data.collector import DataCollector


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
            print(f"\n  Sentiment distribution on buy days:")
            print(f"    Mean F&G:   {fg_dist['mean']:.0f}")
            print(f"    Min F&G:    {fg_dist['min']:.0f}")
            print(f"    Max F&G:    {fg_dist['max']:.0f}")
            print(f"    Avg mult:   {result.buy_log['multiplier'].mean():.2f}x")


def cmd_check(args: argparse.Namespace) -> None:
    """Quick check: fetch all signals and show current status."""
    init_db()
    import requests as req

    print("CryptoTrader Advisor - Quick Check")
    print("=" * 55)

    # Prices
    try:
        resp = req.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        cg = resp.json()
        btc_price = cg["bitcoin"]["usd"]
        btc_change = cg["bitcoin"]["usd_24h_change"]
        eth_price = cg["ethereum"]["usd"]
        eth_change = cg["ethereum"].get("usd_24h_change", 0)
    except Exception:
        btc_price = btc_change = eth_price = eth_change = None

    # Fear & Greed
    try:
        fg = req.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()
        fg_val = int(fg["data"][0]["value"])
        fg_label = fg["data"][0]["value_classification"]
    except Exception:
        fg_val = fg_label = None

    # ETH MVRV
    try:
        mv = req.get("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
                      params={"assets": "eth", "metrics": "CapMVRVCur",
                              "frequency": "1d", "page_size": "1",
                              "paging_from": "end"}, timeout=10).json()
        mvrv = float(mv["data"][0]["CapMVRVCur"])
    except Exception:
        mvrv = None

    # Funding rate (live from OKX - no geo-restrictions from GitHub)
    try:
        fr = req.get(
            "https://www.okx.com/api/v5/public/funding-rate",
            params={"instId": "BTC-USDT-SWAP"},
            timeout=10,
        )
        fr.raise_for_status()
        fr_data = fr.json().get("data", [])
        funding = float(fr_data[0]["fundingRate"]) if fr_data else None
    except Exception:
        funding = None

    # Display
    print(f"\n  MARKET STATUS:")
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

    # Alerts
    print(f"\n  SIGNALS:")
    has_alert = False

    if btc_change is not None and btc_change <= -15:
        print(f"    [RED] BTC CRASH: {btc_change:.1f}% in 24h")
        print(f"          -> Buy extra 100-150 EUR of BTC in Trade Republic")
        has_alert = True

    if btc_change is not None and btc_change <= -10 and btc_change > -15:
        print(f"    [WATCH] BTC dropped {btc_change:.1f}% - monitoring for further drop")
        has_alert = True

    if funding is not None and funding < -0.0001:
        print(f"    [ORANGE] Negative funding ({funding*100:.4f}%)")
        print(f"          -> Bullish signal, consider extra BTC buy")
        has_alert = True

    if mvrv is not None and mvrv < 0.8:
        print(f"    [RED] ETH MVRV at {mvrv:.3f} (< 0.8) - deep value!")
        print(f"          -> Buy extra 100 EUR of ETH in Trade Republic")
        has_alert = True
    elif mvrv is not None and mvrv < 1.0:
        print(f"    [YELLOW] ETH MVRV at {mvrv:.3f} (< 1.0) - undervalued")
        print(f"          -> Consider increasing ETH Sparplan temporarily")
        has_alert = True

    # BTC DCA-out levels
    if btc_price is not None:
        btc_dca_base, btc_dca_step = 80_000, 20_000
        level = btc_dca_base
        level_num = 1
        while level <= 500_000:
            if btc_price >= level:
                print(f"    [ORANGE] BTC DCA-out nivel {level_num} (${level:,.0f}): vende el 3% de tus BTC en TR")
                has_alert = True
            level += btc_dca_step
            level_num += 1

    # ETH DCA-out levels
    if eth_price is not None:
        eth_dca_base, eth_dca_step = 3_000, 1_000
        level = eth_dca_base
        level_num = 1
        while level <= 50_000:
            if eth_price >= level:
                print(f"    [ORANGE] ETH DCA-out nivel {level_num} (${level:,.0f}): vende el 3% de tu ETH en TR")
                has_alert = True
            level += eth_dca_step
            level_num += 1

    if not has_alert:
        print(f"    [OK] No action needed. Sparplan running as usual.")

    if args.notify:
        from alerts.discord_bot import check_and_alert
        triggered = check_and_alert()
        if triggered:
            sent = sum(1 for a in triggered if a.get("sent"))
            print(f"\n  Discord alerts sent: {sent}/{len(triggered)}")
        else:
            print(f"\n  No alerts triggered.")

    print(f"\n{'='*55}")


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
        "dashboard": cmd_dashboard,
        "monitor": cmd_monitor,
        "info": cmd_info,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
