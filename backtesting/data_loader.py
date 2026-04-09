import pandas as pd
from datetime import datetime, timezone

from data.collector import DataCollector
from data.database import init_db


def load_backtest_data(
    symbol: str,
    timeframe: str = "1h",
    since: str | None = None,
    until: str | None = None,
) -> pd.DataFrame:
    """Load candle data from DB for backtesting.

    If no data in DB, fetches from exchange first.
    """
    init_db()
    collector = DataCollector()

    since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc) if since else None
    until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc) if until else None

    df = collector.load_candles(symbol, timeframe, since=since_dt, until=until_dt)

    if df.empty:
        print(f"No local data for {symbol}. Fetching from exchange...")
        fetched = collector.fetch_all_history(symbol, timeframe, since=since_dt)
        collector.save_candles(fetched)
        df = collector.load_candles(symbol, timeframe, since=since_dt, until=until_dt)

    if df.empty:
        raise ValueError(f"No data available for {symbol} ({timeframe})")

    # Ensure timestamp is datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)
