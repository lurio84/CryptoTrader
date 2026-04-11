"""Data commands: collect, update, backtest, sentiment, dca-backtest, info."""

import argparse
import sys
from datetime import datetime, timezone

from config.settings import settings
from data.database import init_db
from data.collector import DataCollector


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
