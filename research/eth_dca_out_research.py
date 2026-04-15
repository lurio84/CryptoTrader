"""eth_dca_out_research.py
==========================
Research 14: ETH DCA-out strategy (formal backtest).

Motivation
----------
`eth_dca_out_Xk` alerts are in production with parameters:
    base=$3,000, step=$1,000, pct=3%, cooldown=30d, max=$50,000

These parameters were NEVER formally backtested. `exit_signals_research4.py`
only analyzes BTC and mentions ETH parameters in Part 3 as "suggested"
(line 705) by extrapolation from BTC. No simulation was run for ETH.

This script closes the gap: simulate pure hold vs DCA-out for ETH from
2018 to 2026 with IRPF (Spain), over a range of parameter combinations.

Critical context
----------------
- ETH all-time high: ~$4,831 (2021-11-10)
- ETH dataset max:    $4,831 (CoinMetrics)
- ETH has NEVER reached $5,000. Levels $5k+ in production are speculative.
- Current ETH price (2026-04): ~$2,190 (below all DCA-out levels)

Setup
-----
- Period:      2018-01-01 to 2026-04-01 (matches Research 3/4)
- Weekly DCA:  2 EUR/week (matches current ETH Sparplan)
- Tax model:   Spain IRPF 2024 brackets, FIFO cost basis, EUR/USD=1.10
- Cooldown:    30 days per level (matches production)
- Parameters tested:
    * base:  $3k, $4k, $5k
    * step:  $500, $1k, $2k
    * pct:   3%, 5%
- Plus the current production combo (base=$3k, step=$1k, pct=3%)

Metrics
-------
- Final equity (EUR, after taxes)
- CAGR
- Total sold (EUR)
- Total tax paid (EUR)
- Break-even ETH price at dataset end (ETH remaining)
- Nominal advantage vs pure hold

Run
---
    python research/eth_dca_out_research.py
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANALYSIS_START = "2018-01-01"
ANALYSIS_END   = "2026-04-01"

WEEKLY_ETH_EUR = 2.0   # current Sparplan allocation
SELL_FEE_EUR   = 0.0   # Trade Republic: 0 fees for crypto
EUR_USD_AVG    = 1.10  # average 2018-2026, consistent with Research 4

# Spain IRPF 2024 capital gains brackets (annual NET gain)
SPAIN_TAX_BRACKETS = [
    (6_000,       0.19),
    (50_000,      0.21),
    (200_000,     0.23),
    (300_000,     0.27),
    (float("inf"), 0.28),
]

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"
ETH_CACHE = CACHE_DIR / "eth_cm.csv"
RESULTS_FILE = CACHE_DIR / "eth_dca_out_results.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_eth_prices() -> pd.DataFrame:
    if not ETH_CACHE.exists():
        raise SystemExit(f"Missing cache {ETH_CACHE}. Run exit_strategy_research.py first.")
    df = pd.read_csv(ETH_CACHE, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df[(df["date"] >= ANALYSIS_START) & (df["date"] < ANALYSIS_END)]
    return df.sort_values("date").reset_index(drop=True)


def cagr(start_eur: float, end_eur: float, years: float) -> float:
    if start_eur <= 0 or end_eur <= 0 or years <= 0:
        return 0.0
    return (end_eur / start_eur) ** (1 / years) - 1


def compute_irpf(gain_eur: float) -> float:
    """Apply Spain IRPF 2024 brackets on the total annual NET gain (EUR)."""
    if gain_eur <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in SPAIN_TAX_BRACKETS:
        if gain_eur > lower:
            taxable = min(gain_eur, upper) - lower
            tax += taxable * rate
            lower = upper
            if gain_eur <= upper:
                break
    return tax


# ---------------------------------------------------------------------------
# Strategy simulations
# ---------------------------------------------------------------------------

def simulate_hold(prices_df: pd.DataFrame, weekly_eur: float) -> dict:
    """Pure DCA hold: buy every Monday, no sells, no taxes until the end."""
    cost_basis = deque()  # (units, eur_cost)
    total_invested = 0.0
    total_units = 0.0

    for _, row in prices_df.iterrows():
        if row["date"].weekday() != 0:  # Mondays only
            continue
        price_usd = row["price"]
        if price_usd <= 0:
            continue
        price_eur = price_usd / EUR_USD_AVG
        units = weekly_eur / price_eur
        cost_basis.append((units, weekly_eur))
        total_invested += weekly_eur
        total_units += units

    final_price_usd = prices_df["price"].iloc[-1]
    final_price_eur = final_price_usd / EUR_USD_AVG
    end_value_eur = total_units * final_price_eur
    gain = end_value_eur - total_invested
    tax = compute_irpf(gain)
    end_value_after_tax = end_value_eur - tax

    years = (prices_df["date"].iloc[-1] - prices_df["date"].iloc[0]).days / 365.25

    return {
        "strategy": "HOLD",
        "invested": total_invested,
        "units_end": total_units,
        "end_price_eur": final_price_eur,
        "end_value_pre_tax": end_value_eur,
        "tax": tax,
        "end_value_after_tax": end_value_after_tax,
        "total_sold_eur": 0.0,
        "cash_eur": 0.0,
        "cagr": cagr(total_invested, end_value_after_tax, years),
        "years": years,
    }


def simulate_dca_out(
    prices_df: pd.DataFrame,
    weekly_eur: float,
    base_usd: int,
    step_usd: int,
    pct: float,
    cooldown_days: int,
    max_level_usd: int = 50_000,
) -> dict:
    """DCA + DCA-out: weekly buys, plus sell `pct`% each time price crosses a level."""
    cost_basis: deque = deque()  # FIFO queue of (units, eur_cost_per_unit)
    total_invested = 0.0
    total_units = 0.0
    cash_eur = 0.0           # accumulated cash from sells
    total_sold_eur = 0.0     # gross EUR received
    total_gain_realized = 0.0  # lifetime realized gain (for tax calc, per-year below)
    level_cooldowns: dict[int, pd.Timestamp | None] = {}
    yearly_gains: dict[int, float] = {}
    n_sales = 0

    for _, row in prices_df.iterrows():
        date = row["date"]
        price_usd = float(row["price"])
        if price_usd <= 0:
            continue
        price_eur = price_usd / EUR_USD_AVG

        # 1. Weekly buy (Mondays)
        if date.weekday() == 0:
            units = weekly_eur / price_eur
            cost_basis.append((units, price_eur))  # store cost/unit in EUR
            total_invested += weekly_eur
            total_units += units

        # 2. Check DCA-out levels
        if total_units <= 0:
            continue
        level = base_usd
        while level <= max_level_usd:
            if price_usd >= level:
                last_fire = level_cooldowns.get(level)
                if last_fire is None or (date - last_fire) >= timedelta(days=cooldown_days):
                    # Sell pct% of current holdings at this moment
                    units_to_sell = total_units * (pct / 100.0)
                    if units_to_sell > 0 and units_to_sell <= total_units:
                        proceeds_eur = units_to_sell * price_eur - SELL_FEE_EUR
                        # FIFO cost basis
                        remaining = units_to_sell
                        cost_eur = 0.0
                        while remaining > 1e-12 and cost_basis:
                            lot_units, lot_cost_per_unit = cost_basis[0]
                            take = min(lot_units, remaining)
                            cost_eur += take * lot_cost_per_unit
                            if take >= lot_units - 1e-12:
                                cost_basis.popleft()
                            else:
                                cost_basis[0] = (lot_units - take, lot_cost_per_unit)
                            remaining -= take

                        gain_eur = proceeds_eur - cost_eur
                        year = date.year
                        yearly_gains[year] = yearly_gains.get(year, 0.0) + gain_eur
                        total_gain_realized += gain_eur
                        cash_eur += proceeds_eur
                        total_sold_eur += proceeds_eur
                        total_units -= units_to_sell
                        n_sales += 1
                        level_cooldowns[level] = date
            level += step_usd

    # End-of-simulation valuation
    final_price_usd = prices_df["price"].iloc[-1]
    final_price_eur = final_price_usd / EUR_USD_AVG
    remaining_value_eur = total_units * final_price_eur

    # Compute annual IRPF from realized gains by year (progressive brackets per year)
    total_tax_realized = sum(compute_irpf(g) for g in yearly_gains.values() if g > 0)

    # Unrealized gain tax (assume full liquidation at end date)
    remaining_cost_eur = sum(u * c for u, c in cost_basis)
    unrealized_gain = remaining_value_eur - remaining_cost_eur
    unrealized_tax = compute_irpf(unrealized_gain)

    end_value_after_tax = cash_eur + remaining_value_eur - total_tax_realized - unrealized_tax
    years = (prices_df["date"].iloc[-1] - prices_df["date"].iloc[0]).days / 365.25

    return {
        "strategy": f"DCA-out b=${base_usd//1000}k s=${step_usd//1000}k p={pct:.0f}%",
        "invested": total_invested,
        "units_end": total_units,
        "end_price_eur": final_price_eur,
        "end_value_pre_tax": cash_eur + remaining_value_eur,
        "tax": total_tax_realized + unrealized_tax,
        "tax_realized": total_tax_realized,
        "tax_unrealized": unrealized_tax,
        "end_value_after_tax": end_value_after_tax,
        "cash_eur": cash_eur,
        "total_sold_eur": total_sold_eur,
        "n_sales": n_sales,
        "remaining_value_eur": remaining_value_eur,
        "cagr": cagr(total_invested, end_value_after_tax, years),
        "years": years,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("ETH DCA-OUT STRATEGY RESEARCH (Research 14)")
    print("=" * 70)
    print(f"  Period: {ANALYSIS_START} - {ANALYSIS_END}")
    print(f"  Weekly Sparplan: {WEEKLY_ETH_EUR:.1f} EUR  |  EUR/USD={EUR_USD_AVG}")
    print(f"  Tax model: Spain IRPF 2024, FIFO cost basis")
    print()

    df = load_eth_prices()
    print(f"  ETH price series: N={len(df)}  range=${df['price'].min():.0f}-${df['price'].max():.0f}  last=${df['price'].iloc[-1]:.0f}")
    print()

    # Baseline
    hold = simulate_hold(df, WEEKLY_ETH_EUR)

    # DCA-out parameter grid (includes current production combo)
    grid = [
        # (base, step, pct, label)
        (3_000,  500, 3, "CURRENT_FINE"),     # more granular than prod
        (3_000, 1_000, 3, "PRODUCTION"),      # current production values
        (3_000, 1_000, 5, "prod_pct5"),
        (3_000, 2_000, 3, "base3_step2k"),
        (4_000, 1_000, 3, "base4_step1k"),
        (4_000, 1_000, 5, "base4_pct5"),
        (4_000, 2_000, 3, "base4_step2k"),
        (5_000, 1_000, 3, "base5_step1k"),  # base never reached historically
    ]

    results = [hold]
    for base, step, pct, label in grid:
        r = simulate_dca_out(df, WEEKLY_ETH_EUR, base, step, pct, cooldown_days=30)
        r["label"] = label
        results.append(r)

    # -------------- Print table --------------
    out = ["ETH DCA-OUT STRATEGY RESEARCH (Research 14)", "=" * 70]
    out.append(f"  Period: {ANALYSIS_START} - {ANALYSIS_END}  Weekly: {WEEKLY_ETH_EUR:.1f} EUR")
    out.append("")
    hdr = (f"  {'strategy':<24}  {'invested':>10}  {'end_value':>11}  {'tax':>9}  "
           f"{'after_tax':>11}  {'CAGR':>6}  {'n_sells':>7}  {'sold_eur':>10}")
    sep = "  " + "-" * 100
    out.append(hdr); out.append(sep)
    print(hdr); print(sep)

    for r in results:
        label = r.get("label", "")
        name = r["strategy"] + (f" [{label}]" if label else "")
        line = (f"  {name:<24}  {r['invested']:>10,.0f}  {r['end_value_pre_tax']:>11,.0f}  "
                f"{r['tax']:>9,.0f}  {r['end_value_after_tax']:>11,.0f}  "
                f"{r['cagr']*100:>5.1f}%  {r.get('n_sales', 0):>7}  {r.get('total_sold_eur', 0):>10,.0f}")
        out.append(line); print(line)

    out.append("")
    print()

    # -------------- Delta vs HOLD --------------
    out.append("DELTA vs HOLD (after-tax EUR, pp)")
    out.append("-" * 70)
    print("DELTA vs HOLD (after-tax EUR, pp)")
    print("-" * 70)
    hold_after = hold["end_value_after_tax"]
    for r in results[1:]:
        label = r.get("label", "")
        name = r["strategy"] + (f" [{label}]" if label else "")
        delta_eur = r["end_value_after_tax"] - hold_after
        delta_pct = (delta_eur / hold_after) * 100 if hold_after > 0 else 0
        pp = (r["cagr"] - hold["cagr"]) * 100
        line = f"  {name:<34}  {delta_eur:>+10,.1f} EUR  ({delta_pct:+.1f}%)  CAGR {pp:+.2f}pp"
        out.append(line); print(line)

    out.append("")
    print()

    # -------------- Conclusion --------------
    conclusion = ["CONCLUSION", "=" * 70]
    best = max(results[1:], key=lambda r: r["end_value_after_tax"])
    worst = min(results[1:], key=lambda r: r["end_value_after_tax"])
    prod = next((r for r in results[1:] if r.get("label") == "PRODUCTION"), None)

    conclusion.append(
        f"  Best DCA-out combo (after-tax): {best['strategy']} "
        f"[{best.get('label','')}] -> {best['end_value_after_tax']:,.0f} EUR "
        f"(HOLD={hold_after:,.0f} EUR, delta={(best['end_value_after_tax']-hold_after):+,.0f} EUR)"
    )
    conclusion.append(
        f"  Worst DCA-out combo: {worst['strategy']} -> "
        f"{worst['end_value_after_tax']:,.0f} EUR "
        f"(delta={(worst['end_value_after_tax']-hold_after):+,.0f} EUR)"
    )
    if prod is not None:
        prod_delta = prod["end_value_after_tax"] - hold_after
        prod_pp = (prod["cagr"] - hold["cagr"]) * 100
        conclusion.append("")
        conclusion.append(
            f"  PRODUCTION combo (base=$3k, step=$1k, pct=3%):"
        )
        conclusion.append(
            f"    End value after tax: {prod['end_value_after_tax']:,.0f} EUR "
            f"(delta vs HOLD: {prod_delta:+,.0f} EUR, {prod_pp:+.2f}pp CAGR)"
        )
        conclusion.append(
            f"    N sales: {prod['n_sales']}  |  Total sold: {prod['total_sold_eur']:,.0f} EUR  |  Taxes: {prod['tax']:,.0f} EUR"
        )
        if prod_delta > 0:
            conclusion.append("    VERDICT: PRODUCTION parameters beat hold (after tax). KEEP.")
        elif prod_delta > -hold_after * 0.02:
            conclusion.append("    VERDICT: PRODUCTION parameters roughly match hold. MARGINAL.")
        else:
            conclusion.append("    VERDICT: PRODUCTION parameters UNDERPERFORM hold. REVIEW.")

    for line in conclusion:
        print(line)
    out.extend(conclusion)

    RESULTS_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
