"""Tests for portfolio summary in weekly digest (alerts/digest.py)."""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from data.models import UserTrade


def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


def _normal_prices():
    return {
        "btc_price": 80_000.0,
        "btc_price_eur": 72_000.0,
        "btc_change_24h": 1.0,
        "eth_price": 2_000.0,
        "eth_price_eur": 1_800.0,
        "eth_change_24h": 0.5,
    }


def _add_buy(session, asset, units, price_eur, asset_class="crypto"):
    session.add(UserTrade(
        date=datetime(2024, 1, 1), asset=asset, asset_class=asset_class,
        side="buy", units=units, price_eur=price_eur, fee_eur=0.0, source="sparplan",
    ))
    session.commit()


def _run_digest(db_session, etf_prices=None):
    """Run send_weekly_digest with standard mocks and return (result, captured_payload)."""
    captured = {}

    def _capture_send(payload):
        captured["payload"] = payload
        return True

    etf_ret = etf_prices  # None means don't patch, {} means raise ImportError

    patches = [
        patch("alerts.digest.fetch_prices", return_value=_normal_prices()),
        patch("alerts.digest.fetch_mvrv", return_value=1.5),
        patch("alerts.digest.fetch_funding_rate", return_value=0.0001),
        patch("alerts.digest.fetch_sp500_change", return_value=1.0),
        patch("alerts.digest.send_discord_message", side_effect=_capture_send),
        patch("alerts.digest.init_db"),
        patch("alerts.digest.get_session", _make_session_ctx(db_session)),
        # _get_portfolio_summary also calls get_session and fetch_all_etf_prices_eur lazily
        patch("data.database.get_session", _make_session_ctx(db_session)),
    ]

    if etf_ret is not None:
        patches.append(patch("data.etf_prices.fetch_all_etf_prices_eur", return_value=etf_ret))

    with __import__("contextlib").ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        from alerts.digest import send_weekly_digest
        result = send_weekly_digest()

    return result, captured.get("payload")


def _get_portfolio_field(payload):
    """Extract the Portfolio actual embed field value, or None."""
    if payload is None:
        return None
    fields = payload.get("embeds", [{}])[0].get("fields", [])
    for f in fields:
        if f.get("name") == "Portfolio actual":
            return f["value"]
    return None


def test_digest_no_portfolio_block_when_empty(db_session):
    """Digest has no Portfolio block when user_trade is empty."""
    result, payload = _run_digest(db_session)
    assert result is True
    assert _get_portfolio_field(payload) is None


def test_digest_shows_crypto_portfolio(db_session):
    """Digest shows BTC and ETH values when trades exist."""
    _add_buy(db_session, "BTC", 0.5, 60_000.0)
    _add_buy(db_session, "ETH", 2.0, 1_500.0)

    result, payload = _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    assert result is True
    field = _get_portfolio_field(payload)
    assert field is not None
    assert "BTC" in field
    assert "ETH" in field


def test_digest_shows_etf_values_when_available(db_session):
    """Digest shows ETF values and TOTAL when yfinance prices are available."""
    _add_buy(db_session, "BTC", 0.5, 60_000.0)
    _add_buy(db_session, "SP500", 10.0, 480.0, asset_class="etf")

    result, payload = _run_digest(db_session, etf_prices={
        "SP500": 520.0, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    assert result is True
    field = _get_portfolio_field(payload)
    assert field is not None
    assert "ETFs" in field
    assert "TOTAL" in field


def test_digest_portfolio_crypto_only_when_yfinance_fails(db_session):
    """Digest shows crypto-only note when yfinance import fails."""
    _add_buy(db_session, "BTC", 0.5, 60_000.0)

    with (
        patch("alerts.digest.fetch_prices", return_value=_normal_prices()),
        patch("alerts.digest.fetch_mvrv", return_value=1.5),
        patch("alerts.digest.fetch_funding_rate", return_value=0.0001),
        patch("alerts.digest.fetch_sp500_change", return_value=1.0),
        patch("alerts.digest.send_discord_message", return_value=True),
        patch("alerts.digest.init_db"),
        patch("alerts.digest.get_session", _make_session_ctx(db_session)),
        patch("data.database.get_session", _make_session_ctx(db_session)),
        # Simulate yfinance not available
        patch("data.etf_prices.fetch_all_etf_prices_eur", side_effect=ImportError("no yfinance")),
    ):
        from alerts.digest import send_weekly_digest
        result = send_weekly_digest()

    assert result is True


def test_digest_shows_irpf_when_gains(db_session):
    """Digest shows IRPF estimate when crypto portfolio has unrealized gains."""
    # BTC bought at 60,000 EUR; current price 72,000 EUR -> unrealized gain -> IRPF > 0
    _add_buy(db_session, "BTC", 0.5, 60_000.0)

    result, payload = _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    assert result is True
    field = _get_portfolio_field(payload)
    assert field is not None
    assert "IRPF est." in field


def test_digest_no_irpf_when_no_gains(db_session):
    """Digest omits IRPF line when there are no unrealized gains."""
    # BTC bought at current price -> zero gain -> no IRPF line
    _add_buy(db_session, "BTC", 0.5, 72_000.0)

    result, payload = _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    assert result is True
    field = _get_portfolio_field(payload)
    assert field is not None
    assert "IRPF est." not in field


def test_digest_saves_portfolio_snapshot(db_session):
    """Digest saves a UserPortfolioSnapshot after sending."""
    from data.models import UserPortfolioSnapshot
    _add_buy(db_session, "BTC", 0.5, 60_000.0)

    _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })

    snaps = db_session.query(UserPortfolioSnapshot).all()
    assert len(snaps) == 1
    import json
    data = json.loads(snaps[0].data_json)
    assert data["btc_value"] > 0
    assert "total" in data


def test_digest_snapshot_idempotent(db_session):
    """Second digest call in same ISO week does not duplicate snapshot."""
    from data.models import UserPortfolioSnapshot
    _add_buy(db_session, "BTC", 0.5, 60_000.0)

    _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    # Manually reset the weekly_digest cooldown so digest can run again
    from data.models import AlertLog
    db_session.query(AlertLog).filter_by(alert_type="weekly_digest").delete()
    db_session.commit()

    _run_digest(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })

    snaps = db_session.query(UserPortfolioSnapshot).all()
    assert len(snaps) == 1  # idempotent: still only one snapshot for this ISO week
