import ccxt
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import select

from config.settings import settings
from data.database import get_session
from data.models import Candle


class DataCollector:
    """Collects OHLCV data from exchanges via ccxt."""

    def __init__(self, exchange_id: str | None = None):
        exchange_id = exchange_id or settings.default_exchange
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange: ccxt.Exchange = exchange_class(
            {
                "apiKey": settings.binance.api_key or None,
                "secret": settings.binance.api_secret or None,
                "enableRateLimit": True,
            }
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles from exchange and return as DataFrame."""
        since_ms = int(since.timestamp() * 1000) if since else None
        raw = self.exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=since_ms, limit=limit
        )
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    def fetch_all_history(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch full history by paginating through the API."""
        all_data: list[pd.DataFrame] = []
        current_since = since

        while True:
            df = self.fetch_ohlcv(symbol, timeframe, since=current_since, limit=1000)
            if df.empty:
                break
            all_data.append(df)
            last_ts = df["timestamp"].iloc[-1].to_pydatetime()
            if current_since and last_ts <= current_since:
                break
            current_since = last_ts
            if len(df) < 1000:
                break

        if not all_data:
            return pd.DataFrame()

        result = pd.concat(all_data, ignore_index=True)
        return result.drop_duplicates(subset=["timestamp", "symbol", "timeframe"]).reset_index(
            drop=True
        )

    def save_candles(self, df: pd.DataFrame) -> int:
        """Save candles DataFrame to database. Returns number of new rows inserted."""
        if df.empty:
            return 0

        inserted = 0
        with get_session() as session:
            for _, row in df.iterrows():
                exists = session.execute(
                    select(Candle).where(
                        Candle.symbol == row["symbol"],
                        Candle.timeframe == row["timeframe"],
                        Candle.timestamp == row["timestamp"].to_pydatetime(),
                    )
                ).scalar_one_or_none()

                if exists is None:
                    candle = Candle(
                        symbol=row["symbol"],
                        timeframe=row["timeframe"],
                        timestamp=row["timestamp"].to_pydatetime(),
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        volume=row["volume"],
                    )
                    session.add(candle)
                    inserted += 1

        return inserted

    def load_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> pd.DataFrame:
        """Load candles from database as DataFrame."""
        with get_session() as session:
            query = select(Candle).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
            )
            if since:
                query = query.where(Candle.timestamp >= since)
            if until:
                query = query.where(Candle.timestamp <= until)
            query = query.order_by(Candle.timestamp)

            candles = session.execute(query).scalars().all()

            if not candles:
                return pd.DataFrame()

            data = [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "symbol": c.symbol,
                    "timeframe": c.timeframe,
                }
                for c in candles
            ]
        return pd.DataFrame(data)

    def get_last_candle_time(self, symbol: str, timeframe: str) -> datetime | None:
        """Get the timestamp of the most recent stored candle."""
        with get_session() as session:
            result = session.execute(
                select(Candle.timestamp)
                .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
                .order_by(Candle.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()
        return result

    def update_candles(self, symbol: str, timeframe: str = "1h") -> int:
        """Fetch and store only new candles since last stored."""
        last_time = self.get_last_candle_time(symbol, timeframe)
        df = self.fetch_all_history(symbol, timeframe, since=last_time)
        return self.save_candles(df)
