"""Tests for dashboard/app.py FastAPI endpoints.

Mocking strategy:
- External API calls (fetch_prices, fetch_mvrv, etc.) patched at dashboard.app module level.
- get_session patched to use the in-memory db_session fixture.
- init_db patched to no-op.

Pattern mirrors test_discord_bot.py: patch as close to usage as possible.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

def _insert_alert(session, alert_type, severity="orange", timestamp=None):
    a = AlertLog(
        alert_type=alert_type,
        severity=severity,
        message="",
        btc_price=85_000.0,
        eth_price=3_200.0,
        metric_value=0.0,
        notified=True,
        timestamp=timestamp or datetime.now(timezone.utc).replace(tzinfo=None),
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


# ---------------------------------------------------------------------------
# D6 heatmap: gap-coverage tests (severity aggregation, days filter, multi-day)
# ---------------------------------------------------------------------------

def test_api_alerts_heatmap_severity_aggregation_keeps_highest(client_with_session):
    """When multiple alerts of the same (date, type) coexist, the cell should
    surface the highest severity (red > orange > yellow > green)."""
    c, session = client_with_session
    _insert_alert(session, "btc_crash", "yellow")
    _insert_alert(session, "btc_crash", "orange")
    _insert_alert(session, "btc_crash", "red")

    data = c.get("/api/alerts_heatmap").json()
    cells = [cell for cell in data["cells"] if cell["type"] == "btc_crash"]
    assert len(cells) == 1
    assert cells[0]["count"] == 3
    assert cells[0]["severity"] == "red"


def test_api_alerts_heatmap_days_param_excludes_old_alerts(client_with_session):
    """Alerts older than `days` should be filtered out by the cutoff."""
    c, session = client_with_session
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _insert_alert(session, "btc_crash", "red", timestamp=now)
    _insert_alert(session, "mvrv_critical", "red", timestamp=now - timedelta(days=60))

    # Default days=30 -> only recent alert
    data_30 = c.get("/api/alerts_heatmap?days=30").json()
    types_30 = {cell["type"] for cell in data_30["cells"]}
    assert "btc_crash" in types_30
    assert "mvrv_critical" not in types_30

    # days=90 -> both alerts
    data_90 = c.get("/api/alerts_heatmap?days=90").json()
    types_90 = {cell["type"] for cell in data_90["cells"]}
    assert "btc_crash" in types_90
    assert "mvrv_critical" in types_90


def test_api_alerts_heatmap_multi_day_distinct_cells(client_with_session):
    """Same alert type on different days should produce distinct cells."""
    c, session = client_with_session
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _insert_alert(session, "btc_crash", "red", timestamp=now)
    _insert_alert(session, "btc_crash", "red", timestamp=now - timedelta(days=3))

    data = c.get("/api/alerts_heatmap").json()
    btc_cells = [c for c in data["cells"] if c["type"] == "btc_crash"]
    assert len(btc_cells) == 2
    distinct_dates = {c["date"] for c in btc_cells}
    assert len(distinct_dates) == 2
    assert len(data["days"]) == 2


# ---------------------------------------------------------------------------
# D7 tax_simulate: gap-coverage tests (real preexisting trades affect baseline)
# ---------------------------------------------------------------------------

def _insert_dated_trade(session, asset, units, price_eur, side, trade_date,
                       asset_class="crypto"):
    from data.models import UserTrade
    session.add(UserTrade(
        date=trade_date,
        asset=asset, asset_class=asset_class, side=side,
        units=units, price_eur=price_eur, fee_eur=0.0, source="sparplan",
    ))
    session.commit()


def test_api_tax_simulate_with_existing_buy_produces_gain(client_with_session):
    """A simulated sell against a preexisting buy at a lower cost basis
    should produce delta_gain > 0 and delta_irpf > 0."""
    c, session = client_with_session
    now = datetime.now()
    _insert_dated_trade(
        session, "BTC", units=0.1, price_eur=30_000.0,
        side="buy", trade_date=now - timedelta(days=180),
    )

    resp = c.post("/api/tax_simulate", json={
        "asset": "BTC", "units": 0.05, "price_eur": 80_000.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "error" not in data
    assert data["proceeds_eur"] == pytest.approx(0.05 * 80_000.0)
    assert data["gain_before_eur"] == pytest.approx(0.0)
    # 0.05 BTC * (80000 - 30000) = 2500 EUR gain
    assert data["gain_after_eur"] == pytest.approx(2500.0, rel=0.01)
    assert data["delta_gain_eur"] == pytest.approx(2500.0, rel=0.01)
    assert data["delta_irpf_eur"] > 0
    # Net cash should be proceeds minus tax
    assert 0 < data["net_cash_eur"] < data["proceeds_eur"]
    assert data["effective_tax_rate_pct"] > 0


def test_api_tax_simulate_baseline_with_realized_gain(client_with_session):
    """If the user already has a realized sell this year, the baseline gain
    must be > 0 and delta_irpf must reflect only the marginal impact."""
    c, session = client_with_session
    now = datetime.now()
    _insert_dated_trade(
        session, "BTC", units=0.2, price_eur=20_000.0,
        side="buy", trade_date=now - timedelta(days=400),
    )
    _insert_dated_trade(
        session, "BTC", units=0.05, price_eur=70_000.0,
        side="sell", trade_date=now - timedelta(days=30),
    )

    resp = c.post("/api/tax_simulate", json={
        "asset": "BTC", "units": 0.05, "price_eur": 90_000.0,
    })
    data = resp.json()
    assert "error" not in data
    # Already realized: 0.05 * (70000 - 20000) = 2500 EUR
    assert data["gain_before_eur"] == pytest.approx(2500.0, rel=0.01)
    # After sim: + 0.05 * (90000 - 20000) = +3500 EUR -> 6000 total
    assert data["gain_after_eur"] == pytest.approx(6000.0, rel=0.01)
    assert data["delta_gain_eur"] == pytest.approx(3500.0, rel=0.01)
    assert data["delta_irpf_eur"] > 0


def test_api_tax_simulate_zero_price_rejected(client):
    resp = client.post("/api/tax_simulate", json={
        "asset": "BTC", "units": 0.1, "price_eur": 0.0,
    })
    data = resp.json()
    assert "error" in data


# ---------------------------------------------------------------------------
# D8 retirement_mc: gap-coverage (inflation deflate, n_simulations clamp)
# ---------------------------------------------------------------------------

def test_api_retirement_mc_inflation_deflates_values(client):
    """With inflation > 0, returned percentile values must be strictly less
    than the raw simulation output (real EUR < nominal EUR)."""
    raw = _make_mock_mc_result()
    raw_p50 = list(raw.p50)  # snapshot before patching consumes it

    with patch("analysis.monte_carlo.run_monte_carlo", return_value=raw):
        data = client.get(
            "/api/retirement_mc?age=30&retire_age=65&monthly=140&inflation=0.05"
        ).json()

    assert data["inflation"] == 0.05
    assert len(data["p50"]) == len(raw_p50)
    # Every deflated value must be smaller than the nominal one
    for nominal, deflated in zip(raw_p50, data["p50"]):
        assert deflated < nominal


def test_api_retirement_mc_no_inflation_passes_through(client):
    """Without inflation the values must equal the raw simulation output."""
    raw = _make_mock_mc_result()
    raw_p50 = list(raw.p50)

    with patch("analysis.monte_carlo.run_monte_carlo", return_value=raw):
        data = client.get(
            "/api/retirement_mc?age=30&retire_age=65&monthly=140"
        ).json()

    assert data["inflation"] == 0.0
    assert data["p50"] == raw_p50


def test_api_retirement_mc_clamps_n_simulations_low(client):
    """n_simulations below 50 must be clamped to 50."""
    with patch(
        "analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()
    ) as mock_mc:
        client.get("/api/retirement_mc?n_simulations=10")
    _, kwargs = mock_mc.call_args
    assert kwargs["n_simulations"] == 50


def test_api_retirement_mc_clamps_n_simulations_high(client):
    """n_simulations above 2000 must be clamped to 2000."""
    with patch(
        "analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()
    ) as mock_mc:
        client.get("/api/retirement_mc?n_simulations=99999")
    _, kwargs = mock_mc.call_args
    assert kwargs["n_simulations"] == 2000


def test_api_retirement_mc_n_years_floor(client):
    """When age >= retire_age, n_years must be floored to 1 (not 0/negative)."""
    with patch(
        "analysis.monte_carlo.run_monte_carlo", return_value=_make_mock_mc_result()
    ) as mock_mc:
        client.get("/api/retirement_mc?age=70&retire_age=65")
    _, kwargs = mock_mc.call_args
    assert kwargs["n_years"] == 1
