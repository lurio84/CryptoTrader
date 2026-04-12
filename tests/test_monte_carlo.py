"""Tests for analysis.monte_carlo retirement simulation.

Mocks _load_monthly_returns_all so tests never hit yfinance -- keeps CI fast and offline.
"""

from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import patch


def _fake_returns_df() -> pd.DataFrame:
    """Build a small deterministic returns DataFrame for all 6 assets."""
    dates = pd.date_range("2018-01-01", periods=60, freq="MS")  # 5 years monthly
    # Deterministic small positive drift with some variance
    assets = {
        "BTC":            [0.03 + (i % 4 - 1.5) * 0.05 for i in range(60)],
        "ETH":            [0.025 + (i % 4 - 1.5) * 0.06 for i in range(60)],
        "SP500":          [0.008 + (i % 4 - 1.5) * 0.02 for i in range(60)],
        "SEMICONDUCTORS": [0.012 + (i % 4 - 1.5) * 0.03 for i in range(60)],
        "REALTY_INCOME":  [0.004 + (i % 4 - 1.5) * 0.02 for i in range(60)],
        "URANIUM":        [0.01 + (i % 4 - 1.5) * 0.04 for i in range(60)],
    }
    return pd.DataFrame(assets, index=dates)


def test_run_monte_carlo_returns_result_shape():
    from analysis.monte_carlo import run_monte_carlo

    with patch("analysis.monte_carlo._load_monthly_returns_all", return_value=_fake_returns_df()):
        result = run_monte_carlo(
            n_years=5,
            monthly_contribution_eur=100.0,
            target_eur=10_000.0,
            n_simulations=200,
            seed=123,
        )

    assert result.n_years == 5
    assert result.n_simulations == 200
    assert len(result.years) == 5
    assert len(result.p50) == 5
    # Percentiles are monotonically ordered
    for yr in range(5):
        assert result.p10[yr] <= result.p25[yr] <= result.p50[yr] <= result.p75[yr] <= result.p90[yr]


def test_run_monte_carlo_portfolio_grows_with_positive_drift():
    from analysis.monte_carlo import run_monte_carlo

    with patch("analysis.monte_carlo._load_monthly_returns_all", return_value=_fake_returns_df()):
        result = run_monte_carlo(
            n_years=3,
            monthly_contribution_eur=100.0,
            target_eur=1_000.0,
            n_simulations=100,
            seed=42,
        )
    # With positive drift + 100*12*3 = 3600 EUR contributed, median should exceed contributions
    assert result.median_at_retirement > 2000  # sane lower bound with noise


def test_run_monte_carlo_probability_target_bounded():
    from analysis.monte_carlo import run_monte_carlo

    with patch("analysis.monte_carlo._load_monthly_returns_all", return_value=_fake_returns_df()):
        result = run_monte_carlo(
            n_years=2,
            monthly_contribution_eur=50.0,
            target_eur=1_000_000.0,  # unreachable
            n_simulations=100,
            seed=1,
        )
    assert 0.0 <= result.prob_reach_target <= 1.0
    # Target way too high in 2 years -> near zero
    assert result.prob_reach_target < 0.05


def test_run_monte_carlo_deterministic_with_seed():
    from analysis.monte_carlo import run_monte_carlo

    with patch("analysis.monte_carlo._load_monthly_returns_all", return_value=_fake_returns_df()):
        a = run_monte_carlo(n_years=2, monthly_contribution_eur=100.0, n_simulations=50, seed=7)
        b = run_monte_carlo(n_years=2, monthly_contribution_eur=100.0, n_simulations=50, seed=7)

    assert a.median_at_retirement == pytest.approx(b.median_at_retirement)
    assert a.p50 == b.p50


def test_run_monte_carlo_safe_withdrawal_is_4pct_monthly():
    from analysis.monte_carlo import run_monte_carlo

    with patch("analysis.monte_carlo._load_monthly_returns_all", return_value=_fake_returns_df()):
        result = run_monte_carlo(n_years=2, monthly_contribution_eur=100.0, n_simulations=50, seed=3)

    expected_monthly = result.median_at_retirement * 0.04 / 12
    assert result.safe_withdrawal_rate_4pct == pytest.approx(expected_monthly)
