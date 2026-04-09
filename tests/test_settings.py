from config.settings import Settings


def test_default_settings():
    s = Settings()
    assert s.trading_mode == "paper"
    assert s.default_exchange == "binance"
    assert "BTC/USDT" in s.default_symbols
    assert s.risk.max_position_pct == 0.05
    assert s.risk.max_daily_drawdown_pct == 0.05
    assert s.maker_fee_pct == 0.001
    assert s.taker_fee_pct == 0.001


def test_fee_calculations():
    s = Settings()
    trade_cost = 100.0  # 100 USDT trade
    maker_fee = trade_cost * s.maker_fee_pct
    taker_fee = trade_cost * s.taker_fee_pct
    slippage = trade_cost * s.slippage_pct

    # Round trip cost
    round_trip = (taker_fee * 2) + (slippage * 2)
    assert round_trip == pytest.approx(0.3, abs=0.01)


import pytest
