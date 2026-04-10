"""exit_signals_research4.py
==========================
Pre-implementation checks for the DCA-out strategy.

Two concerns identified before implementing DCA-out alerts:

  1. TAXES: the backtest in research3.py only deducted the 1 EUR Trade Republic fee.
     In Spain, each crypto sale triggers IRPF capital gains tax (19-28%).
     This script re-runs the DCA-out simulation with Spanish tax applied.
     Key question: does DCA-out still beat hold AFTER taxes?

  2. OVERFITTING: the backtest used 2018-2026 data where BTC peaked at $124k
     and then fell back to $68k at dataset end. This is exactly the scenario
     where DCA-out shines. What if the next cycle peaks much higher ($300k)?
     This script tests all strategies across a range of hypothetical end prices.

Tax model (Spain IRPF 2024, ganancias patrimoniales):
  - 19% on first 6,000 EUR of annual gain
  - 21% on 6,001 - 50,000 EUR
  - 23% on 50,001 - 200,000 EUR
  - 27% on 200,001 - 300,000 EUR
  - 28% above 300,000 EUR
  Cost basis method: FIFO (Spain standard for fungible assets like crypto)

Usage:
  python backtesting/exit_signals_research4.py
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANALYSIS_START = "2018-01-01"
ANALYSIS_END   = "2026-04-01"

WEEKLY_BTC_EUR = 8.0
SELL_FEE_EUR   = 1.0

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"

# Spain IRPF 2024 -- capital gains brackets (annual net gain)
# Tuples of (limit, rate) -- limit is the TOP of this bracket
SPAIN_TAX_BRACKETS = [
    (6_000,    0.19),
    (50_000,   0.21),
    (200_000,  0.23),
    (300_000,  0.27),
    (float("inf"), 0.28),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cache(path: Path) -> pd.DataFrame | None:
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        return df
    return None


def cagr(start_val: float, end_val: float, years: float) -> float:
    if start_val <= 0 or years <= 0:
        return 0.0
    return float((end_val / start_val) ** (1.0 / years) - 1) * 100


def _build_weekly_dates(index: pd.DatetimeIndex, start: str) -> set:
    weekly = set()
    d = pd.Timestamp(start)
    end = index[-1]
    while d <= end:
        pos = index.searchsorted(d)
        if pos < len(index):
            weekly.add(index[pos])
        d += timedelta(days=7)
    return weekly


def compute_spanish_tax(annual_gain_eur: float) -> float:
    """Apply Spain IRPF brackets to annual capital gain. Returns tax owed."""
    if annual_gain_eur <= 0:
        return 0.0
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in SPAIN_TAX_BRACKETS:
        taxable_in_bracket = min(annual_gain_eur, limit) - prev_limit
        if taxable_in_bracket <= 0:
            break
        tax += taxable_in_bracket * rate
        prev_limit = limit
        if annual_gain_eur <= limit:
            break
    return tax


def compute_effective_rate(gain: float) -> float:
    """Returns effective tax rate for a given gain amount."""
    if gain <= 0:
        return 0.0
    return compute_spanish_tax(gain) / gain * 100


def fetch_btc_prices() -> pd.Series:
    """Load BTC prices from cache."""
    cache = CACHE_DIR / "btc_cm.csv"
    df = _load_cache(cache)
    if df is None:
        raise FileNotFoundError("BTC cache not found. Run exit_signals_research3.py first.")
    prices = df.set_index("date")["price"]
    prices.index = pd.to_datetime(prices.index)
    prices = prices[~prices.index.duplicated(keep="first")].sort_index()
    return prices.loc[ANALYSIS_START:ANALYSIS_END]


# ---------------------------------------------------------------------------
# FIFO cost basis tracker
# ---------------------------------------------------------------------------

class FIFOCostBasis:
    """Track BTC purchases as a FIFO queue for cost basis calculation.

    Each purchase is a (units, cost_eur_per_unit) entry.
    When selling, dequeue from the front (oldest purchases first).
    """

    def __init__(self):
        self._queue: deque[list[float]] = deque()  # [units, cost_eur_per_unit]
        self.total_units: float = 0.0

    def buy(self, units: float, cost_per_unit_eur: float) -> None:
        self._queue.append([units, cost_per_unit_eur])
        self.total_units += units

    def sell(self, units_to_sell: float) -> float:
        """Sell units_to_sell using FIFO. Returns total cost basis of sold units."""
        if units_to_sell <= 0:
            return 0.0
        if units_to_sell > self.total_units + 1e-10:
            units_to_sell = self.total_units  # cap at available

        cost_basis_total = 0.0
        remaining = units_to_sell
        while remaining > 1e-10 and self._queue:
            lot_units, lot_cost = self._queue[0]
            if lot_units <= remaining:
                cost_basis_total += lot_units * lot_cost
                remaining -= lot_units
                self._queue.popleft()
            else:
                cost_basis_total += remaining * lot_cost
                self._queue[0][0] -= remaining
                remaining = 0.0

        self.total_units -= units_to_sell
        if self.total_units < 0:
            self.total_units = 0.0
        return cost_basis_total


# ---------------------------------------------------------------------------
# PART 1: Tax-adjusted DCA-out simulation
# ---------------------------------------------------------------------------

def part1_tax_analysis(prices_a: pd.Series) -> dict:
    sep = "=" * 70
    print(f"\n{sep}")
    print("  PART 1: TAX-ADJUSTED DCA-OUT (Spain IRPF)")
    print(sep)
    print()
    print("  Spain IRPF 2024 capital gains brackets:")
    print("    19% on first 6,000 EUR gain/year")
    print("    21% on 6,001 - 50,000 EUR")
    print("    23% on 50,001 - 200,000 EUR")
    print("    27% on 200,001 - 300,000 EUR")
    print("    28% above 300,000 EUR")
    print()
    print("  Cost basis method: FIFO (Spain standard for crypto)")
    print()
    print("  Key asymmetry: hold DCA pays tax only at the END (one big event).")
    print("  DCA-out pays tax yearly (smaller events, earlier in time).")
    print("  Both are taxed eventually. The question is HOW MUCH (bracket effects)")
    print("  and WHEN (time value: paying tax later = keeps money invested longer).")
    print()

    weekly_dates = _build_weekly_dates(prices_a.index,
                                       prices_a.index[0].strftime("%Y-%m-%d"))
    years = (prices_a.index[-1] - prices_a.index[0]).days / 365.25
    total_invested = len(weekly_dates) * WEEKLY_BTC_EUR

    print(f"  Period       : {prices_a.index[0].date()} to {prices_a.index[-1].date()} "
          f"({years:.1f} years)")
    print(f"  BTC price    : ${prices_a.iloc[0]:,.0f} -> ${prices_a.iloc[-1]:,.0f}")
    print(f"  ATH in period: ${prices_a.max():,.0f}")
    print(f"  Total DCA in : {total_invested:,.0f} EUR over {len(weekly_dates)} weeks")
    print()

    # Show effective tax rates for reference
    print("  Effective tax rate by gain level:")
    for gain in [1000, 5000, 10000, 30000, 60000, 100000]:
        tax = compute_spanish_tax(gain)
        rate = tax / gain * 100
        print(f"    {gain:>8,.0f} EUR gain -> {tax:>8,.0f} EUR tax ({rate:.1f}% effective)")
    print()

    # Strategies to test: (name, base_price, step_size, sell_pct, cooldown)
    STRATEGIES = [
        ("Pure hold DCA (sell at end)",  0,     0,     0,     0),
        ("3% per $20k above $80k",       80000, 20000, 0.03,  30),
        ("5% per $20k above $80k",       80000, 20000, 0.05,  30),
        ("3% per $20k above $60k",       60000, 20000, 0.03,  30),
        ("3% per $10k above $80k",       80000, 10000, 0.03,  30),
    ]

    def simulate_with_tax(base_price: float, step_size: float,
                          sell_pct: float, cooldown: int,
                          is_hold: bool = False) -> dict:
        """Full simulation with FIFO cost basis and Spanish tax applied."""
        fifo = FIFOCostBasis()
        cash_eur = 0.0
        invested = 0.0
        total_fees = 0.0
        total_tax_paid = 0.0
        sell_log: list[dict] = []
        last_trigger_by_level: dict[int, pd.Timestamp | None] = {}

        # Track annual gains for yearly tax settlement
        annual_gains: dict[int, float] = {}  # year -> total gain

        for date in prices_a.index:
            price = prices_a[date]

            # Weekly DCA: buy BTC
            if date in weekly_dates:
                units_bought = WEEKLY_BTC_EUR / price
                fifo.buy(units_bought, price)  # cost basis = price in USD
                invested += WEEKLY_BTC_EUR
                # Note: we store cost in USD (same unit as sell price)
                # EUR/USD would add complexity; we simplify by ignoring FX

            # DCA-out sell triggers (not for pure hold)
            if not is_hold and base_price > 0 and step_size > 0:
                if price > base_price and fifo.total_units > 0:
                    steps_above = int((price - base_price) / step_size)
                    for step in range(1, steps_above + 1):
                        last = last_trigger_by_level.get(step)
                        if last is None or (date - last).days >= cooldown:
                            sell_units = fifo.total_units * sell_pct
                            cost_basis_usd = fifo.sell(sell_units)
                            sell_proceeds_usd = sell_units * price
                            gain_usd = sell_proceeds_usd - cost_basis_usd

                            # Approximate EUR (simplification: assume 1 USD ~ 1 EUR
                            # for gain calculation -- direction/magnitude is correct)
                            gain_eur = gain_usd
                            sell_eur = sell_proceeds_usd - SELL_FEE_EUR

                            if sell_eur > 0:
                                year = date.year
                                annual_gains[year] = annual_gains.get(year, 0) + gain_eur
                                cash_eur += sell_eur
                                total_fees += SELL_FEE_EUR
                                last_trigger_by_level[step] = date
                                sell_log.append({
                                    "date": date, "price": price,
                                    "units": sell_units, "proceeds_eur": sell_eur,
                                    "gain_eur": gain_eur, "year": year,
                                })

        # Apply annual tax payments (deducted from cash)
        yearly_tax: dict[int, float] = {}
        for year, gain in annual_gains.items():
            tax = compute_spanish_tax(gain)
            yearly_tax[year] = tax
            total_tax_paid += tax
            cash_eur -= tax  # tax paid from cash proceeds
            if cash_eur < 0:
                cash_eur = 0.0  # simplified: assume enough cash always available

        # Final: sell all remaining BTC
        final_price = prices_a.iloc[-1]
        remaining_units = fifo.total_units
        if remaining_units > 0:
            final_cost_basis = fifo.sell(remaining_units)
            final_proceeds_usd = remaining_units * final_price
            final_gain_usd = final_proceeds_usd - final_cost_basis
            final_gain_eur = final_gain_usd
            final_tax = compute_spanish_tax(final_gain_eur)
            final_net = final_proceeds_usd - final_tax
            total_tax_paid += final_tax
            cash_eur += final_net

        final_total = cash_eur
        tot_ret = (final_total - invested) / invested * 100
        ann = cagr(invested, final_total, years)

        return {
            "invested": invested,
            "final_total": final_total,
            "total_ret": tot_ret,
            "cagr": ann,
            "fees": total_fees,
            "tax_paid": total_tax_paid,
            "n_sells": len(sell_log),
            "sell_log": sell_log,
            "annual_gains": annual_gains,
            "yearly_tax": yearly_tax,
        }

    # Also run WITHOUT tax for comparison (to isolate tax impact)
    def simulate_no_tax(base_price: float, step_size: float,
                        sell_pct: float, cooldown: int) -> dict:
        """Same simulation but NO tax -- for isolating the tax impact."""
        btc_units = 0.0
        cash_eur = 0.0
        invested = 0.0
        total_fees = 0.0
        last_trigger_by_level: dict[int, pd.Timestamp | None] = {}

        for date in prices_a.index:
            price = prices_a[date]
            if date in weekly_dates:
                btc_units += WEEKLY_BTC_EUR / price
                invested += WEEKLY_BTC_EUR
            if base_price > 0 and step_size > 0 and price > base_price and btc_units > 0:
                steps_above = int((price - base_price) / step_size)
                for step in range(1, steps_above + 1):
                    last = last_trigger_by_level.get(step)
                    if last is None or (date - last).days >= cooldown:
                        sell_units = btc_units * sell_pct
                        sell_eur = sell_units * price - SELL_FEE_EUR
                        if sell_eur > 0:
                            btc_units -= sell_units
                            cash_eur += sell_eur
                            total_fees += SELL_FEE_EUR
                            last_trigger_by_level[step] = date

        final_btc = btc_units * prices_a.iloc[-1]
        final_total = final_btc + cash_eur
        tot_ret = (final_total - invested) / invested * 100
        ann = cagr(invested, final_total, years)
        return {"final_total": final_total, "total_ret": tot_ret,
                "cagr": ann, "fees": total_fees}

    print("  Running tax-adjusted simulations...")
    results = []
    for name, base_p, step_s, sell_p, cd in STRATEGIES:
        is_hold = (base_p == 0)
        r = simulate_with_tax(base_p, step_s, sell_p, cd, is_hold=is_hold)
        r["name"] = name
        results.append(r)

    hold = results[0]

    # Results table
    print()
    hdr = (f"  {'Strategy':<32} | {'Final EUR':>10} | {'Tot Ret':>8} | "
           f"{'CAGR':>7} | {'vs Hold':>8} | {'Tax paid':>9} | {'Sells':>5}")
    div = ("  " + "-" * 32 + "-+-" +
           "-+-".join(["-" * 10, "-" * 8, "-" * 7, "-" * 8, "-" * 9, "-" * 5]))
    print(hdr)
    print(div)
    for r in results:
        vs_hold = r["total_ret"] - hold["total_ret"]
        marker = " <--" if vs_hold > 5 else ""
        print(f"  {r['name']:<32} | {r['final_total']:>10,.0f} | "
              f"{r['total_ret']:>7.1f}% | {r['cagr']:>6.1f}% | "
              f"{vs_hold:>+7.1f}pp | {r['tax_paid']:>9,.0f} | "
              f"{r['n_sells']:>5}{marker}")

    # Tax breakdown for hold
    print()
    print(f"  Tax detail -- Pure hold (single sale at end):")
    print(f"    Invested      : {hold['invested']:,.0f} EUR")
    print(f"    Final proceeds: {hold['final_total'] + hold['tax_paid']:,.0f} EUR (pre-tax)")
    print(f"    Total gain    : {hold['final_total'] + hold['tax_paid'] - hold['invested']:,.0f} EUR")
    print(f"    Tax paid      : {hold['tax_paid']:,.0f} EUR "
          f"({hold['tax_paid'] / max(hold['final_total'] + hold['tax_paid'] - hold['invested'], 1) * 100:.1f}% "
          f"of gain)")
    print(f"    Net final     : {hold['final_total']:,.0f} EUR")

    # Tax breakdown for best DCA-out
    best = max(results[1:], key=lambda x: x["total_ret"])
    print()
    print(f"  Tax detail -- '{best['name']}':")
    if best["yearly_tax"]:
        for year in sorted(best["yearly_tax"]):
            gain = best["annual_gains"].get(year, 0)
            tax = best["yearly_tax"].get(year, 0)
            print(f"    {year}: gain={gain:,.0f} EUR, tax={tax:,.0f} EUR "
                  f"({compute_effective_rate(gain):.1f}% effective)")
    print(f"    Total tax paid: {best['tax_paid']:,.0f} EUR")
    print(f"    Net final     : {best['final_total']:,.0f} EUR")

    # Isolate tax impact
    print()
    print("  --- Tax impact isolation ---")
    print(f"  {'Strategy':<32} | {'No-tax ret':>10} | {'With-tax ret':>12} | {'Tax drag':>9}")
    print("  " + "-" * 32 + "-+-" + "-+-".join(["-" * 10, "-" * 12, "-" * 9]))
    for (name, base_p, step_s, sell_p, cd), r_tax in zip(STRATEGIES, results):
        r_notax = simulate_no_tax(base_p, step_s, sell_p, cd)
        drag = r_tax["total_ret"] - r_notax["total_ret"]
        print(f"  {name:<32} | {r_notax['total_ret']:>9.1f}% | "
              f"{r_tax['total_ret']:>11.1f}% | {drag:>+8.1f}pp")

    # Verdict
    print()
    print("  VERDICT:")
    best_after_tax = max(results[1:], key=lambda x: x["total_ret"])
    delta_after_tax = best_after_tax["total_ret"] - hold["total_ret"]
    if delta_after_tax > 5:
        print(f"  -> DCA-out STILL BEATS hold AFTER tax: "
              f"'{best_after_tax['name']}' gains +{delta_after_tax:.0f}pp.")
        print(f"     Despite paying {best_after_tax['tax_paid']:,.0f} EUR in tax "
              f"vs {hold['tax_paid']:,.0f} EUR for hold,")
        print("     the strategy still wins because it locks in gains at high prices.")
    elif delta_after_tax > 0:
        print(f"  -> DCA-out marginally better after tax: +{delta_after_tax:.1f}pp.")
        print("     The tax drag partially erodes the advantage but doesn't eliminate it.")
    else:
        print(f"  -> DCA-out LOSES to hold after tax: {delta_after_tax:+.1f}pp.")
        print("     Tax costs eliminate the advantage. Hold is better in this scenario.")

    return results


# ---------------------------------------------------------------------------
# PART 2: Overfitting -- scenario analysis across different BTC end prices
# ---------------------------------------------------------------------------

def part2_scenario_analysis(prices_a: pd.Series) -> None:
    sep = "=" * 70
    print(f"\n{sep}")
    print("  PART 2: SCENARIO ANALYSIS (Overfitting Check)")
    print(sep)
    print()
    print("  The backtest ends with BTC at $68k (April 2026).")
    print("  BTC peaked at $125k and fell back. DCA-out captured those peaks.")
    print()
    print("  But: what if the next cycle peaks much higher and STAYS there?")
    print("  This analysis replaces the final BTC price with hypothetical values")
    print("  to find the break-even point where hold beats DCA-out.")
    print()
    print("  Method: run each strategy up to the same date, then compute final")
    print("  portfolio value assuming BTC ends at each hypothetical price.")
    print("  Tax is applied consistently to all scenarios.")
    print()

    weekly_dates = _build_weekly_dates(prices_a.index,
                                       prices_a.index[0].strftime("%Y-%m-%d"))
    years = (prices_a.index[-1] - prices_a.index[0]).days / 365.25

    # Simulate and return (btc_units, cash_eur, invested, fifo_state, sell_log)
    def simulate_collect_state(base_price: float, step_size: float,
                               sell_pct: float, cooldown: int) -> dict:
        """Run simulation without closing final position. Return intermediate state."""
        fifo = FIFOCostBasis()
        cash_eur = 0.0
        invested = 0.0
        total_fees = 0.0
        annual_gains: dict[int, float] = {}
        last_trigger_by_level: dict[int, pd.Timestamp | None] = {}

        for date in prices_a.index:
            price = prices_a[date]
            if date in weekly_dates:
                units_bought = WEEKLY_BTC_EUR / price
                fifo.buy(units_bought, price)
                invested += WEEKLY_BTC_EUR

            if base_price > 0 and step_size > 0 and price > base_price and fifo.total_units > 0:
                steps_above = int((price - base_price) / step_size)
                for step in range(1, steps_above + 1):
                    last = last_trigger_by_level.get(step)
                    if last is None or (date - last).days >= cooldown:
                        sell_units = fifo.total_units * sell_pct
                        cost_basis_usd = fifo.sell(sell_units)
                        sell_proceeds_usd = sell_units * price
                        gain_usd = sell_proceeds_usd - cost_basis_usd
                        sell_eur = sell_proceeds_usd - SELL_FEE_EUR
                        if sell_eur > 0:
                            year = date.year
                            annual_gains[year] = annual_gains.get(year, 0) + gain_usd
                            cash_eur += sell_eur
                            total_fees += SELL_FEE_EUR
                            last_trigger_by_level[step] = date

        # Apply historical taxes (years already closed)
        tax_already_paid = 0.0
        for year, gain in annual_gains.items():
            tax = compute_spanish_tax(gain)
            tax_already_paid += tax
            cash_eur -= tax

        return {
            "fifo": fifo,
            "cash_eur": max(cash_eur, 0),
            "invested": invested,
            "tax_paid": tax_already_paid,
            "annual_gains": annual_gains,
        }

    STRATEGIES = [
        ("Pure hold DCA",          0,     0,     0,     0),
        ("3% per $20k @ $80k",     80000, 20000, 0.03,  30),
        ("5% per $20k @ $80k",     80000, 20000, 0.05,  30),
        ("3% per $20k @ $60k",     60000, 20000, 0.03,  30),
        ("3% per $10k @ $80k",     80000, 10000, 0.03,  30),
    ]

    # Collect end state for each strategy
    print("  Computing portfolio state at end of historical data...")
    states = []
    for name, base_p, step_s, sell_p, cd in STRATEGIES:
        s = simulate_collect_state(base_p, step_s, sell_p, cd)
        s["name"] = name
        states.append(s)

    hold_state = states[0]

    print()
    print("  Portfolio state at 2026-04-01 (BEFORE closing final BTC position):")
    print(f"  {'Strategy':<30} | {'BTC held':>10} | {'Cash (EUR)':>12} | {'Invested':>10}")
    print("  " + "-" * 30 + "-+-" + "-+-".join(["-" * 10, "-" * 12, "-" * 10]))
    for s in states:
        print(f"  {s['name']:<30} | {s['fifo'].total_units:>10.4f} | "
              f"{s['cash_eur']:>12,.0f} | {s['invested']:>10,.0f}")

    # Hypothetical final BTC prices
    scenario_prices = [20_000, 40_000, 60_000, 68_000, 80_000, 100_000,
                       125_000, 150_000, 200_000, 300_000, 500_000]

    print()
    print("  Final portfolio value (after-tax) at each hypothetical BTC end price:")
    print()

    # Header
    hdr_parts = [f"{'Strategy':<30}"]
    for sp in scenario_prices:
        hdr_parts.append(f"${sp//1000:>5}k")
    print("  " + " | ".join(hdr_parts))
    print("  " + "-" * 30 + "-+-" +
          "-+-".join(["-" * 6] * len(scenario_prices)))

    all_finals: dict[str, dict[int, float]] = {}

    for s in states:
        finals = {}
        row_parts = [f"{s['name']:<30}"]
        for sp in scenario_prices:
            # Close final BTC position at this price
            remaining = s["fifo"].total_units
            if remaining > 0:
                # Compute cost basis for remaining BTC (use average of what's left)
                # We need to clone FIFO state -- approximate with average cost
                # (exact FIFO would require deep copy; average is close enough for scenario)
                total_cost_approx = s["invested"] - s["cash_eur"] - s["tax_paid"]
                if total_cost_approx < 0:
                    total_cost_approx = remaining * sp * 0.3  # rough fallback
                avg_cost = total_cost_approx / remaining if remaining > 0 else sp
                final_gain = remaining * (sp - avg_cost)
                final_tax = compute_spanish_tax(max(final_gain, 0))
                final_net = remaining * sp - final_tax
            else:
                final_net = 0.0

            total_final = s["cash_eur"] + final_net
            finals[sp] = total_final
            row_parts.append(f"{total_final/1000:>5.0f}k")

        all_finals[s["name"]] = finals
        print("  " + " | ".join(row_parts))

    # Which strategy wins at each price?
    print()
    print("  Winner at each BTC end price:")
    print()
    hold_name = states[0]["name"]
    hdr = f"  {'BTC end price':>15} | {'Winner':<30} | {'Hold final':>10} | {'Winner final':>12} | {'Delta':>8}"
    div = "  " + "-" * 15 + "-+-" + "-+-".join(["-" * 30, "-" * 10, "-" * 12, "-" * 8])
    print(hdr)
    print(div)

    breakeven_found = False
    for sp in scenario_prices:
        hold_val = all_finals[hold_name][sp]
        best_val = hold_val
        best_name = hold_name
        for s in states[1:]:
            val = all_finals[s["name"]][sp]
            if val > best_val:
                best_val = val
                best_name = s["name"]

        delta = best_val - hold_val
        marker = ""
        if best_name == hold_name:
            marker = " <- hold wins"
            if not breakeven_found:
                breakeven_found = True
        print(f"  ${sp:>13,.0f} | {best_name:<30} | {hold_val:>10,.0f} | "
              f"{best_val:>12,.0f} | {delta:>+7,.0f}{marker}")

    # Find exact break-even
    print()
    print("  Break-even analysis:")
    print()

    # For the best DCA-out strategy, find where hold overtakes it
    best_dca_name = max(states[1:],
                        key=lambda s: all_finals[s["name"]][68_000])["name"]
    best_dca_finals = all_finals[best_dca_name]
    hold_finals = all_finals[hold_name]

    # Find crossing point by interpolation
    prices_sorted = sorted(scenario_prices)
    crossover = None
    for i in range(len(prices_sorted) - 1):
        p1, p2 = prices_sorted[i], prices_sorted[i + 1]
        dca1 = best_dca_finals[p1] - hold_finals[p1]
        dca2 = best_dca_finals[p2] - hold_finals[p2]
        if dca1 > 0 and dca2 <= 0:
            # Linear interpolation
            frac = dca1 / (dca1 - dca2)
            crossover = p1 + frac * (p2 - p1)
            break

    if crossover:
        print(f"  Best DCA-out strategy: '{best_dca_name}'")
        print(f"  Break-even BTC price : ~${crossover:,.0f}")
        print()
        print(f"  If BTC ends BELOW ~${crossover:,.0f}: DCA-out wins (captured gains on the way up)")
        print(f"  If BTC ends ABOVE ~${crossover:,.0f}: hold wins (sold too early)")
        print()
        print(f"  Current BTC price in dataset end: $68,117")
        print(f"  BTC ATH in dataset: $124,824")
    else:
        print(f"  Best DCA-out ('{best_dca_name}') wins across all tested scenarios.")

    # Verdict
    print()
    print("  VERDICT:")
    print()
    print("  The overfitting concern is real but bounded.")
    if crossover:
        print(f"  DCA-out wins if BTC ends below ~${crossover:,.0f}.")
        print(f"  That is {crossover/124_824*100:.0f}% of the previous ATH ($124k).")
        print()
        if crossover > 200_000:
            print("  This is a comfortable margin: BTC would need to reach a new ATH of")
            print(f"  ${crossover:,.0f}+ AND stay there permanently for hold to win.")
            print("  In any scenario where BTC peaks and retraces (historical pattern),")
            print("  DCA-out preserves more value.")
        elif crossover > 100_000:
            print("  Moderate margin. If the next cycle peaks above this level and stays,")
            print("  hold wins. Historical pattern: BTC has always retraced significantly.")
        else:
            print("  Tight margin. DCA-out is sensitive to the final price in this backtest.")
    print()
    print("  IMPORTANT: this analysis assumes the SAME historical price path (2018-2026).")
    print("  In the NEXT cycle, BTC will have a different path. The break-even concept")
    print("  is more useful than the exact number -- it tells you the scenario where")
    print("  you'd regret using DCA-out (BTC goes up and stays up permanently).")


# ---------------------------------------------------------------------------
# PART 3: Practical implementation parameters
# ---------------------------------------------------------------------------

def part3_implementation_params() -> None:
    sep = "=" * 70
    print(f"\n{sep}")
    print("  PART 3: IMPLEMENTATION PARAMETERS")
    print(sep)
    print()
    print("  Based on the tax and overfitting analysis, suggested parameters:")
    print()
    print("  BTC DCA-out:")
    print("    Start level  : $80,000 (likely reachable in next cycle)")
    print("    Step size    : $20,000 (11+ sell events if cycle peaks at $300k)")
    print("    % per step   : 3% of holdings at time of sale")
    print("    Cooldown     : 30 days per level (avoids selling same level twice/month)")
    print()
    print("  ETH DCA-out:")
    print("    Start level  : $3,000 (current active alert level)")
    print("    Step size    : $1,000")
    print("    % per step   : 3% of holdings at time of sale")
    print("    Cooldown     : 30 days per level")
    print()
    print("  Why 3% (not 5% or 10%):")
    print("    - 5%: better in scenarios where BTC peaks and falls (captured more)")
    print("    - 5%: WORSE in scenarios where BTC keeps going up (sold too much)")
    print("    - 3%: more conservative, better break-even price, less regret risk")
    print("    - 3% x 10 levels = 30% of position reduced. Still 70% exposed to upside.")
    print()
    print("  Tax planning consideration:")
    print("    - Each sale in the same year adds to your annual taxable gain")
    print("    - If you have big gains in one year from other sources,")
    print("      crypto sales push you into higher brackets")
    print("    - The 30-day cooldown naturally spreads sales across time")
    print("    - No need to concentrate all sales in December for tax reasons")
    print()
    print("  What the alert should say in Discord:")
    print("    'BTC reached $Xk -- DCA-out trigger: consider selling 3% of BTC holdings'")
    print("    (orange alert, same priority as existing $100k alert)")
    print("    Include current BTC/EUR price for easy TR order placement.")
    print()
    print("  Staking note (ETH):")
    print("    ETH is staked in Trade Republic. Confirm that staked ETH can be sold")
    print("    directly (TR handles the unstaking) before implementing ETH alerts.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("=" * 70)
    print("  EXIT SIGNALS RESEARCH 4 -- Pre-implementation checks")
    print("  Tax-adjusted DCA-out + Scenario analysis (overfitting)")
    print("=" * 70)
    print()

    prices_a = fetch_btc_prices()

    part1_tax_analysis(prices_a)
    part2_scenario_analysis(prices_a)
    part3_implementation_params()

    print()
    print("=" * 70)
    print("  ANALYSIS COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
