"""Tests for the drift-check CLI command."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from data.models import AlertLog, UserTrade


def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


def _make_args(notify=False):
    args = argparse.Namespace()
    args.notify = notify
    return args


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
        date=datetime(2024, 1, 1),
        asset=asset, asset_class=asset_class,
        side="buy", units=units, price_eur=price_eur,
        fee_eur=0.0, source="sparplan",
    ))
    session.commit()


# Lazy imports in cmd_drift_check -> patch at source modules
_PATCHES_BASE = {
    "prices":  "data.market_data.fetch_prices",
    "etf":     "data.etf_prices.fetch_all_etf_prices_eur",
    "session": "data.database.get_session",
    "init_db": "data.database.init_db",
}

_DEFAULT_ETF = {
    "SP500": 500.0, "SEMICONDUCTORS": 200.0,
    "REALTY_INCOME": 50.0, "URANIUM": 10.0,
}


def _run_drift_check(db_session, notify=False, etf_prices=None):
    etf_ret = etf_prices if etf_prices is not None else _DEFAULT_ETF
    with (
        patch(_PATCHES_BASE["prices"], return_value=_normal_prices()),
        patch(_PATCHES_BASE["etf"], return_value=etf_ret),
        patch(_PATCHES_BASE["session"], _make_session_ctx(db_session)),
        patch(_PATCHES_BASE["init_db"]),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_drift_check
        cmd_drift_check(_make_args(notify=notify))


def test_drift_check_empty_portfolio(db_session, capsys):
    """Empty portfolio prints informational message, no crash."""
    _run_drift_check(db_session)
    out = capsys.readouterr().out
    assert "vacio" in out.lower() or "sin precios" in out.lower()


def test_drift_check_prints_table(db_session, capsys):
    """With portfolio data, drift table lists all assets."""
    _add_buy(db_session, "BTC", 0.1, 72_000.0)
    _add_buy(db_session, "ETH", 1.0, 1_800.0)
    _add_buy(db_session, "SP500", 10.0, 500.0, asset_class="etf")

    _run_drift_check(db_session)
    out = capsys.readouterr().out

    assert "BTC" in out
    assert "ETH" in out
    assert "SP500" in out


def test_drift_check_btc_overweight_shown(db_session, capsys):
    """Heavily BTC-overweighted portfolio shows REBALANCEAR status."""
    _add_buy(db_session, "BTC", 1.0, 72_000.0)

    # ETF prices all None -> only BTC has value -> BTC weight ~100% vs 22.86% target
    _run_drift_check(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    out = capsys.readouterr().out
    assert "REBALANCEAR" in out


def test_drift_check_suggestions_shown_on_drift(db_session, capsys):
    """When drift >10pp, 'Para rebalancear:' block with buy/sell amounts is shown."""
    # BTC only portfolio -> BTC ~100% vs 22.86% target (overweight -> Vende)
    # ETH at 0 units but price known -> drift only -5.71pp, below threshold
    _add_buy(db_session, "BTC", 1.0, 72_000.0)

    _run_drift_check(db_session, etf_prices={
        "SP500": None, "SEMICONDUCTORS": None,
        "REALTY_INCOME": None, "URANIUM": None,
    })
    out = capsys.readouterr().out

    assert "Para rebalancear:" in out
    assert "Vende" in out
    assert "BTC" in out
    # Amount should be non-zero
    import re
    amounts = re.findall(r"(?:Compra|Vende) (\d+) EUR", out)
    assert amounts, "No EUR amount found in suggestions"
    assert int(amounts[0]) > 0


def test_drift_check_no_discord_without_notify(db_session, capsys):
    """Without --notify, no Discord alerts sent even with large drift."""
    _add_buy(db_session, "BTC", 1.0, 72_000.0)

    from unittest.mock import MagicMock
    mock_send = MagicMock()
    with (
        patch(_PATCHES_BASE["prices"], return_value=_normal_prices()),
        patch(_PATCHES_BASE["etf"], return_value={}),
        patch(_PATCHES_BASE["session"], _make_session_ctx(db_session)),
        patch(_PATCHES_BASE["init_db"]),
        patch("alerts.discord_bot.send_discord_message", mock_send),
    ):
        from cli.commands_ops import cmd_drift_check
        cmd_drift_check(_make_args(notify=False))

    mock_send.assert_not_called()
    out = capsys.readouterr().out
    assert "--notify" in out


def test_drift_check_discord_sent_with_notify(db_session, capsys):
    """With --notify and large drift, Discord alert is sent and logged."""
    _add_buy(db_session, "BTC", 1.0, 72_000.0)

    with (
        patch(_PATCHES_BASE["prices"], return_value=_normal_prices()),
        patch(_PATCHES_BASE["etf"], return_value={}),
        patch(_PATCHES_BASE["session"], _make_session_ctx(db_session)),
        patch(_PATCHES_BASE["init_db"]),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_drift_check
        cmd_drift_check(_make_args(notify=True))

    row = db_session.query(AlertLog).filter(
        AlertLog.alert_type.like("rebalance_drift_%")
    ).first()
    assert row is not None
    assert row.severity == "orange"


def test_drift_check_dedup(db_session, capsys):
    """Drift alert not re-sent if already logged within 7d cooldown."""
    _add_buy(db_session, "BTC", 1.0, 72_000.0)
    db_session.add(AlertLog(
        timestamp=datetime.utcnow() - timedelta(hours=24),
        alert_type="rebalance_drift_btc", severity="orange",
        message="rebalance_drift_btc", btc_price=80_000.0, eth_price=2_000.0,
        metric_value=77.0, notified=1,
    ))
    db_session.commit()

    with (
        patch(_PATCHES_BASE["prices"], return_value=_normal_prices()),
        patch(_PATCHES_BASE["etf"], return_value={}),
        patch(_PATCHES_BASE["session"], _make_session_ctx(db_session)),
        patch(_PATCHES_BASE["init_db"]),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from cli.commands_ops import cmd_drift_check
        cmd_drift_check(_make_args(notify=True))

    rows = db_session.query(AlertLog).filter_by(alert_type="rebalance_drift_btc").all()
    assert len(rows) == 1

    out = capsys.readouterr().out
    assert "ya enviado" in out
