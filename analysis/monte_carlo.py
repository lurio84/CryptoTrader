"""Monte Carlo retirement projection using bootstrap resampling.

Method
------
1. Load maximum available daily price history for all 6 assets via yfinance:
   BTC-USD, ETH-USD, SPY (S&P 500 proxy), SOXX (semiconductors),
   O (Realty Income), URA (uranium).
2. Resample to monthly prices, compute monthly log returns per asset.
3. Build a single weighted portfolio monthly return series using Sparplan
   target weights (preserving cross-asset correlations within each month).
   Inner join on months -- limits history to the shortest available asset.
4. Run N bootstrap simulations (vectorized):
   - Resample T*12 monthly returns with replacement.
   - Accumulate month by month: value = value * (1 + return) + monthly_DCA.
   - Snapshot value at each year-end.
5. Compute percentile bands (p10/p25/p50/p75/p90) per year.

Data availability note
----------------------
SPY: 1993+, URA: 2008+, SOXX: 2001+, BTC-USD: 2014+, ETH-USD: 2017+, O: 1994+
Inner join limits history to ~2017-present (ETH bottleneck).
The simulation uses this aligned period for bootstrapping.

Usage
-----
    from analysis.monte_carlo import run_monte_carlo
    result = run_monte_carlo(n_years=35, monthly_contribution_eur=140.0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Sparplan target weights (must match SPARPLAN_MONTHLY in main.py)
# ---------------------------------------------------------------------------

_SPARPLAN_MONTHLY = {
    "BTC":           32.0,
    "ETH":            8.0,
    "SP500":         64.0,
    "SEMICONDUCTORS":16.0,
    "REALTY_INCOME": 16.0,
    "URANIUM":        4.0,
}
_SPARPLAN_TOTAL = sum(_SPARPLAN_MONTHLY.values())  # 140

_WEIGHTS = {k: v / _SPARPLAN_TOTAL for k, v in _SPARPLAN_MONTHLY.items()}

# yfinance tickers for each asset
_TICKERS = {
    "BTC":           "BTC-USD",
    "ETH":           "ETH-USD",
    "SP500":         "SPY",
    "SEMICONDUCTORS":"SOXX",
    "REALTY_INCOME": "O",
    "URANIUM":       "URA",
}

_CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MonteCarloResult:
    years: list[int]
    p10:   list[float]
    p25:   list[float]
    p50:   list[float]
    p75:   list[float]
    p90:   list[float]
    prob_reach_target:          float
    median_at_retirement:       float
    safe_withdrawal_rate_4pct:  float   # EUR/month at 4% annual rule
    n_simulations: int
    n_years:       int
    data_start_year: int
    data_end_year:   int
    data_months:     int


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_monthly_returns_all() -> pd.DataFrame:
    """Load and align monthly returns for all 6 assets.

    Returns a DataFrame with one column per asset, indexed by month-start date.
    Rows contain simple monthly returns (0.05 = 5% gain).
    Only months where ALL assets have data are included (inner join).
    """
    import yfinance as yf

    monthly_prices: dict[str, pd.Series] = {}

    for asset, ticker in _TICKERS.items():
        cache_file = _CACHE_DIR / f"mc_{asset.lower()}_monthly.csv"
        try:
            # Try to load from cache first
            if cache_file.exists():
                df_cache = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                price_series = df_cache["close"].squeeze()
            else:
                raise FileNotFoundError("no cache")
        except Exception:
            price_series = None

        # Download from yfinance (max history)
        try:
            raw = yf.download(ticker, period="max", interval="1mo",
                              progress=False, auto_adjust=True)
            if raw.empty:
                raise ValueError(f"No data for {ticker}")
            # yfinance may return MultiIndex columns if auto_adjust
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            closes = raw["Close"].dropna()
            closes.index = closes.index.to_period("M").to_timestamp()
            closes.name = asset
            # Save to cache
            closes.to_frame("close").to_csv(cache_file)
            price_series = closes
        except Exception as e:
            if price_series is None:
                raise RuntimeError(
                    f"Could not load data for {asset} ({ticker}): {e}\n"
                    "Make sure yfinance is installed and you have internet access."
                ) from e

        monthly_prices[asset] = price_series

    # Build aligned DataFrame of prices
    df = pd.DataFrame(monthly_prices)
    df = df.dropna()  # inner join on all assets

    # Compute simple monthly returns
    returns = df.pct_change().dropna()
    return returns


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_monte_carlo(
    n_years: int = 35,
    monthly_contribution_eur: float = 140.0,
    target_eur: float = 1_000_000.0,
    n_simulations: int = 5000,
    current_portfolio_eur: float = 0.0,
    seed: int = 42,
) -> MonteCarloResult:
    """Run Monte Carlo retirement projection.

    Args:
        n_years: Investment horizon in years.
        monthly_contribution_eur: DCA added every month (EUR).
        target_eur: Portfolio target to measure probability against.
        n_simulations: Number of bootstrap paths.
        current_portfolio_eur: Starting portfolio value (EUR).
        seed: Random seed for reproducibility.

    Returns:
        MonteCarloResult with percentile bands per year and summary stats.
    """
    # Load historical returns
    returns_df = _load_monthly_returns_all()

    data_start = returns_df.index.min()
    data_end   = returns_df.index.max()
    data_months = len(returns_df)

    # Build single weighted portfolio return series
    portfolio_returns = pd.Series(0.0, index=returns_df.index)
    for asset, weight in _WEIGHTS.items():
        portfolio_returns += weight * returns_df[asset]

    port_arr = portfolio_returns.values.astype(np.float64)
    T = n_years * 12

    rng = np.random.default_rng(seed)

    # Vectorized bootstrap: shape (n_simulations, T)
    indices = rng.integers(0, len(port_arr), size=(n_simulations, T))
    sampled = port_arr[indices]  # (n_simulations, T)

    # Simulate accumulation month by month
    values = np.full(n_simulations, float(current_portfolio_eur), dtype=np.float64)
    yearly_snapshots: list[np.ndarray] = []

    for month in range(T):
        values = values * (1.0 + sampled[:, month]) + monthly_contribution_eur
        # Clip negative values (theoretically impossible with DCA but guard)
        np.maximum(values, 0.0, out=values)
        if (month + 1) % 12 == 0:
            yearly_snapshots.append(values.copy())

    # Compute percentile bands
    years_list = list(range(1, n_years + 1))
    p10, p25, p50, p75, p90 = [], [], [], [], []
    for snap in yearly_snapshots:
        p10.append(float(np.percentile(snap, 10)))
        p25.append(float(np.percentile(snap, 25)))
        p50.append(float(np.percentile(snap, 50)))
        p75.append(float(np.percentile(snap, 75)))
        p90.append(float(np.percentile(snap, 90)))

    final_values = yearly_snapshots[-1]
    prob_target  = float(np.mean(final_values >= target_eur))
    median_final = float(np.median(final_values))
    safe_withdrawal = median_final * 0.04 / 12  # 4% annual rule, monthly

    return MonteCarloResult(
        years=years_list,
        p10=p10, p25=p25, p50=p50, p75=p75, p90=p90,
        prob_reach_target=prob_target,
        median_at_retirement=median_final,
        safe_withdrawal_rate_4pct=safe_withdrawal,
        n_simulations=n_simulations,
        n_years=n_years,
        data_start_year=data_start.year,
        data_end_year=data_end.year,
        data_months=data_months,
    )
