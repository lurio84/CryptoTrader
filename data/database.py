from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from config.settings import settings
from data.models import Base


engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def _migrate_user_trade() -> None:
    """Add asset_class column to user_trade if it does not exist yet.

    Idempotent: runs PRAGMA table_info to check before altering.
    Safe for existing DBs with data -- ALTER TABLE preserves all rows
    and backfills asset_class = 'crypto' for pre-existing records.
    """
    with engine.connect() as conn:
        info = conn.execute(text("PRAGMA table_info(user_trade)")).fetchall()
        existing_cols = [row[1] for row in info]
        if "asset_class" not in existing_cols:
            conn.execute(text(
                "ALTER TABLE user_trade ADD COLUMN asset_class TEXT NOT NULL DEFAULT 'crypto'"
            ))
            conn.commit()


def _ensure_indexes() -> None:
    """Create additional indexes on existing tables if missing (idempotent)."""
    _indexes = {
        "ix_alert_log_alert_type": "CREATE INDEX IF NOT EXISTS ix_alert_log_alert_type ON alert_log(alert_type)",
        "ix_alert_log_timestamp":  "CREATE INDEX IF NOT EXISTS ix_alert_log_timestamp ON alert_log(timestamp)",
        "ix_alert_log_type_ts":    "CREATE INDEX IF NOT EXISTS ix_alert_log_type_ts ON alert_log(alert_type, timestamp)",
        "ix_user_portfolio_snapshot_snapshot_date": "CREATE INDEX IF NOT EXISTS ix_user_portfolio_snapshot_snapshot_date ON user_portfolio_snapshot(snapshot_date)",
        "ix_user_trade_asset_date": "CREATE INDEX IF NOT EXISTS ix_user_trade_asset_date ON user_trade(asset, date)",
    }
    with engine.connect() as conn:
        for stmt in _indexes.values():
            conn.execute(text(stmt))
        conn.commit()


def init_db() -> None:
    """Create all tables if they don't exist, then apply pending migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate_user_trade()
    _ensure_indexes()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
