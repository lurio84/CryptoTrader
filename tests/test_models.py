from datetime import datetime, timezone
from data.models import Candle, Trade, PortfolioSnapshot


def test_candle_creation(db_session):
    candle = Candle(
        symbol="BTC/USDT",
        timeframe="1h",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        open=42000.0,
        high=42500.0,
        low=41800.0,
        close=42300.0,
        volume=150.5,
    )
    db_session.add(candle)
    db_session.commit()

    result = db_session.query(Candle).first()
    assert result.symbol == "BTC/USDT"
    assert result.close == 42300.0
    assert result.volume == 150.5


def test_candle_unique_constraint(db_session):
    """Same symbol + timeframe + timestamp should not allow duplicates."""
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    c1 = Candle(symbol="BTC/USDT", timeframe="1h", timestamp=ts,
                open=42000, high=42500, low=41800, close=42300, volume=100)
    c2 = Candle(symbol="BTC/USDT", timeframe="1h", timestamp=ts,
                open=42000, high=42500, low=41800, close=42300, volume=100)
    db_session.add(c1)
    db_session.commit()
    db_session.add(c2)
    try:
        db_session.commit()
        assert False, "Should have raised IntegrityError"
    except Exception:
        db_session.rollback()


def test_trade_creation(db_session):
    trade = Trade(
        symbol="ETH/USDT",
        side="buy",
        price=2500.0,
        amount=0.5,
        cost=1250.0,
        fee=1.25,
        strategy="sma_crossover",
        mode="paper",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(trade)
    db_session.commit()

    result = db_session.query(Trade).first()
    assert result.side == "buy"
    assert result.cost == 1250.0
    assert result.strategy == "sma_crossover"


def test_portfolio_snapshot(db_session):
    snapshot = PortfolioSnapshot(
        total_value_usdt=500.0,
        cash_usdt=300.0,
        positions_value_usdt=200.0,
        unrealized_pnl=15.0,
        realized_pnl=5.0,
        drawdown_pct=0.02,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(snapshot)
    db_session.commit()

    result = db_session.query(PortfolioSnapshot).first()
    assert result.total_value_usdt == 500.0
    assert result.drawdown_pct == 0.02
