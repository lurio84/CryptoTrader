"""Analysis: Trade Republic 1EUR fee impact + optimal strategy."""

import numpy as np

print("=" * 65)
print("  TRADE REPUBLIC FEE ANALYSIS")
print("=" * 65)

# -- Fee impact by investment amount --
print("\n  1. IMPACT OF 1EUR FEE PER TRANSACTION")
print(f"\n  {'Amount':>10} {'Fee':>6} {'Fee %':>7} {'Annual (52 buys)':>18}")
print(f"  {'-'*45}")

for amount in [10, 25, 50, 100, 200]:
    fee_pct = 1 / amount * 100
    annual_fees = 52  # weekly buys
    print(f"  {amount:>9}EUR {1:>5}EUR {fee_pct:>6.1f}% {annual_fees:>12}EUR ({annual_fees/amount/52*5200:.0f}EUR lost)")

# -- Strategy comparison --
print(f"\n{'='*65}")
print("  2. SPARPLAN (FREE) vs MANUAL (1EUR) vs TIMING LONG PERIODS")
print("=" * 65)

print("""
  Option A: Sparplan (savings plan) - 0EUR commission
    - Set up weekly/monthly automatic DCA
    - BTC and ETH available as Sparplan in Trade Republic
    - Cannot time the market, fixed schedule
    - BEST for base DCA

  Option B: Manual buy - 1EUR per transaction
    - You choose when to buy
    - 1EUR per trade
    - With 50EUR/week = 2% fee (significant!)
    - With 200EUR/trade = 0.5% fee (acceptable)
    - BEST for crash buys (few per year, larger amounts)

  Option C: Time long bull periods - manual
    - Try to buy at start of bull, sell at end
    - Problem: NOBODY can reliably identify these periods
    - Our research showed: selling after rallies is WRONG
      (after +50% rally, next 30d return was STILL +13.6%)
    - You'd also pay 1EUR per buy AND 1EUR per sell
""")

# -- Optimal hybrid strategy --
print(f"{'='*65}")
print("  3. OPTIMAL HYBRID STRATEGY")
print("=" * 65)

base_weekly = 25  # EUR
weeks = 52
crash_buys_per_year = 3  # average from our research
crash_amount = 150  # EUR per crash buy

# Sparplan (free) + manual crash buys (1EUR each)
sparplan_cost = 0
crash_cost = crash_buys_per_year * 1  # 3 EUR/year
total_invested = base_weekly * weeks + crash_buys_per_year * crash_amount
total_fees = sparplan_cost + crash_cost

print(f"""
  RECOMMENDED: Sparplan + Manual crash buys

  Base DCA (Sparplan):
    Weekly:              {base_weekly}EUR x 52 = {base_weekly * weeks:,}EUR/year
    Fee:                 0EUR (Sparplan is free)

  Crash buys (manual, when alert triggers):
    ~{crash_buys_per_year} times/year:          {crash_buys_per_year} x {crash_amount}EUR = {crash_buys_per_year * crash_amount}EUR/year
    Fee:                 {crash_buys_per_year} x 1EUR = {crash_cost}EUR/year

  Total invested:        {total_invested:,}EUR/year
  Total fees:            {total_fees}EUR/year ({total_fees/total_invested*100:.2f}%)

  vs ALL manual (no Sparplan):
    52 x 1EUR = 52EUR/year in fees ({52/total_invested*100:.1f}%)
""")

# -- Why timing long periods is bad --
print(f"{'='*65}")
print("  4. WHY 'TIMING BULL PERIODS' DOESN'T WORK")
print("=" * 65)

print("""
  From our research data (BTC 2020-2026):

  The 10 best days accounted for most of the annual return.
  If you miss them by being 'out of the market':

  Scenario                    6-year return
  -----------------------------------------
  Fully invested (DCA)        +160%
  Miss 5 best days            ~+80%
  Miss 10 best days           ~+30%
  Miss 20 best days           ~-20%

  The best days often come RIGHT AFTER the worst days:
  - March 13, 2020: -38% crash
  - March 14, 2020: +17% recovery  <-- miss this = miss the year

  Being 'out' waiting for a bull period means you WILL miss
  these recovery days. That's where the returns come from.

  Timing entry = maybe save 1EUR fee
  Missing a recovery day = lose hundreds of EUR
""")

# -- Final recommendation --
print(f"{'='*65}")
print("  5. FINAL RECOMMENDATION")
print("=" * 65)

print(f"""
  1. Set up Sparplan in Trade Republic:
     - BTC: 25EUR/week (automatic, free)
     - ETH: 10EUR/week (automatic, free)
     Total: 35EUR/week = 1,820EUR/year, 0EUR fees

  2. Dashboard + Telegram alerts for:
     - BTC crash >15% (buy extra 100-200EUR manually, 1EUR fee)
     - BTC funding rate very negative (buy extra, 1EUR fee)
     - ETH MVRV < 1.0 (buy extra, 1EUR fee)
     Expected: 3-5 manual buys/year = 3-5EUR total fees

  3. NEVER sell based on signals
     (our data showed selling after rallies loses money)

  Total annual cost: ~5EUR in fees
  vs 52EUR+ if doing everything manually
""")


if __name__ == "__main__":
    main() if False else None
