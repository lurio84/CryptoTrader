"""Tests for dashboard/app.py FastAPI endpoints.

Mocking strategy:
- External API calls (fetch_prices, fetch_mvrv, etc.) patched at dashboard.app module level.
- get_session patched to use the in-memory db_session fixture.
- init_db patched to no-op.

Pattern mirrors test_discord_bot.py: patch as close to usage as possible.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data.models import AlertLog, Base, UserPortfolioSnapshot


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


def _normal_prices():
    return {
        "btc_price": 85_000.0,
        "btc_price_eur": 78_000.0,
        "btc_change_24h": 1.5,
        "eth_price": 3_200.0,
        "eth_price_eur": 2_940.0,
        "eth_change_24h": 0.8,
    }


def _normal_fg():
    return {"fear_greed_value": 55, "fear_greed_label": "Greed"}


def _make_test_engine():
    # StaticPool + check_same_thread=False: all threads share one connection.
    # Required for FastAPI sync routes (run in threadpool) to see test data.
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def db_session():
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    """TestClient backed by the same db_session, all external APIs mocked."""
    from dashboard.app import app

    session_ctx = _make_session_ctx(db_session)
    with (
        patch("dashboard.app.init_db"),
        patch("dashboard.app.get_session", session_ctx),
        patch("dashboard.app.fetch_prices", return_value=_normal_prices()),
        patch("dashboard.app.fetch_fear_greed", return_value=_normal_fg()),
        patch("dashboard.app.fetch_mvrv", return_value=1.5),
        patch("dashboard.app.fetch_funding_rate", return_value=0.0001),
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_with_session():
    """Yield (TestClient, session) sharing the same in-memory DB.

    Use this when tests need to insert data AND query it via the API.
    """
    from dashboard.app import app

    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session_ctx = _make_session_ctx(session)
    with (
        patch("dashboard.app.init_db"),
        patch("dashboard.app.get_session", session_ctx),
        patch("dashboard.app.fetch_prices", return_value=_normal_prices()),
        patch("dashboard.app.fetch_fear_greed", return_value=_normal_fg()),
        patch("dashboard.app.fetch_mvrv", return_value=1.5),
        patch("dashboard.app.fetch_funding_rate", return_value=0.0001),
    ):
        with TestClient(app) as c:
            yield c, session

    session.close()


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------

def test_api_status_returns_200(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_api_status_has_expected_keys(client):
    data = client.get("/api/status").json()
    for key in ("prices", "fear_greed", "eth_mvrv", "btc_mvrv", "funding_rate", "halving", "alerts"):
        assert key in data, "Missing key: {}".format(key)


def test_api_status_prices_populated(client):
    data = client.get("/api/status").json()
    assert data["prices"]["btc_price"] == 85_000.0
    assert data["prices"]["eth_price"] == 3_200.0


def test_api_status_halving_has_months(client):
    data = client.get("/api/status").json()
    assert "months_elapsed" in data["halving"]
    assert isinstance(data["halving"]["months_elapsed"], (int, float))


def test_api_status_no_alerts_in_normal_market(client):
    """Normal prices should not trigger any active alerts."""
    data = client.get("/api/status").json()
    assert data["alerts"] == []


def test_api_status_btc_crash_triggers_alert(db_session):
    """BTC drop > 15% in 24h should appear in active alerts."""
    from dashboard.app import app

    crash_prices = {**_normal_prices(), "btc_change_24h": -17.0}
    session_ctx = _make_session_ctx(db_session)
    with (
        patch("dashboard.app.init_db"),
        patch("dashboard.app.get_session", session_ctx),
        patch("dashboard.app.fetch_prices", return_value=crash_prices),
        patch("dashboard.app.fetch_fear_greed", return_value=_normal_fg()),
        patch("dashboard.app.fetch_mvrv", return_value=1.5),
        patch("dashboard.app.fetch_funding_rate", return_value=0.0001),
    ):
        with TestClient(app) as c:
            data = c.get("/api/status").json()
    alert_types = [a["type"] for a in data["alerts"]]
    assert "BTC Crash" in alert_types


# ---------------------------------------------------------------------------
# /api/alerts
# ---------------------------------------------------------------------------

def _insert_alert(session, alert_type, severity="orange"):
    a = AlertLog(
        alert_type=alert_type,
        severity=severity,
        message="",
        btc_price=85_000.0,
        eth_price=3_200.0,
        metric_value=0.0,
        notified=True,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(a)
    session.commit()


def test_api_alerts_empty_by_default(client):
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_alerts_excludes_heartbeats_by_default(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "heartbeat", "green")
    _insert_alert(session, "btc_crash", "red")

    data = c.get("/api/alerts").json()
    assert len(data) == 1
    assert data[0]["alert_type"] == "btc_crash"


def test_api_alerts_includes_heartbeats_when_requested(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "heartbeat", "green")
    _insert_alert(session, "btc_crash", "red")

    data = c.get("/api/alerts?include_heartbeats=1").json()
    assert len(data) == 2


def test_api_alerts_response_shape(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "sp500_crash", "orange")

    data = c.get("/api/alerts").json()
    assert len(data) == 1
    row = data[0]
    for field in ("timestamp", "alert_type", "severity", "notified"):
        assert field in row


# ---------------------------------------------------------------------------
# /api/snapshots
# ---------------------------------------------------------------------------

def test_api_snapshots_empty(client):
    resp = client.get("/api/snapshots")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_snapshots_returns_data(client_with_session):
    c, session = client_with_session
    snap = UserPortfolioSnapshot(
        snapshot_date="2026-W14",
        data_json=json.dumps({"btc_value": 5000.0, "total": 8000.0}),
    )
    session.add(snap)
    session.commit()

    data = c.get("/api/snapshots").json()
    assert len(data) == 1
    assert data[0]["date"] == "2026-W14"
    assert data[0]["btc_value"] == 5000.0


def test_api_snapshots_sorted_by_date(client_with_session):
    c, session = client_with_session
    for week in ("2026-W12", "2026-W14", "2026-W13"):
        snap = UserPortfolioSnapshot(
            snapshot_date=week,
            data_json=json.dumps({"total": 1000.0}),
        )
        session.add(snap)
    session.commit()

    data = c.get("/api/snapshots").json()
    dates = [d["date"] for d in data]
    assert dates == sorted(dates)
