"""Personal investment plan: adjusted to real budget."""

import numpy as np


def project_value(initial, monthly, annual_return, years):
    value = initial
    monthly_rate = (1 + annual_return / 100) ** (1/12) - 1
    for _ in range(years * 12):
        value = value * (1 + monthly_rate) + monthly
    return value


def main():
    print("=" * 65)
    print("  YOUR ADJUSTED INVESTMENT PLAN")
    print("  Budget: 150 EUR/month (100 stocks + 50 crypto)")
    print("=" * 65)

    # Current portfolio
    stocks = {
        "S&P 500 USD (Acc)":        {"invested": 253, "weekly": 16, "ret": 10.5},
        "MSCI Global Semiconductors": {"invested": 46, "weekly": 4,  "ret": 15.0},
        "Realty Income":              {"invested": 43, "weekly": 4,  "ret": 8.0},
        "Uranium USD (Acc)":          {"invested": 10, "weekly": 1,  "ret": 12.0},
    }

    # Crypto plan: 50 EUR/month = 12.50 EUR/week
    crypto = {
        "BTC (Sparplan)":  {"invested": 0, "weekly": 10, "ret_low": 25, "ret_mid": 40, "ret_high": 60},
        "ETH (Sparplan)":  {"invested": 0, "weekly": 2.50, "ret_low": 15, "ret_mid": 35, "ret_high": 55},
    }

    # Crash buy reserve: from the 50 EUR/month, save some months to have
    # cash ready for crash buys. Estimated 2-3 crash buys of ~100 EUR/year
    crash_reserve_yearly = 200  # EUR saved for crash opportunities

    print(f"\n  STOCKS (Sparplan, 0 EUR fees):")
    print(f"  {'Asset':<30} {'Invested':>9} {'Weekly':>8} {'Monthly':>8}")
    print(f"  {'-'*58}")
    total_stock_invested = 0
    total_stock_monthly = 0
    for name, d in stocks.items():
        m = d["weekly"] * 4
        print(f"  {name:<30} {d['invested']:>8} EUR {d['weekly']:>7} EUR {m:>7} EUR")
        total_stock_invested += d["invested"]
        total_stock_monthly += m
    print(f"  {'-'*58}")
    print(f"  {'SUBTOTAL STOCKS':<30} {total_stock_invested:>8} EUR {'':>8} {total_stock_monthly:>7} EUR")

    print(f"\n  CRYPTO (Sparplan, 0 EUR fees):")
    print(f"  {'Asset':<30} {'Invested':>9} {'Weekly':>8} {'Monthly':>8}")
    print(f"  {'-'*58}")
    total_crypto_monthly = 0
    for name, d in crypto.items():
        m = d["weekly"] * 4
        print(f"  {name:<30} {d['invested']:>8} EUR {d['weekly']:>6.1f} EUR {m:>7} EUR")
        total_crypto_monthly += m
    print(f"  {'-'*58}")
    print(f"  {'SUBTOTAL CRYPTO':<30} {'0':>8} EUR {'':>8} {total_crypto_monthly:>7} EUR")

    total_monthly = total_stock_monthly + total_crypto_monthly
    print(f"\n  {'TOTAL MONTHLY':<30} {'':>9} {'':>8} {total_monthly:>7} EUR")
    print(f"  Crash buy reserve: ~{crash_reserve_yearly} EUR/year (2-3 manual buys when alerts trigger)")

    # ── Projections ──
    print(f"\n{'='*65}")
    print(f"  PROJECTIONS")
    print(f"{'='*65}")

    stock_weighted_ret = sum(
        stocks[n]["ret"] * stocks[n]["weekly"] for n in stocks
    ) / sum(stocks[n]["weekly"] for n in stocks)

    # Scenario: stocks only (current plan)
    print(f"\n  A) CURRENT PLAN (stocks only, 100 EUR/month):")
    print(f"     Weighted return: {stock_weighted_ret:.1f}%")
    print(f"\n  {'Year':<6} {'Value':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*40}")
    for y in [1, 3, 5, 10]:
        val = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, y)
        inv = total_stock_invested + total_stock_monthly * 12 * y
        print(f"  {y:<6} {val:>10,.0f} EUR {inv:>10,.0f} EUR {val-inv:>+10,.0f} EUR")

    # Scenario: stocks + crypto moderate
    crypto_ret_mid = 38  # weighted avg of BTC 40% + ETH 35%
    print(f"\n  B) NEW PLAN (stocks 100 + crypto 50 EUR/month, moderate scenario):")
    print(f"     Stocks: {stock_weighted_ret:.1f}% | Crypto: ~{crypto_ret_mid}%")
    print(f"\n  {'Year':<6} {'Stocks':>10} {'Crypto':>10} {'Total':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*55}")
    for y in [1, 3, 5, 10]:
        s_val = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, y)
        c_val = project_value(0, total_crypto_monthly, crypto_ret_mid, y)
        total = s_val + c_val
        inv = total_stock_invested + total_monthly * 12 * y
        print(f"  {y:<6} {s_val:>10,.0f} {c_val:>10,.0f} {total:>10,.0f} {inv:>10,.0f} {total-inv:>+10,.0f}")

    # Scenario: stocks + crypto conservative
    crypto_ret_low = 20
    print(f"\n  C) NEW PLAN (conservative crypto scenario, ~{crypto_ret_low}%):")
    print(f"\n  {'Year':<6} {'Stocks':>10} {'Crypto':>10} {'Total':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*55}")
    for y in [1, 3, 5, 10]:
        s_val = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, y)
        c_val = project_value(0, total_crypto_monthly, crypto_ret_low, y)
        total = s_val + c_val
        inv = total_stock_invested + total_monthly * 12 * y
        print(f"  {y:<6} {s_val:>10,.0f} {c_val:>10,.0f} {total:>10,.0f} {inv:>10,.0f} {total-inv:>+10,.0f}")

    # Scenario: worst case (crypto bear)
    crypto_ret_bad = -15
    print(f"\n  D) WORST CASE (crypto loses {crypto_ret_bad}% annually):")
    print(f"\n  {'Year':<6} {'Stocks':>10} {'Crypto':>10} {'Total':>10} {'Invested':>10} {'Profit':>10}")
    print(f"  {'-'*55}")
    for y in [1, 3, 5]:
        s_val = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, y)
        c_val = project_value(0, total_crypto_monthly, crypto_ret_bad, y)
        total = s_val + c_val
        inv = total_stock_invested + total_monthly * 12 * y
        print(f"  {y:<6} {s_val:>10,.0f} {c_val:>10,.0f} {total:>10,.0f} {inv:>10,.0f} {total-inv:>+10,.0f}")

    # ── Comparison: all in S&P 500 with same 150 EUR/month ──
    print(f"\n{'='*65}")
    print(f"  COMPARISON: 150 EUR/month all in S&P 500 vs diversified")
    print(f"{'='*65}")

    print(f"\n  {'Strategy':<35} {'5yr':>10} {'10yr':>10}")
    print(f"  {'-'*58}")

    sp_5 = project_value(total_stock_invested, 150, 10.5, 5)
    sp_10 = project_value(total_stock_invested, 150, 10.5, 10)
    print(f"  {'All S&P 500 (150/mo)' :<35} {sp_5:>10,.0f} {sp_10:>10,.0f}")

    div_mod_5 = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, 5) + \
                project_value(0, total_crypto_monthly, crypto_ret_mid, 5)
    div_mod_10 = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, 10) + \
                 project_value(0, total_crypto_monthly, crypto_ret_mid, 10)
    print(f"  {'Stocks + Crypto moderate':<35} {div_mod_5:>10,.0f} {div_mod_10:>10,.0f}")

    div_con_5 = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, 5) + \
                project_value(0, total_crypto_monthly, crypto_ret_low, 5)
    div_con_10 = project_value(total_stock_invested, total_stock_monthly, stock_weighted_ret, 10) + \
                 project_value(0, total_crypto_monthly, crypto_ret_low, 10)
    print(f"  {'Stocks + Crypto conservative':<35} {div_con_5:>10,.0f} {div_con_10:>10,.0f}")

    inv_5 = total_stock_invested + 150 * 12 * 5
    inv_10 = total_stock_invested + 150 * 12 * 10
    print(f"  {'Total invested':<35} {inv_5:>10,.0f} {inv_10:>10,.0f}")

    print(f"""
  SUMMARY:
  - You keep your current 100 EUR/month in stocks (unchanged)
  - You add 50 EUR/month in crypto via Sparplan (0 fees)
    - BTC: 10 EUR/week (40 EUR/month)
    - ETH: 2.50 EUR/week (10 EUR/month)
  - When dashboard alerts, buy extra 100 EUR manually (1 EUR fee)
    - This comes from savings/extra cash, ~2-3 times per year
  - Maximum downside: if crypto goes to 0, you lose 50 EUR/month
    but your stocks are unaffected
""")


if __name__ == "__main__":
    main()
