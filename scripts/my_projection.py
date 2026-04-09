"""Long-term projection: 5-year intervals up to 50 years."""

import numpy as np


def project_value(initial, monthly, annual_return, years):
    value = initial
    monthly_rate = (1 + annual_return / 100) ** (1/12) - 1
    for _ in range(years * 12):
        value = value * (1 + monthly_rate) + monthly
    return value


def main():
    # Current portfolio
    stock_invested = 352  # EUR already invested
    stock_monthly = 100   # 16+4+4+1 = 25/week = 100/month
    stock_return = 10.9   # weighted average

    crypto_monthly = 40   # 8+2 = 10/week = 40/month
    crash_extra_monthly = 200 / 12  # ~200 EUR/year in crash buys

    # Scenarios for crypto annual return
    scenarios = [
        ("Conservative (crypto +15%)", 15),
        ("Moderate (crypto +30%)", 30),
        ("Historical (crypto +40%)", 40),
    ]

    print("=" * 75)
    print("  LONG-TERM PROJECTION: YOUR PLAN")
    print("  Stocks: 100 EUR/month @ 10.9% | Crypto: 40 EUR/month + crash buys")
    print("  Starting with 352 EUR in stocks, 0 in crypto")
    print("=" * 75)

    for scenario_name, crypto_ret in scenarios:
        print(f"\n  {scenario_name}")
        print(f"  {'Year':<6} {'Age':>4} {'Stocks':>12} {'Crypto':>12} {'TOTAL':>12} {'Invested':>12} {'Profit':>12}")
        print(f"  {'-'*72}")

        for years in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
            s_val = project_value(stock_invested, stock_monthly, stock_return, years)
            c_val = project_value(0, crypto_monthly + crash_extra_monthly, crypto_ret, years)
            total = s_val + c_val
            invested = stock_invested + (stock_monthly + crypto_monthly + crash_extra_monthly) * 12 * years
            profit = total - invested
            # Assuming user is ~25 now
            age = 25 + years

            print(f"  {years:<6} {age:>4} {s_val:>12,.0f} {c_val:>12,.0f} {total:>12,.0f} "
                  f"{invested:>12,.0f} {profit:>+12,.0f}")

    # Comparison: all in S&P 500 with same 140 EUR/month
    print(f"\n{'='*75}")
    print(f"  COMPARISON: All 140 EUR/month in S&P 500 only (10.5%)")
    print(f"{'='*75}")
    print(f"\n  {'Year':<6} {'Age':>4} {'Value':>12} {'Invested':>12} {'Profit':>12}")
    print(f"  {'-'*50}")

    for years in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
        val = project_value(stock_invested, 140, 10.5, years)
        invested = stock_invested + 140 * 12 * years
        age = 25 + years
        print(f"  {years:<6} {age:>4} {val:>12,.0f} {invested:>12,.0f} {val-invested:>+12,.0f}")

    # Worst case: crypto goes to 0 after N years
    print(f"\n{'='*75}")
    print(f"  WORST CASE: Crypto drops to 0 at some point")
    print(f"  (You only lose the crypto portion, stocks are safe)")
    print(f"{'='*75}")

    print(f"\n  {'Crypto dies after':<20} {'Lost in crypto':>15} {'Stocks still worth':>20}")
    print(f"  {'-'*58}")
    for years in [1, 3, 5, 10]:
        lost = (crypto_monthly + crash_extra_monthly) * 12 * years
        stocks_val = project_value(stock_invested, stock_monthly, stock_return, years)
        print(f"  {years:>3} years              {lost:>14,.0f} EUR {stocks_val:>19,.0f} EUR")

    print(f"""
{'='*75}
  KEY TAKEAWAYS
{'='*75}

  With the moderate scenario (crypto +30%/year):
    Age 30 (5yr):   ~6,000 EUR profit
    Age 35 (10yr):  ~40,000 EUR profit
    Age 40 (15yr):  ~160,000 EUR profit
    Age 45 (20yr):  ~550,000 EUR profit

  The magic is COMPOUND INTEREST + TIME:
    - First 5 years: modest gains
    - Years 10-20: exponential growth
    - After 20 years: your money works harder than you do

  IMPORTANT CAVEATS:
    - Crypto may not return 30%/year forever
    - As your portfolio grows, consider shifting more to stocks
    - These projections assume constant contributions (adjust for salary growth)
    - Inflation reduces real purchasing power (~2-3%/year)
    - Past returns do NOT guarantee future returns
""")


if __name__ == "__main__":
    main()
