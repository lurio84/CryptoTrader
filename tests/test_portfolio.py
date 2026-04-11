"""Tests for data/portfolio.py -- FIFO cost basis and IRPF Spain tax calculation."""

from datetime import datetime

import pytest

from data.portfolio import FIFOQueue, compute_spanish_tax, calculate_portfolio_status


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
