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


# ---------------------------------------------------------------------------
# /api/alerts filters
# ---------------------------------------------------------------------------

def test_api_alerts_filter_by_type(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "btc_crash", "red")
    _insert_alert(session, "mvrv_critical", "red")

    data = c.get("/api/alerts?alert_type=btc_crash").json()
    assert len(data) == 1
    assert data[0]["alert_type"] == "btc_crash"


def test_api_alerts_filter_by_severity(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "btc_crash", "red")
    _insert_alert(session, "funding_negative", "orange")

    data = c.get("/api/alerts?severity=red").json()
    assert all(r["severity"] == "red" for r in data)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# /api/drift
# ---------------------------------------------------------------------------

def _insert_trade(session, asset, units, price_eur, side="buy", asset_class="crypto"):
    from data.models import UserTrade
    session.add(UserTrade(
        date=datetime(2024, 1, 1),
        asset=asset, asset_class=asset_class, side=side,
        units=units, price_eur=price_eur, fee_eur=0.0, source="sparplan",
    ))
    session.commit()


def _fake_portfolio_prices(btc_eur=60_000.0, eth_eur=2_500.0, etf_prices=None):
    return {
        "btc_eur": btc_eur,
        "eth_eur": eth_eur,
        "etf_prices": etf_prices or {
            "SP500": 500.0,
            "SEMICONDUCTORS": 200.0,
            "REALTY_INCOME": 50.0,
            "URANIUM": 30.0,
        },
    }


def test_api_drift_empty_without_trades(client_with_session):
    c, _session = client_with_session
    with patch("data.market_data.fetch_portfolio_prices_eur", return_value=_fake_portfolio_prices()):
        data = c.get("/api/drift").json()
    assert data == []


def test_api_drift_returns_all_targets(client_with_session):
    c, session = client_with_session
    _insert_trade(session, "BTC", 0.01, 50_000.0, asset_class="crypto")
    _insert_trade(session, "SP500", 2.0, 450.0, asset_class="etf")

    with patch("data.market_data.fetch_portfolio_prices_eur", return_value=_fake_portfolio_prices()):
        data = c.get("/api/drift").json()

    assert len(data) == 6  # 6 Sparplan assets
    assets = {d["asset"] for d in data}
    assert assets == {"BTC", "ETH", "SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM"}
    for row in data:
        assert "target_pct" in row
        assert "actual_pct" in row
        assert "drift_pp" in row
        assert "status" in row
        assert row["status"] in ("ok", "watch", "rebalance")


# ---------------------------------------------------------------------------
# /api/portfolio_pnl
# ---------------------------------------------------------------------------

def test_api_portfolio_pnl_empty(client_with_session):
    c, _session = client_with_session
    with patch("data.market_data.fetch_portfolio_prices_eur", return_value=_fake_portfolio_prices()):
        data = c.get("/api/portfolio_pnl").json()
    assert data == {"assets": [], "totals": {"invested": 0, "value": 0, "pnl": 0}}


def test_api_portfolio_pnl_crypto_and_etf(client_with_session):
    c, session = client_with_session
    _insert_trade(session, "BTC", 0.1, 30_000.0, asset_class="crypto")
    _insert_trade(session, "SP500", 2.0, 450.0, asset_class="etf")

    with patch("data.market_data.fetch_portfolio_prices_eur", return_value=_fake_portfolio_prices()):
        data = c.get("/api/portfolio_pnl").json()

    assets = {a["asset"]: a for a in data["assets"]}
    assert "BTC" in assets
    assert "SP500" in assets
    assert data["totals"]["invested"] > 0
    assert data["totals"]["value"] > 0


# ---------------------------------------------------------------------------
# D6: /api/alerts_heatmap
# ---------------------------------------------------------------------------

def test_api_alerts_heatmap_empty(client):
    resp = client.get("/api/alerts_heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data and "types" in data and "cells" in data
    assert data["cells"] == []


def test_api_alerts_heatmap_groups_by_day_and_type(client_with_session):
    c, session = client_with_session
    # Two alerts of the same type on the same day
    _insert_alert(session, "btc_crash", "red")
    _insert_alert(session, "btc_crash", "red")
    _insert_alert(session, "mvrv_critical", "red")

    data = c.get("/api/alerts_heatmap").json()
    cells_by_type = {cell["type"]: cell for cell in data["cells"]}
    assert "btc_crash" in cells_by_type
    assert cells_by_type["btc_crash"]["count"] == 2
    assert "mvrv_critical" in cells_by_type
    assert cells_by_type["mvrv_critical"]["count"] == 1


def test_api_alerts_heatmap_excludes_heartbeats(client_with_session):
    c, session = client_with_session
    _insert_alert(session, "heartbeat", "green")
    _insert_alert(session, "btc_crash", "red")

    data = c.get("/api/alerts_heatmap").json()
    types = {cell["type"] for cell in data["cells"]}
    assert "heartbeat" not in types
    assert "btc_crash" in types


# ---------------------------------------------------------------------------
# D7: POST /api/tax_simulate
# ---------------------------------------------------------------------------

def test_api_tax_simulate_no_trades(client):
    resp = client.post("/api/tax_simulate", json={
        "asset": "BTC", "units": 0.1, "price_eur": 80000.0
    })
    assert resp.status_code == 200
    data = resp.json()
    # With no real trades, baseline gain is 0 and sim gain equals the simulated sale
    assert "delta_irpf_eur" in data
    assert "proceeds_eur" in data
    assert data["proceeds_eur"] == pytest.approx(8000.0)


def test_api_tax_simulate_invalid_units(client):
    resp = client.post("/api/tax_simulate", json={
        "asset": "BTC", "units": -1.0, "price_eur": 80000.0
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_api_tax_simulate_response_shape(client):
    resp = client.post("/api/tax_simulate", json={
        "asset": "ETH", "units": 0.5, "price_eur": 2000.0
    })
    assert resp.status_code == 200
    data = resp.json()
    for field in ("asset", "units", "price_eur", "proceeds_eur",
                  "delta_irpf_eur", "net_cash_eur", "bracket_before", "bracket_after"):
        assert field in data, f"Missing field: {field}"
    assert data["asset"] == "ETH"


# ---------------------------------------------------------------------------
# D8: GET /api/retirement_mc
# ---------------------------------------------------------------------------

def _make_mock_mc_result():
    """Build a minimal MonteCarloResult-like object for mocking."""
    from unittest.mock import MagicMock
    r = MagicMock()
    r.n_years = 35
    r.n_simulations = 500
    r.data_start_year = 2017
    r.data_end_year = 2025
    r.data_months = 96
    r.years = list(range(1, 36))
    r.p10 = [i * 1000.0 for i in range(1, 36)]
    r.p25 = [i * 2000.0 for i in range(1, 36)]
    r.p50 = [i * 3000.0 for i in range(1, 36)]
    r.p75 = [i * 4000.0 for i in range(1, 36)]
    r.p90 = [i * 5000.0 for i in range(1, 36)]
    r.prob_reach_target = 0.72
    r.median_at_retirement = 350_000.0
    r.safe_withdrawal_rate_4pct = 1166.67
    return r


def test_api_retirement_mc_returns_200(client):
    with patch("analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()):
        resp = client.get("/api/retirement_mc?age=30&retire_age=65&monthly=140")
    assert resp.status_code == 200


def test_api_retirement_mc_response_shape(client):
    with patch("analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()):
        data = client.get("/api/retirement_mc?age=30&retire_age=65&monthly=140").json()
    for key in ("n_years", "years", "p10", "p25", "p50", "p75", "p90",
                "prob_reach_1M", "median_at_retirement", "safe_withdrawal_monthly_eur"):
        assert key in data, f"Missing key: {key}"


def test_api_retirement_mc_n_years_matches_params(client):
    with patch("analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()):
        data = client.get("/api/retirement_mc?age=40&retire_age=65&monthly=200").json()
    assert data["n_years"] == 35  # from mock result
    assert data["age"] == 40
    assert data["retire_age"] == 65


def test_api_retirement_mc_handles_mc_error(client):
    with patch("analysis.monte_carlo.run_monte_carlo", side_effect=RuntimeError("no data")):
        resp = client.get("/api/retirement_mc")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
