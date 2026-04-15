"""Tests for alerts/discord_bot.py signal logic.

Mocking strategy:
- External API calls (fetch_prices, fetch_funding_rate, fetch_sp500_change) are patched
  at the discord_bot module level where they are imported.
- send_discord_message is patched to avoid real HTTP calls.
- get_session is patched to use the in-memory db_session fixture.
- init_db is patched to a no-op (DB already initialised by fixture).

Pattern: patch as close to usage as possible, i.e. "alerts.discord_bot.X".
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0001),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.5),
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
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
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
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
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
        patch("alerts.discord_bot.fetch_funding_rate", return_value=-0.0002),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "funding_negative" in types


# ETH MVRV tests removed 2026-04: signal discarded in research13 (does not
# beat baseline under IS/OOS methodology). See RESEARCH_ARCHIVE.md.


# ---------------------------------------------------------------------------
# check_and_alert -- BTC DCA-out
# ---------------------------------------------------------------------------

def test_btc_dca_out_level_triggered(db_session):
    """BTC at $90k triggers the $80k DCA-out level."""
    prices = {**_normal_prices(), "btc_price": 90_000.0, "btc_price_eur": 81_000.0}

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "btc_dca_out_80k" in types
    assert "btc_dca_out_100k" not in types  # $90k does not reach $100k level


def test_eth_dca_out_level_triggered(db_session):
    """ETH at $3500 triggers the $3k DCA-out level but not $4k."""
    prices = {**_normal_prices(), "eth_price": 3_500.0, "eth_price_eur": 3_150.0}

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "eth_dca_out_3k" in types
    assert "eth_dca_out_4k" not in types  # $3500 does not reach $4k level


# ---------------------------------------------------------------------------
# check_and_alert -- deduplication
# ---------------------------------------------------------------------------

def test_deduplication_prevents_double_alert(db_session):
    """Same alert within cooldown window is not sent twice."""
    prices = {**_normal_prices(), "btc_change_24h": -16.0}

    from alerts.discord_bot import check_and_alert

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        first = check_and_alert()

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
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


# ---------------------------------------------------------------------------
# check_and_alert -- S&P500 crash
# ---------------------------------------------------------------------------

def test_sp500_crash_triggered(db_session):
    """S&P500 drop of -8% over 5d triggers sp500_crash (orange)."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=-8.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    types = [a["type"] for a in result]
    assert "sp500_crash" in types
    assert next(a for a in result if a["type"] == "sp500_crash")["severity"] == "orange"

    row = db_session.query(AlertLog).filter_by(alert_type="sp500_crash").first()
    assert row is not None


def test_sp500_no_alert_when_normal(db_session):
    """S&P500 change of -2% does NOT trigger sp500_crash."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=-2.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert not any(a["type"] == "sp500_crash" for a in result)


def test_sp500_none_does_not_crash(db_session):
    """fetch_sp500_change returning None (Stooq unavailable) does not trigger any alert."""
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=None),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        result = check_and_alert()

    assert not any(a["type"] == "sp500_crash" for a in result)


# ---------------------------------------------------------------------------
# send_weekly_digest (alerts/digest.py)
# ---------------------------------------------------------------------------

def test_weekly_digest_sends_when_no_prior(db_session):
    """send_weekly_digest sends message when no prior digest in last 6 days."""
    with (
        patch("alerts.digest.fetch_prices", return_value=_normal_prices()),
        patch("alerts.digest.fetch_mvrv", return_value=1.5),
        patch("alerts.digest.fetch_funding_rate", return_value=0.0001),
        patch("alerts.digest.fetch_sp500_change", return_value=1.0),
        patch("alerts.digest.send_discord_message", return_value=True),
        patch("alerts.digest.init_db"),
        patch("alerts.digest.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.digest import send_weekly_digest
        result = send_weekly_digest()

    assert result is True


def test_weekly_digest_skipped_when_recent(db_session):
    """send_weekly_digest skips if digest was already sent within 6 days."""
    from alerts.discord_bot import _log_alert
    _log_alert(db_session, "weekly_digest", "blue", 50000.0, 2500.0, 1.5, notified=True)
    db_session.commit()

    with (
        patch("alerts.digest.fetch_prices", return_value=_normal_prices()),
        patch("alerts.digest.fetch_mvrv", return_value=1.5),
        patch("alerts.digest.fetch_funding_rate", return_value=0.0001),
        patch("alerts.digest.fetch_sp500_change", return_value=1.0),
        patch("alerts.digest.send_discord_message", return_value=True),
        patch("alerts.digest.init_db"),
        patch("alerts.digest.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.digest import send_weekly_digest
        result = send_weekly_digest()

    assert result is False


def test_weekly_digest_handles_none_prices(db_session):
    """send_weekly_digest does not crash when all prices/indicators are None."""
    none_prices = {
        "btc_price": None, "btc_price_eur": None, "btc_change_24h": None,
        "eth_price": None, "eth_price_eur": None, "eth_change_24h": None,
    }
    with (
        patch("alerts.digest.fetch_prices", return_value=none_prices),
        patch("alerts.digest.fetch_mvrv", return_value=None),
        patch("alerts.digest.fetch_funding_rate", return_value=None),
        patch("alerts.digest.fetch_sp500_change", return_value=None),
        patch("alerts.digest.send_discord_message", return_value=True),
        patch("alerts.digest.init_db"),
        patch("alerts.digest.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.digest import send_weekly_digest
        result = send_weekly_digest()

    assert result is True


# ---------------------------------------------------------------------------
# check_and_alert -- heartbeat and dead canary
# ---------------------------------------------------------------------------

def _add_heartbeat(db_session, hours_ago: float):
    """Helper: insert a heartbeat entry with the given age."""
    ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago)
    entry = AlertLog(
        timestamp=ts, alert_type="heartbeat", severity="green",
        message="heartbeat", btc_price=50000.0, eth_price=2500.0,
        metric_value=0.0, notified=1,
    )
    db_session.add(entry)
    db_session.commit()


def _run_normal_check(db_session):
    with (
        patch("alerts.discord_bot.fetch_prices", return_value=_normal_prices()),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=0.0),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=0.0),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        return check_and_alert()


def test_heartbeat_logged_after_check(db_session):
    """check_and_alert() logs a heartbeat entry after each successful run."""
    _run_normal_check(db_session)

    row = db_session.query(AlertLog).filter_by(alert_type="heartbeat").first()
    assert row is not None
    assert row.severity == "green"


def test_dead_canary_triggers_when_gap_large(db_session):
    """Dead canary alert fires when last heartbeat is > 10h ago."""
    _add_heartbeat(db_session, hours_ago=12)

    result = _run_normal_check(db_session)

    assert any(a["type"] == "dead_canary" and a["severity"] == "red" for a in result)
    row = db_session.query(AlertLog).filter_by(alert_type="dead_canary").first()
    assert row is not None


def test_dead_canary_no_trigger_recent_heartbeat(db_session):
    """Dead canary does not fire when last heartbeat is < 10h ago."""
    _add_heartbeat(db_session, hours_ago=3)

    result = _run_normal_check(db_session)

    assert not any(a["type"] == "dead_canary" for a in result)


def test_dead_canary_no_trigger_no_heartbeats(db_session):
    """Dead canary does not fire on first run (no heartbeat records in DB)."""
    result = _run_normal_check(db_session)

    assert not any(a["type"] == "dead_canary" for a in result)


def test_dead_canary_dedup(db_session):
    """Dead canary alert not sent again if already alerted within 6h cooldown."""
    _add_heartbeat(db_session, hours_ago=12)
    # Simulate a dead_canary alert already sent 1h ago
    db_session.add(AlertLog(
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        alert_type="dead_canary", severity="red",
        message="dead_canary", btc_price=None, eth_price=None,
        metric_value=12.0, notified=1,
    ))
    db_session.commit()

    result = _run_normal_check(db_session)

    assert not any(a["type"] == "dead_canary" for a in result)
