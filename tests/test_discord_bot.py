"""Tests for alerts/discord_bot.py signal logic.

Mocking strategy:
- External API calls (fetch_prices, fetch_mvrv, fetch_funding_rate) are patched
  at the discord_bot module level where they are imported.
- send_discord_message is patched to avoid real HTTP calls.
- get_session is patched to use the in-memory db_session fixture.
- init_db is patched to a no-op (DB already initialised by fixture).

Pattern: patch as close to usage as possible, i.e. "alerts.discord_bot.X".
"""

from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest

from data.models import AlertLog


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normal_prices():
    return {
        "btc_price": 50_000.0,
        "btc_price_eur": 45_000.0,
        "btc_change_24h": 2.5,
        "eth_price": 2_500.0,
        "eth_price_eur": 2_250.0,
        "eth_change_24h": 1.2,
    }


def _make_session_ctx(session):
    """Return a context-manager mock that yields the given session."""
    @contextmanager
    def _ctx():
        yield session
    return _ctx


# ---------------------------------------------------------------------------
# _already_alerted
# ---------------------------------------------------------------------------

def test_already_alerted_no_prior(db_session):
    """No prior alerts -> _already_alerted returns False."""
    from alerts.discord_bot import _already_alerted

    result = _already_alerted(db_session, "btc_crash", hours=6)
    assert result is False


def test_already_alerted_after_logging(db_session):
    """After logging an alert, _already_alerted returns True within cooldown."""
    from datetime import datetime, timezone
    from alerts.discord_bot import _already_alerted, _log_alert

    _log_alert(db_session, "btc_crash", "red", 50000.0, 2500.0, -16.0, notified=True)
    db_session.commit()

    result = _already_alerted(db_session, "btc_crash", hours=6)
    assert result is True


# ---------------------------------------------------------------------------
# check_and_alert -- no signal
# ---------------------------------------------------------------------------

def test_no_alerts_when_normal(db_session):
    """All metrics in normal range -> empty list returned."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0001),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert result == []


# ---------------------------------------------------------------------------
# check_and_alert -- BTC crash
# ---------------------------------------------------------------------------

def test_btc_crash_triggered(db_session):
    """BTC drop of -16% triggers btc_crash alert."""
    prices = {**_normal_prices(), "btc_change_24h": -16.0}

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert len(result) == 1
    assert result[0]["type"] == "btc_crash"
    assert result[0]["severity"] == "red"

    row = db_session.query(AlertLog).filter_by(alert_type="btc_crash").first()
    assert row is not None
    assert row.notified == 1


def test_btc_crash_not_triggered_small_drop(db_session):
    """BTC drop of -5% does NOT trigger crash alert."""
    prices = {**_normal_prices(), "btc_change_24h": -5.0}

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert not any(a["type"] == "btc_crash" for a in result)


# ---------------------------------------------------------------------------
# check_and_alert -- funding rate
# ---------------------------------------------------------------------------

def test_funding_negative_triggered(db_session):
    """Negative funding rate triggers funding_negative alert."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=-0.0002),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "funding_negative" in types


# ---------------------------------------------------------------------------
# check_and_alert -- ETH MVRV
# ---------------------------------------------------------------------------

def test_eth_mvrv_critical(db_session):
    """ETH MVRV < 0.8 triggers mvrv_critical (red)."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_mvrv", return_value=0.6),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert any(a["type"] == "mvrv_critical" and a["severity"] == "red" for a in result)
    assert not any(a["type"] == "mvrv_low" for a in result)


def test_eth_mvrv_low(db_session):
    """ETH MVRV between 0.8 and 1.0 triggers mvrv_low (yellow), not critical."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_mvrv", return_value=0.9),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert any(a["type"] == "mvrv_low" and a["severity"] == "yellow" for a in result)
    assert not any(a["type"] == "mvrv_critical" for a in result)


# ---------------------------------------------------------------------------
# check_and_alert -- BTC DCA-out
# ---------------------------------------------------------------------------

def test_btc_dca_out_level_triggered(db_session):
    """BTC at $90k triggers the $80k DCA-out level."""
    prices = {**_normal_prices(), "btc_price": 90_000.0, "btc_price_eur": 81_000.0}

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "btc_dca_out_80k" in types
    assert "btc_dca_out_100k" not in types  # $90k does not reach $100k level


# ---------------------------------------------------------------------------
# check_and_alert -- deduplication
# ---------------------------------------------------------------------------

def test_deduplication_prevents_double_alert(db_session):
    """Same alert within cooldown window is not sent twice."""
    prices = {**_normal_prices(), "btc_change_24h": -16.0}
    kwargs = dict(
        fetch_prices=patch("alerts.discord_bot.fetch_prices", return_value=prices),
        fetch_mvrv=patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        fetch_funding_rate=patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        send_discord=patch("alerts.discord_bot.send_discord_message", return_value=True),
        init_db=patch("alerts.discord_bot.init_db"),
        get_session=patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    )

    from alerts.discord_bot import check_and_alert

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        first = check_and_alert()

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_mvrv", return_value=1.5),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        second = check_and_alert()

    # First run triggers the alert
    assert any(a["type"] == "btc_crash" for a in first)
    # Second run within cooldown: no new alert
    assert not any(a["type"] == "btc_crash" for a in second)

    # Only one row in DB
    rows = db_session.query(AlertLog).filter_by(alert_type="btc_crash").all()
    assert len(rows) == 1
