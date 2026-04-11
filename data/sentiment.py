import logging

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from config.settings import settings
from data.database import get_session
from data.models import SentimentData

logger = logging.getLogger(__name__)


class SentimentCollector:
    """Collects Fear & Greed Index and funding rates."""

    FNG_API_URL = "https://api.alternative.me/fng/"

    def __init__(self):
        import ccxt  # lazy-load: heavy library, not needed in CI/alerts
        exchange_class = getattr(ccxt, settings.default_exchange)
        self.exchange = exchange_class({"enableRateLimit": True})

    def fetch_fear_greed(self, days: int = 365) -> pd.DataFrame:
        """Fetch Fear & Greed Index history from alternative.me."""
        response = requests.get(
            self.FNG_API_URL,
            params={"limit": days, "format": "json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json().get("data", [])

        if not data:
            return pd.DataFrame()

        records = []
        for entry in data:
            records.append({
                "timestamp": datetime.fromtimestamp(
                    int(entry["timestamp"]), tz=timezone.utc
                ).replace(hour=0, minute=0, second=0),
                "fear_greed_value": int(entry["value"]),
                "fear_greed_label": entry.get("value_classification", ""),
            })

        df = pd.DataFrame(records)
        return df.sort_values("timestamp").reset_index(drop=True)

    def fetch_funding_rate(self, symbol: str = "BTC/USDT:USDT") -> float | None:
        """Fetch current funding rate for a symbol."""
        try:
            rate = self.exchange.fetch_funding_rate(symbol)
            return rate.get("fundingRate")
        except Exception as e:
            logger.warning("Failed to fetch funding rate for %s: %s", symbol, e)
            return None

    def fetch_funding_history(
        self, symbol: str = "BTC/USDT:USDT", since: datetime | None = None, limit: int = 1000
    ) -> pd.DataFrame:
        """Fetch historical funding rates (used by collect_all for DB population)."""
        try:
            since_ms = int(since.timestamp() * 1000) if since else None
            rates = self.exchange.fetch_funding_rate_history(
                symbol, since=since_ms, limit=limit
            )
            if not rates:
                return pd.DataFrame()

            records = []
            for r in rates:
                records.append({
                    "timestamp": datetime.fromtimestamp(
                        r["timestamp"] / 1000, tz=timezone.utc
                    ),
                    "funding_rate": r.get("fundingRate", 0),
                    "symbol": symbol,
                })
            return pd.DataFrame(records)
        except Exception as e:
            logger.warning("Failed to fetch funding history for %s: %s", symbol, e)
            return pd.DataFrame()

    def save_sentiment(self, df: pd.DataFrame) -> int:
        """Save sentiment data to database. Returns rows inserted."""
        if df.empty:
            return 0

        inserted = 0
        with get_session() as session:
            for _, row in df.iterrows():
                ts = row["timestamp"]
                if isinstance(ts, pd.Timestamp):
                    ts = ts.to_pydatetime()

                exists = session.execute(
                    select(SentimentData).where(SentimentData.timestamp == ts)
                ).scalar_one_or_none()

                if exists is None:
                    entry = SentimentData(
                        timestamp=ts,
                        fear_greed_value=row["fear_greed_value"],
                        fear_greed_label=row.get("fear_greed_label", ""),
                        funding_rate_btc=row.get("funding_rate_btc"),
                        funding_rate_eth=row.get("funding_rate_eth"),
                    )
                    session.add(entry)
                    inserted += 1
                elif pd.notna(row.get("funding_rate_btc")):
                    exists.funding_rate_btc = row["funding_rate_btc"]
                    exists.funding_rate_eth = row.get("funding_rate_eth")

        return inserted

    def load_sentiment(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> pd.DataFrame:
        """Load sentiment data from DB as DataFrame."""
        with get_session() as session:
            query = select(SentimentData)
            if since:
                query = query.where(SentimentData.timestamp >= since)
            if until:
                query = query.where(SentimentData.timestamp <= until)
            query = query.order_by(SentimentData.timestamp)

            rows = session.execute(query).scalars().all()

            if not rows:
                return pd.DataFrame()

            data = [
                {
                    "timestamp": r.timestamp,
                    "fear_greed_value": r.fear_greed_value,
                    "fear_greed_label": r.fear_greed_label,
                    "funding_rate_btc": r.funding_rate_btc,
                    "funding_rate_eth": r.funding_rate_eth,
                }
                for r in rows
            ]
        return pd.DataFrame(data)

    def collect_all(self, days: int = 365) -> int:
        """Fetch Fear & Greed + funding rates and save to DB."""
        print("  Fetching Fear & Greed Index...")
        fg_df = self.fetch_fear_greed(days=days)
        print(f"  {len(fg_df)} days of F&G data fetched")

        # Try to add funding rates (daily average)
        print("  Fetching BTC funding rate history...")
        since = datetime.now(timezone.utc) - timedelta(days=days)
        btc_funding = self.fetch_funding_history("BTC/USDT:USDT", since=since)
        eth_funding = self.fetch_funding_history("ETH/USDT:USDT", since=since)

        if not fg_df.empty and not btc_funding.empty:
            btc_daily = (
                btc_funding
                .set_index("timestamp")
                .resample("D")["funding_rate"]
                .mean()
                .reset_index()
            )
            btc_daily.columns = ["date", "funding_rate_btc"]
            btc_daily["date"] = btc_daily["date"].dt.normalize()

            fg_df["date"] = pd.to_datetime(fg_df["timestamp"]).dt.normalize()
            fg_df = fg_df.merge(btc_daily, on="date", how="left")
            fg_df.drop(columns=["date"], inplace=True)

        if not fg_df.empty and not eth_funding.empty:
            eth_daily = (
                eth_funding
                .set_index("timestamp")
                .resample("D")["funding_rate"]
                .mean()
                .reset_index()
            )
            eth_daily.columns = ["date", "funding_rate_eth"]
            eth_daily["date"] = eth_daily["date"].dt.normalize()

            fg_df["date"] = pd.to_datetime(fg_df["timestamp"]).dt.normalize()
            fg_df = fg_df.merge(eth_daily, on="date", how="left")
            fg_df.drop(columns=["date"], inplace=True)

        inserted = self.save_sentiment(fg_df)
        print(f"  {inserted} new sentiment rows saved")
        return inserted
