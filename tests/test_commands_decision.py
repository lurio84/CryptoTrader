"""Tests for cli.commands_decision (tax-simulate, what-if, health-check, explain-alert)."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from data.models import AlertLog, UserTrade


def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


# ---------------------------------------------------------------------------
# tax-simulate
# ---------------------------------------------------------------------------

def test_tax_simulate_no_trades(db_session, capsys):
    args = argparse.Namespace(asset="BTC", units=0.1, price_eur=60_000.0, year=2024)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
    ):
        from cli.commands_decision import cmd_tax_simulate
        cmd_tax_simulate(args)

    out = capsys.readouterr().out
    assert "No hay operaciones" in out


def test_tax_simulate_gain_and_delta(db_session, capsys):
    db_session.add(UserTrade(
        date=datetime(2023, 1, 1), asset="BTC", asset_class="crypto",
        side="buy", units=0.2, price_eur=20_000.0, fee_eur=0.0, source="sparplan",
    ))
    db_session.commit()

    # year=None -> current year, so the synthetic sale (dated datetime.now()) counts
    args = argparse.Namespace(asset="BTC", units=0.1, price_eur=60_000.0, year=None)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
    ):
        from cli.commands_decision import cmd_tax_simulate
        cmd_tax_simulate(args)

    out = capsys.readouterr().out
    assert "SIMULACION" in out
    assert "Delta plusvalia" in out
    # Profit = (60000 - 20000) * 0.1 = 4000 EUR on synthetic sell (ignoring fees)
    assert "4,000" in out or "4000" in out
    assert "Net cash" in out


def test_tax_simulate_rejects_non_positive(capsys):
    args = argparse.Namespace(asset="BTC", units=0.0, price_eur=60_000.0, year=2024)
    with patch("cli.commands_decision.init_db"):
        from cli.commands_decision import cmd_tax_simulate
        cmd_tax_simulate(args)
    out = capsys.readouterr().out
    assert "positivos" in out


# ---------------------------------------------------------------------------
# what-if
# ---------------------------------------------------------------------------

def test_what_if_btc_price_shows_drift_and_dca(db_session, capsys):
    db_session.add(UserTrade(
        date=datetime(2023, 1, 1), asset="BTC", asset_class="crypto",
        side="buy", units=0.05, price_eur=25_000.0, fee_eur=0.0, source="sparplan",
    ))
    db_session.commit()

    args = argparse.Namespace(asset="BTC", price=150_000.0)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
        patch(
            "data.market_data.fetch_portfolio_prices_eur",
            return_value={"btc_eur": 130_000.0, "eth_eur": 3_000.0, "etf_prices": {}},
        ),
    ):
        from cli.commands_decision import cmd_what_if
        cmd_what_if(args)

    out = capsys.readouterr().out
    assert "WHAT-IF" in out
    assert "BTC" in out
    assert "DCA-out BTC niveles activados" in out


def test_what_if_no_trades(db_session, capsys):
    args = argparse.Namespace(asset="BTC", price=150_000.0)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
        patch(
            "data.market_data.fetch_portfolio_prices_eur",
            return_value={"btc_eur": 50_000.0, "eth_eur": 2_000.0, "etf_prices": {}},
        ),
    ):
        from cli.commands_decision import cmd_what_if
        cmd_what_if(args)
    out = capsys.readouterr().out
    assert "No hay operaciones" in out


# ---------------------------------------------------------------------------
# health-check
# ---------------------------------------------------------------------------

def test_health_check_reports_db_and_apis(db_session, capsys):
    # Add a recent heartbeat so we get an "OK" row
    db_session.add(AlertLog(
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
        alert_type="heartbeat", severity="green", message="heartbeat",
        btc_price=50_000.0, eth_price=2_500.0, metric_value=0.0, notified=1,
    ))
    db_session.commit()

    args = argparse.Namespace()
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
        patch("data.market_data.fetch_prices", return_value={
            "btc_price": 50_000.0, "btc_price_eur": 46_000.0, "btc_change_24h": 0.0,
            "eth_price": 2_500.0, "eth_price_eur": 2_300.0, "eth_change_24h": 0.0,
        }),
        patch("data.market_data.fetch_mvrv", return_value=1.5),
        patch("data.market_data.fetch_funding_rate", return_value=0.0001),
        patch("data.market_data.fetch_sp500_change", return_value=-0.5),
    ):
        from cli.commands_decision import cmd_health_check
        cmd_health_check(args)

    out = capsys.readouterr().out
    assert "Health Check" in out
    assert "CoinGecko" in out
    assert "CoinMetrics" in out
    assert "OKX" in out
    assert "Stooq" in out


# ---------------------------------------------------------------------------
# explain-alert
# ---------------------------------------------------------------------------

def test_explain_alert_by_id(db_session, capsys):
    db_session.add(AlertLog(
        timestamp=datetime(2024, 6, 1, 12, 0),
        alert_type="btc_crash", severity="red", message="BTC dropped 18%",
        btc_price=62_000.0, eth_price=3_200.0, metric_value=-18.0, notified=1,
    ))
    db_session.commit()
    row_id = db_session.query(AlertLog).first().id

    args = argparse.Namespace(id=row_id, type=None)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
    ):
        from cli.commands_decision import cmd_explain_alert
        cmd_explain_alert(args)

    out = capsys.readouterr().out
    assert "ALERT EXPLANATION" in out
    assert "btc_crash" in out
    assert "RED" in out


def test_explain_alert_missing(db_session, capsys):
    args = argparse.Namespace(id=9999, type=None)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
    ):
        from cli.commands_decision import cmd_explain_alert
        cmd_explain_alert(args)
    out = capsys.readouterr().out
    assert "no encontrada" in out.lower()


def test_explain_alert_requires_arg(db_session, capsys):
    args = argparse.Namespace(id=None, type=None)
    with (
        patch("cli.commands_decision.get_session", _make_session_ctx(db_session)),
        patch("cli.commands_decision.init_db"),
    ):
        from cli.commands_decision import cmd_explain_alert
        cmd_explain_alert(args)
    out = capsys.readouterr().out
    assert "--id" in out or "--type" in out
