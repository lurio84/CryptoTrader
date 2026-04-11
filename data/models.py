from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Candle(Base):
    """OHLCV candle data from exchange."""

    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
    )

    def __repr__(self) -> str:
        return f"<Candle {self.symbol} {self.timeframe} {self.timestamp} C={self.close}>"


class Trade(Base):
    """Executed trade (paper or real)."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)  # "buy" or "sell"
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)  # price * amount
    fee = Column(Float, nullable=False, default=0.0)
    strategy = Column(String, nullable=False)
    mode = Column(String, nullable=False, default="paper")  # "paper" or "live"
    order_id = Column(String, nullable=True)  # exchange order ID (live only)
    pnl = Column(Float, nullable=True)  # P&L for closing trades
    timestamp = Column(DateTime, nullable=False, default=func.now())
    created_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self) -> str:
        return f"<Trade {self.side} {self.amount} {self.symbol} @ {self.price}>"


class PortfolioSnapshot(Base):
    """Periodic snapshot of portfolio state."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_value_usdt = Column(Float, nullable=False)
    cash_usdt = Column(Float, nullable=False)
    positions_value_usdt = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    drawdown_pct = Column(Float, nullable=False, default=0.0)
    timestamp = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self) -> str:
        return f"<Portfolio {self.timestamp} total={self.total_value_usdt} USDT>"


class SentimentData(Base):
    """Daily sentiment data (Fear & Greed Index + funding rates)."""

    __tablename__ = "sentiment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    fear_greed_value = Column(Integer, nullable=False)  # 0-100
    fear_greed_label = Column(String, nullable=True)
    funding_rate_btc = Column(Float, nullable=True)
    funding_rate_eth = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("timestamp", name="uq_sentiment_ts"),
    )

    def __repr__(self) -> str:
        return f"<Sentiment {self.timestamp} F&G={self.fear_greed_value} ({self.fear_greed_label})>"


class AlertLog(Base):
    """Log of triggered alerts to avoid duplicates."""

    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    alert_type = Column(String, nullable=False)  # "btc_crash", "funding_negative", "mvrv_low"
    severity = Column(String, nullable=False)  # "red", "orange", "yellow"
    message = Column(String, nullable=False)
    btc_price = Column(Float, nullable=True)
    eth_price = Column(Float, nullable=True)
    metric_value = Column(Float, nullable=True)  # the value that triggered the alert
    notified = Column(Integer, nullable=False, default=0)  # 1 if discord sent

    def __repr__(self) -> str:
        return f"<AlertLog {self.alert_type} {self.severity} {self.timestamp}>"


class UserTrade(Base):
    """Personal trade register for FIFO cost basis and IRPF tracking.

    Stored locally only - never committed to GitHub or synced to CI.
    Use 'python main.py portfolio export' to backup as CSV.
    """

    __tablename__ = "user_trade"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)            # Date of the trade
    asset = Column(String, nullable=False)             # "BTC" or "ETH"
    side = Column(String, nullable=False)              # "buy" or "sell"
    units = Column(Float, nullable=False)              # Units of crypto
    price_eur = Column(Float, nullable=False)          # Price in EUR at time of trade
    fee_eur = Column(Float, nullable=False, default=0.0)  # Fee in EUR (0 for Sparplan, 1 for manual TR)
    source = Column(String, nullable=False, default="manual")
    # Source options: sparplan | crash_buy | mvrv_buy | dca_out | rebalance | manual
    notes = Column(String, nullable=True)              # Free-form comment
    created_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self) -> str:
        return f"<UserTrade {self.side} {self.units:.6f} {self.asset} @ {self.price_eur:.2f} EUR ({self.source})>"
