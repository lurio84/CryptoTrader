"""Portfolio analysis: current investments + crypto plan vs S&P 500 only."""

import numpy as np

# ── Current portfolio ──
portfolio = {
    "S&P 500 USD (Acc)": {"invested": 253, "monthly": 16 * 4, "type": "ETF", "expected_annual": 10.5},
    "MSCI Global Semiconductors": {"invested": 46, "monthly": 4 * 4, "type": "ETF", "expected_annual": 15.0},
    "Realty Income": {"invested": 43, "monthly": 4 * 4, "type": "Stock", "expected_annual": 8.0},
    "Uranium USD (Acc)": {"invested": 10, "monthly": 1 * 4, "type": "ETF", "expected_annual": 12.0},
}

# Weekly contributions (from user)
weekly_contributions = {
    "S&P 500 USD (Acc)": 16,
    "MSCI Global Semiconductors": 4,
    "Realty Income": 4,
    "Uranium USD (Acc)": 1,
}
# Total current weekly: 25 EUR

# Proposed crypto addition
crypto_plan = {
    "BTC Sparplan": {"weekly": 25, "expected_annual_low": 25, "expected_annual_mid": 40, "expected_annual_high": 60},
    "ETH Sparplan": {"weekly": 10, "expected_annual_low": 15, "expected_annual_mid": 35, "expected_annual_high": 55},
}


def project_value(initial, monthly, annual_return, years):
    """Project future value with monthly contributions."""
    value = initial
    monthly_rate = (1 + annual_return / 100) ** (1/12) - 1
    for _ in range(years * 12):
        value = value * (1 + monthly_rate) + monthly
    return value


def main():
    print("=" * 70)
    print("  YOUR CURRENT PORTFOLIO ANALYSIS")
    print("=" * 70)

    total_invested = sum(p["invested"] for p in portfolio.values())
    total_weekly = sum(weekly_contributions.values())
    total_monthly = total_weekly * 4

    print(f"\n  {'Asset':<30} {'Invested':>9} {'Weekly':>8} {'Monthly':>8} {'Exp.Ret':>8}")
    print(f"  {'-'*65}")

    for name, data in portfolio.items():
        w = weekly_contributions[name]
        m = w * 4
        print(f"  {name:<30} {data['invested']:>8}EUR {w:>7}EUR {m:>7}EUR {data['expected_annual']:>+7.1f}%")

    print(f"  {'-'*65}")
    print(f"  {'TOTAL':<30} {total_invested:>8}EUR {total_weekly:>7}EUR {total_monthly:>7}EUR")

    # ── Projection: current portfolio only ──
    print(f"\n{'='*70}")
    print(f"  PROJECTION: CURRENT PORTFOLIO (no crypto)")
    print(f"{'='*70}")

    # Weighted average return of current portfolio
    total_flow = sum(weekly_contributions[n] for n in portfolio)
    weighted_ret = sum(
        portfolio[n]["expected_annual"] * weekly_contributions[n] / total_flow
        for n in portfolio
    )

    print(f"\n  Weighted avg expected return: {weighted_ret:.1f}%")
    print(f"  Monthly contribution: {total_monthly}EUR")

    print(f"\n  {'Year':<6} {'Value':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*40}")

    for years in [1, 2, 3, 5, 10]:
        value = project_value(total_invested, total_monthly, weighted_ret, years)
        invested = total_invested + total_monthly * 12 * years
        profit = value - invested
        print(f"  {years:<6} {value:>10,.0f}EUR {invested:>10,.0f}EUR {profit:>+10,.0f}EUR")

    # ── Projection: 100% S&P 500 ──
    print(f"\n{'='*70}")
    print(f"  PROJECTION: IF YOU PUT EVERYTHING IN S&P 500 (10.5% avg)")
    print(f"{'='*70}")

    print(f"\n  {'Year':<6} {'Value':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*40}")

    for years in [1, 2, 3, 5, 10]:
        value = project_value(total_invested, total_monthly, 10.5, years)
        invested = total_invested + total_monthly * 12 * years
        profit = value - invested
        print(f"  {years:<6} {value:>10,.0f}EUR {invested:>10,.0f}EUR {profit:>+10,.0f}EUR")

    # ── Projection: current + crypto plan ──
    print(f"\n{'='*70}")
    print(f"  PROJECTION: CURRENT PORTFOLIO + CRYPTO PLAN")
    print(f"  (BTC 25EUR/week + ETH 10EUR/week + crash buys)")
    print(f"{'='*70}")

    crypto_weekly = 35
    crypto_monthly = crypto_weekly * 4
    crash_extra_yearly = 5300 / 6  # from our 6-year simulation average

    # Three scenarios for crypto
    scenarios = [
        ("Conservative (BTC+15%, ETH+10%)", 13),
        ("Moderate (BTC+30%, ETH+25%)", 28),
        ("Historical (BTC+40%, ETH+35%)", 38),
    ]

    for scenario_name, crypto_ret in scenarios:
        print(f"\n  Scenario: {scenario_name}")
        print(f"  Stocks: {total_monthly}EUR/mo @ {weighted_ret:.1f}% | Crypto: {crypto_monthly}EUR/mo @ {crypto_ret}%")
        print(f"  + ~{crash_extra_yearly:.0f}EUR/year crash buys")

        print(f"\n  {'Year':<6} {'Stocks':>10} {'Crypto':>10} {'Total':>10} {'Invested':>10} {'Profit':>10}")
        print(f"  {'-'*55}")

        for years in [1, 2, 3, 5, 10]:
            stock_val = project_value(total_invested, total_monthly, weighted_ret, years)
            crypto_val = project_value(0, crypto_monthly + crash_extra_yearly/12, crypto_ret, years)
            total_val = stock_val + crypto_val
            invested = total_invested + (total_monthly + crypto_monthly) * 12 * years + crash_extra_yearly * years
            profit = total_val - invested
            print(f"  {years:<6} {stock_val:>10,.0f} {crypto_val:>10,.0f} {total_val:>10,.0f} "
                  f"{invested:>10,.0f} {profit:>+10,.0f}")

    # ── The key comparison ──
    print(f"\n{'='*70}")
    print(f"  KEY COMPARISON: All S&P 500 vs Diversified (Stocks + Crypto)")
    print(f"  Same total monthly contribution: {total_monthly + crypto_monthly}EUR/month")
    print(f"{'='*70}")

    total_contribution = total_monthly + crypto_monthly

    print(f"\n  {'Strategy':<35} {'5yr Value':>10} {'5yr Profit':>11} {'10yr Value':>11} {'10yr Profit':>12}")
    print(f"  {'-'*82}")

    # All in S&P 500
    for years in [5, 10]:
        sp_val = project_value(total_invested, total_contribution, 10.5, years)
        sp_inv = total_invested + total_contribution * 12 * years
        sp_profit = sp_val - sp_inv
        if years == 5:
            sp5_v, sp5_p = sp_val, sp_profit
        else:
            sp10_v, sp10_p = sp_val, sp_profit

    print(f"  {'100% S&P 500':<35} {sp5_v:>10,.0f} {sp5_p:>+11,.0f} {sp10_v:>11,.0f} {sp10_p:>+12,.0f}")

    # Diversified moderate
    for scenario_name, crypto_ret in [("Stocks + Crypto (moderate)", 28)]:
        for years in [5, 10]:
            stock_val = project_value(total_invested, total_monthly, weighted_ret, years)
            crypto_val = project_value(0, crypto_monthly + crash_extra_yearly/12, crypto_ret, years)
            total_val = stock_val + crypto_val
            invested = total_invested + total_contribution * 12 * years + crash_extra_yearly * years
            profit = total_val - invested
            if years == 5:
                d5_v, d5_p = total_val, profit
            else:
                d10_v, d10_p = total_val, profit

        print(f"  {scenario_name:<35} {d5_v:>10,.0f} {d5_p:>+11,.0f} {d10_v:>11,.0f} {d10_p:>+12,.0f}")

    print(f"""
  IMPORTANT CAVEATS:
  - Crypto projections based on 2020-2026 data (may not repeat)
  - S&P 500 10.5% is long-term historical average
  - Crypto has 5x more volatility than S&P 500
  - Past returns do NOT guarantee future returns
  - Your current portfolio is well diversified (good!)
""")


if __name__ == "__main__":
    main()
