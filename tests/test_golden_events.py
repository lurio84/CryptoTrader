"""Golden tests: replay real historical market snapshots through
``alerts.discord_bot.check_and_alert`` and verify the expected set of alert
types fires (and that none of the forbidden ones leak).

Acts as a regression net for refactors that touch surrounding code
(e.g. M8 fee changes in backtesting engines) but should leave the alert
logic untouched. Snapshots are derived from ``data/research_cache``
CSVs -- see ``tests/fixtures/golden_events.csv``.
"""

import csv
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden_events.csv"


def _make_session_ctx(session):
    @contextmanager
    def _ctx():
        yield session
    return _ctx


def _parse_alerts(value: str) -> set[str]:
    return {a for a in (value or "").split(";") if a}


def _load_events() -> list[dict]:
    with open(FIXTURE_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


GOLDEN_EVENTS = _load_events()


@pytest.mark.parametrize("event", GOLDEN_EVENTS, ids=lambda r: r["event_id"])
def test_golden_event_alerts(event, db_session):
    prices = {
        "btc_price": float(event["btc_price"]),
        "btc_price_eur": float(event["btc_price_eur"]),
        "btc_change_24h": float(event["btc_change_24h"]),
        "eth_price": float(event["eth_price"]),
        "eth_change_24h": float(event["eth_change_24h"]),
        "eth_price_eur": float(event["eth_price_eur"]),
    }
    funding = float(event["funding_rate"])
    sp500 = float(event["sp500_5d"])
    expected = _parse_alerts(event["expected_alerts"])
    forbidden = _parse_alerts(event["forbidden_alerts"])

    with (
        patch("alerts.discord_bot.fetch_prices", return_value=prices),
        patch("alerts.discord_bot.fetch_funding_rate", return_value=funding),
        patch("alerts.discord_bot.fetch_sp500_change", return_value=sp500),
        patch("alerts.discord_bot.send_discord_message", return_value=True),
        patch("alerts.discord_bot.init_db"),
        patch("alerts.discord_bot.get_session", _make_session_ctx(db_session)),
    ):
        from alerts.discord_bot import check_and_alert
        triggered = check_and_alert()

    types = {a["type"] for a in triggered}
    missing = expected - types
    leaked = forbidden & types

    assert not missing, (
        "Missing expected alerts for {!r} ({}): {} -- triggered={}"
        .format(event["event_id"], event["date"], sorted(missing), sorted(types))
    )
    assert not leaked, (
        "Forbidden alerts fired for {!r} ({}): {} -- triggered={}"
        .format(event["event_id"], event["date"], sorted(leaked), sorted(types))
    )
