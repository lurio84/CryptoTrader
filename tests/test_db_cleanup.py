"""Tests for the db-cleanup CLI command (cli/commands_ops.py)."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data.models import AlertLog


def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


def _make_args(keep_days=90):
    args = argparse.Namespace()
    args.keep_days = keep_days
    return args


def _add_alert(session, alert_type, days_ago):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(tzinfo=None)
    session.add(AlertLog(
        alert_type=alert_type,
        severity="green",
        message="test",
        btc_price=None,
        eth_price=None,
        metric_value=None,
        notified=0,
        timestamp=ts,
    ))
    session.commit()


def test_db_cleanup_deletes_old_records(db_session):
    """Records older than keep_days are deleted; recent records are kept."""
    _add_alert(db_session, "heartbeat", days_ago=100)
    _add_alert(db_session, "heartbeat", days_ago=1)

    with (
        patch("cli.commands_ops.init_db"),
        patch("data.database.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_db_cleanup
        cmd_db_cleanup(_make_args(keep_days=30))

    remaining = db_session.query(AlertLog).all()
    assert len(remaining) == 1
    assert remaining[0].alert_type == "heartbeat"
    # The remaining one is the recent record (days_ago=1)


def test_db_cleanup_keeps_recent_records(db_session):
    """Records within keep_days window are not deleted."""
    _add_alert(db_session, "btc_crash", days_ago=10)

    with (
        patch("cli.commands_ops.init_db"),
        patch("data.database.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_db_cleanup
        cmd_db_cleanup(_make_args(keep_days=90))

    remaining = db_session.query(AlertLog).all()
    assert len(remaining) == 1


def test_db_cleanup_empty_db(db_session):
    """Running cleanup on an empty DB completes without error."""
    with (
        patch("cli.commands_ops.init_db"),
        patch("data.database.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_db_cleanup
        cmd_db_cleanup(_make_args(keep_days=90))

    assert db_session.query(AlertLog).count() == 0
