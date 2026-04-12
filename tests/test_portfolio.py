"""Tests for data/portfolio.py -- FIFO cost basis and IRPF Spain tax calculation."""

import os
import tempfile
from datetime import datetime

import pytest

from data.portfolio import (
    FIFOQueue,
    compute_spanish_tax,
    calculate_portfolio_status,
    calculate_tax_report,
    build_xirr_cash_flows,
    calculate_xirr,
    csv_to_trades,
    compute_tax_headroom,
)


# ---------------------------------------------------------------------------
# compute_spanish_tax
# ---------------------------------------------------------------------------

def test_irpf_first_bracket():
    """Gain within first bracket (<=6000) taxed at 19%."""
    tax = compute_spanish_tax(1_000.0)
    assert abs(tax - 190.0) < 0.01


def test_irpf_two_brackets():
    """Gain spanning first two brackets: 6k@19% + 4k@21%."""
    # 6000 * 0.19 + 4000 * 0.21 = 1140 + 840 = 1980
    tax = compute_spanish_tax(10_000.0)
    assert abs(tax - 1_980.0) < 0.01


def test_irpf_zero_gain():
    """Zero or negative gain -> no tax."""
    assert compute_spanish_tax(0.0) == 0.0
    assert compute_spanish_tax(-500.0) == 0.0


# ---------------------------------------------------------------------------
# FIFOQueue
# ---------------------------------------------------------------------------

def test_fifo_single_buy():
    """After one buy, units and avg cost are correct."""
    q = FIFOQueue()
    q.buy(units=1.0, price_eur=30_000.0, fee_eur=1.0)
    assert abs(q.total_units - 1.0) < 1e-9
    # cost_per_unit = (1 * 30000 + 1) / 1 = 30001
    assert abs(q.avg_cost_eur - 30_001.0) < 0.01


def test_fifo_sell_consumes_first_lot():
    """Selling from two lots uses the oldest lot first (FIFO)."""
    q = FIFOQueue()
    q.buy(units=1.0, price_eur=30_000.0, fee_eur=0.0)
    q.buy(units=1.0, price_eur=40_000.0, fee_eur=0.0)

    cost_basis, sold = q.sell(0.5)
    # First lot has cost 30000/unit, so 0.5 units = 15000 cost basis
    assert abs(cost_basis - 15_000.0) < 0.01
    assert abs(sold - 0.5) < 1e-9
    assert abs(q.total_units - 1.5) < 1e-9


# ---------------------------------------------------------------------------
# calculate_portfolio_status
# ---------------------------------------------------------------------------

def _trade(date_str, side, units, price_eur, fee_eur=1.0):
    return {
        "date": datetime.strptime(date_str, "%Y-%m-%d"),
        "asset": "BTC",
        "side": side,
        "units": units,
        "price_eur": price_eur,
        "fee_eur": fee_eur,
    }


def test_portfolio_single_buy_unrealized_gain():
    """Buy 1 BTC at 30k, current price 50k -> unrealized gain = 20k (approx)."""
    trades = [_trade("2023-01-01", "buy", 1.0, 30_000.0, fee_eur=1.0)]
    result = calculate_portfolio_status(
        asset="BTC",
        trades=trades,
        current_price_eur=50_000.0,
        dca_out_base=80_000,
        dca_out_step=20_000,
    )

    assert abs(result["units_held"] - 1.0) < 1e-9
    # avg cost = 30001 (price + fee)
    # unrealized = 50000 - 30001 = 19999
    assert result["unrealized_gain_eur"] > 19_990
    assert result["unrealized_gain_eur"] < 20_010
    assert result["buy_count"] == 1
    assert result["sell_count"] == 0


def test_portfolio_fifo_partial_sell():
    """Buy 1 BTC at 30k + 0.5 BTC at 40k, sell 0.7 BTC at 50k.
    FIFO cost basis: 0.7 * 30k = 21k. Proceeds: 0.7 * 50k = 35k. Gain = 14k.
    """
    trades = [
        _trade("2022-01-01", "buy",  1.0, 30_000.0, fee_eur=0.0),
        _trade("2022-06-01", "buy",  0.5, 40_000.0, fee_eur=0.0),
        _trade("2023-01-01", "sell", 0.7, 50_000.0, fee_eur=0.0),
    ]
    result = calculate_portfolio_status(
        asset="BTC",
        trades=trades,
        current_price_eur=50_000.0,
        dca_out_base=80_000,
        dca_out_step=20_000,
    )

    # Remaining units: 1.0 + 0.5 - 0.7 = 0.8
    assert abs(result["units_held"] - 0.8) < 1e-6
    # Realized gain: proceeds(35000) - cost_basis(21000) = 14000
    assert abs(result["realized_gain_eur"] - 14_000.0) < 1.0
    assert result["buy_count"] == 2
    assert result["sell_count"] == 1


def test_portfolio_empty_trades():
    """No trades -> zero units, no crash."""
    result = calculate_portfolio_status(
        asset="BTC",
        trades=[],
        current_price_eur=50_000.0,
        dca_out_base=80_000,
        dca_out_step=20_000,
    )
    assert result["units_held"] == 0.0
    assert result["buy_count"] == 0
    assert result["irpf_estimate_eur"] == 0.0


# ---------------------------------------------------------------------------
# calculate_tax_report
# ---------------------------------------------------------------------------

def test_tax_report_basic_gain():
    """Buy 1 BTC at 30k, sell 1 BTC at 50k in 2024 -> 20k gain."""
    trades = [
        _trade("2023-01-01", "buy",  1.0, 30_000.0, fee_eur=0.0),
        _trade("2024-06-01", "sell", 1.0, 50_000.0, fee_eur=0.0),
    ]
    result = calculate_tax_report(trades, year=2024)

    assert len(result["rows"]) == 1
    assert abs(result["total_gain_eur"] - 20_000.0) < 0.01
    assert result["total_irpf_eur"] > 0
    assert len(result["bracket_breakdown"]) >= 1
    row = result["rows"][0]
    assert row["asset"] == "BTC"
    assert abs(row["gain_eur"] - 20_000.0) < 0.01


def test_tax_report_year_filter():
    """FIFO state is maintained across years; each year only sees its own sells."""
    trades = [
        _trade("2022-01-01", "buy",  1.0, 20_000.0, fee_eur=0.0),
        _trade("2023-06-01", "sell", 0.5, 30_000.0, fee_eur=0.0),
        _trade("2024-06-01", "sell", 0.5, 40_000.0, fee_eur=0.0),
    ]
    result_2023 = calculate_tax_report(trades, year=2023)
    result_2024 = calculate_tax_report(trades, year=2024)

    assert len(result_2023["rows"]) == 1
    assert len(result_2024["rows"]) == 1
    # 2023: 0.5 BTC sold at 30k, cost basis 10k -> gain 5k
    assert abs(result_2023["total_gain_eur"] - 5_000.0) < 1.0
    # 2024: 0.5 BTC sold at 40k, remaining cost basis 10k -> gain 10k
    assert abs(result_2024["total_gain_eur"] - 10_000.0) < 1.0


def test_tax_report_no_sells_in_year():
    """No sells in requested year -> empty rows, zero gain and tax."""
    trades = [_trade("2023-01-01", "buy", 1.0, 30_000.0, fee_eur=0.0)]
    result = calculate_tax_report(trades, year=2024)

    assert result["rows"] == []
    assert result["total_gain_eur"] == 0.0
    assert result["total_irpf_eur"] == 0.0
    assert result["bracket_breakdown"] == []


# ---------------------------------------------------------------------------
# build_xirr_cash_flows + calculate_xirr
# ---------------------------------------------------------------------------

def test_xirr_cash_flows_buy_no_sell():
    """Single buy, no sell -> one negative flow + terminal positive (current value)."""
    trades = [_trade("2023-01-01", "buy", 1.0, 30_000.0, fee_eur=0.0)]
    flows = build_xirr_cash_flows(trades, current_price_eur=45_000.0)

    assert len(flows) == 2
    assert flows[0][1] < 0           # buy is outflow
    assert flows[1][1] > 0           # current value is inflow
    assert abs(flows[0][1] - (-30_000.0)) < 0.01
    assert abs(flows[1][1] - 45_000.0) < 0.01


def test_xirr_cash_flows_fully_sold():
    """Buy then fully sell -> two flows, no terminal flow (units_remaining == 0)."""
    trades = [
        _trade("2023-01-01", "buy",  1.0, 30_000.0, fee_eur=0.0),
        _trade("2023-06-01", "sell", 1.0, 40_000.0, fee_eur=0.0),
    ]
    flows = build_xirr_cash_flows(trades, current_price_eur=40_000.0)

    assert len(flows) == 2
    assert flows[0][1] < 0   # buy outflow
    assert flows[1][1] > 0   # sell inflow


def test_calculate_xirr_too_few_flows():
    """Fewer than 2 cash flows -> None."""
    assert calculate_xirr([]) is None
    assert calculate_xirr([(datetime(2023, 1, 1), -1_000.0)]) is None


def test_calculate_xirr_known_return():
    """Buy 30k, worth 45k exactly one year later -> ~50% annualized XIRR."""
    flows = [
        (datetime(2023, 1, 1), -30_000.0),
        (datetime(2024, 1, 1),  45_000.0),
    ]
    result = calculate_xirr(flows)
    assert result is not None
    assert abs(result - 0.50) < 0.02


def test_calculate_xirr_no_solution():
    """All-negative cash flows -> no valid rate -> None."""
    flows = [
        (datetime(2023, 1, 1), -1_000.0),
        (datetime(2024, 1, 1), -2_000.0),
    ]
    assert calculate_xirr(flows) is None


# ---------------------------------------------------------------------------
# csv_to_trades
# ---------------------------------------------------------------------------

def _write_tmp_csv(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


def test_csv_to_trades_valid():
    """Valid CSV row is parsed into a correct trade dict."""
    csv_content = (
        "date,asset,side,units,price_eur,fee_eur,source\n"
        "2024-01-15,BTC,buy,0.001,40000.00,0.00,sparplan\n"
    )
    path = _write_tmp_csv(csv_content)
    try:
        trades = csv_to_trades(path)
        assert len(trades) == 1
        t = trades[0]
        assert t["asset"] == "BTC"
        assert t["side"] == "buy"
        assert abs(t["units"] - 0.001) < 1e-9
        assert abs(t["price_eur"] - 40_000.0) < 0.01
        assert t["date"] == datetime(2024, 1, 15)
        assert t["source"] == "sparplan"
    finally:
        os.unlink(path)


def test_csv_to_trades_unknown_asset():
    """Unknown asset raises ValueError mentioning 'unknown asset'."""
    csv_content = (
        "date,asset,side,units,price_eur,fee_eur\n"
        "2024-01-15,DOGE,buy,100,0.10,0.00\n"
    )
    path = _write_tmp_csv(csv_content)
    try:
        with pytest.raises(ValueError, match="unknown asset"):
            csv_to_trades(path)
    finally:
        os.unlink(path)


def test_csv_to_trades_missing_required_field():
    """CSV without 'date' column raises ValueError."""
    csv_content = (
        "asset,side,units,price_eur\n"
        "BTC,buy,0.001,40000\n"
    )
    path = _write_tmp_csv(csv_content)
    try:
        with pytest.raises(ValueError):
            csv_to_trades(path)
    finally:
        os.unlink(path)


def test_csv_to_trades_file_not_found():
    """Non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        csv_to_trades("/nonexistent/path/trades.csv")


# ---------------------------------------------------------------------------
# compute_tax_headroom
# ---------------------------------------------------------------------------

def test_tax_headroom_first_bracket():
    """1000 EUR realized -> in 19% bracket, headroom = 5000 to 6000 limit."""
    h = compute_tax_headroom(1_000.0)
    assert h["current_rate_pct"] == pytest.approx(19.0)
    assert h["headroom_eur"] == pytest.approx(5_000.0)
    assert "19%" in h["current_bracket_label"]


def test_tax_headroom_second_bracket():
    """10000 EUR realized -> in 21% bracket (between 6k and 50k)."""
    h = compute_tax_headroom(10_000.0)
    assert h["current_rate_pct"] == pytest.approx(21.0)
    assert h["headroom_eur"] == pytest.approx(40_000.0)


def test_tax_headroom_zero():
    """0 EUR realized -> first bracket, full headroom of 6000."""
    h = compute_tax_headroom(0.0)
    assert h["current_rate_pct"] == pytest.approx(19.0)
    assert h["headroom_eur"] == pytest.approx(6_000.0)


def test_tax_headroom_top_bracket():
    """400000 EUR realized -> top bracket, no headroom."""
    h = compute_tax_headroom(400_000.0)
    assert h["current_rate_pct"] == pytest.approx(28.0)
    assert h["headroom_eur"] is None


# ---------------------------------------------------------------------------
# cmd_tax_headroom (CLI integration)
# ---------------------------------------------------------------------------

def test_cmd_tax_headroom_no_trades(db_session, capsys):
    """With empty DB, tax-headroom prints informational message."""
    import argparse
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def _session_ctx():
        yield db_session

    args = argparse.Namespace(year=2024)
    with (
        patch("data.database.get_session", _session_ctx),
        patch("data.database.init_db"),
        patch("data.market_data.fetch_prices", return_value={
            "btc_price_eur": 70_000.0, "eth_price_eur": 1_800.0,
        }),
    ):
        from cli.commands_portfolio import cmd_tax_headroom
        cmd_tax_headroom(args)

    out = capsys.readouterr().out
    assert "No hay" in out or "sin ganancias" in out.lower() or "realizadas" in out.lower()


def test_cmd_tax_headroom_with_realized_gains(db_session, capsys):
    """With sell trades, shows bracket and headroom."""
    import argparse
    from contextlib import contextmanager
    from datetime import datetime as _dt
    from unittest.mock import patch
    from data.models import UserTrade

    db_session.add(UserTrade(
        date=_dt(2024, 1, 1), asset="BTC", asset_class="crypto",
        side="buy", units=0.1, price_eur=30_000.0, fee_eur=0.0, source="sparplan",
    ))
    db_session.add(UserTrade(
        date=_dt(2024, 6, 1), asset="BTC", asset_class="crypto",
        side="sell", units=0.05, price_eur=60_000.0, fee_eur=0.0, source="dca_out",
    ))
    db_session.commit()

    @contextmanager
    def _session_ctx():
        yield db_session

    args = argparse.Namespace(year=2024)
    with (
        patch("data.database.get_session", _session_ctx),
        patch("data.database.init_db"),
        patch("data.market_data.fetch_prices", return_value={
            "btc_price_eur": 70_000.0, "eth_price_eur": 1_800.0,
        }),
    ):
        from cli.commands_portfolio import cmd_tax_headroom
        cmd_tax_headroom(args)

    out = capsys.readouterr().out
    assert "2024" in out
    assert "Margen" in out
    assert "tramo" in out.lower()


# ---------------------------------------------------------------------------
# Dividends and staking in calculate_portfolio_status and calculate_tax_report
# ---------------------------------------------------------------------------

_BASE_TRADE = {
    "date": datetime(2024, 1, 1), "asset": "BTC", "asset_class": "crypto",
    "side": "buy", "units": 0.1, "price_eur": 30_000.0, "fee_eur": 0.0, "source": "sparplan", "notes": None,
}


def test_fifo_ignores_dividend_side():
    """dividend records must NOT affect FIFO cost basis or units_held."""
    trades = [
        {**_BASE_TRADE, "asset": "REALTY_INCOME", "asset_class": "etf",
         "side": "dividend", "units": 0.0, "price_eur": 12.50},
    ]
    s = calculate_portfolio_status("REALTY_INCOME", trades, 55.0, 1_000_000, 1)
    assert s["units_held"] == pytest.approx(0.0)
    assert s["realized_gain_eur"] == pytest.approx(0.0)


def test_fifo_ignores_staking_side():
    """staking records must NOT affect FIFO cost basis."""
    trades = [
        {**_BASE_TRADE, "asset": "ETH", "side": "staking", "units": 0.005, "price_eur": 1_800.0},
    ]
    s = calculate_portfolio_status("ETH", trades, 2_000.0, 3_000, 1_000)
    assert s["units_held"] == pytest.approx(0.0)


def test_tax_report_separates_income_from_gains():
    """calculate_tax_report returns income_rows separately from capital gains."""
    trades = [
        # Buy BTC and sell it for a gain
        {**_BASE_TRADE},
        {**_BASE_TRADE, "date": datetime(2024, 6, 1), "side": "sell", "units": 0.05, "price_eur": 60_000.0},
        # Dividend record (capital income, not gain)
        {**_BASE_TRADE, "asset": "REALTY_INCOME", "asset_class": "etf",
         "date": datetime(2024, 3, 1), "side": "dividend", "units": 0.0, "price_eur": 12.50},
    ]
    report = calculate_tax_report(trades, 2024)

    assert report["total_gain_eur"] > 0          # BTC sell gain
    assert len(report["rows"]) == 1               # only the sell
    assert len(report["income_rows"]) == 1        # only the dividend
    assert report["income_rows"][0]["amount_eur"] == pytest.approx(12.50)
    assert report["total_income_eur"] == pytest.approx(12.50)
    assert report["total_income_irpf_eur"] == pytest.approx(12.50 * 0.19)


def test_tax_report_income_year_filter():
    """Dividend from different year not included in target year income_rows."""
    trades = [
        {**_BASE_TRADE, "asset": "REALTY_INCOME", "asset_class": "etf",
         "date": datetime(2023, 3, 1), "side": "dividend", "units": 0.0, "price_eur": 12.50},
    ]
    report = calculate_tax_report(trades, 2024)
    assert len(report["income_rows"]) == 0
    assert report["total_income_eur"] == pytest.approx(0.0)
