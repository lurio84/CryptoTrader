"""Portfolio FIFO cost basis and IRPF Spain tax calculation.

Logic extracted and adapted from backtesting/exit_signals_research4.py.
Used by the 'python main.py portfolio' commands to track personal holdings.

Trades are passed as plain dicts (not ORM objects) to avoid SQLAlchemy
DetachedInstanceError when using outside a session context.

Dict keys: date (datetime), asset (str), side (str), units (float),
           price_eur (float), fee_eur (float), source (str), notes (str|None)
"""

from __future__ import annotations

import csv
import io
from collections import deque
from datetime import datetime


# ---------------------------------------------------------------------------
# Spain IRPF 2024 tax brackets for capital gains (ahorro base)
# ---------------------------------------------------------------------------

_SPAIN_TAX_BRACKETS = [
    (6_000,        0.19),
    (50_000,       0.21),
    (200_000,      0.23),
    (300_000,      0.27),
    (float("inf"), 0.28),
]


def compute_spanish_tax(annual_gain_eur: float) -> float:
    """Apply Spain IRPF brackets to an annual capital gain in EUR."""
    if annual_gain_eur <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for limit, rate in _SPAIN_TAX_BRACKETS:
        taxable = min(annual_gain_eur, limit) - prev
        tax += taxable * rate
        prev = limit
        if annual_gain_eur <= limit:
            break
    return tax


# ---------------------------------------------------------------------------
# FIFO queue per asset
# ---------------------------------------------------------------------------

class FIFOQueue:
    """Tracks purchase lots in FIFO order for a single asset."""

    def __init__(self) -> None:
        self._lots: deque[list[float]] = deque()  # [units, cost_per_unit_eur]
        self.total_units: float = 0.0
        self.total_invested_eur: float = 0.0

    def buy(self, units: float, price_eur: float, fee_eur: float = 0.0) -> None:
        cost_per_unit = (units * price_eur + fee_eur) / units if units > 0 else price_eur
        self._lots.append([units, cost_per_unit])
        self.total_units += units
        self.total_invested_eur += units * price_eur + fee_eur

    def sell(self, units_to_sell: float) -> tuple[float, float]:
        """Consume lots FIFO. Returns (cost_basis_eur, actual_units_sold).
        actual_units_sold may be less than requested if insufficient holdings."""
        remaining = min(units_to_sell, self.total_units)
        cost_basis = 0.0
        sold = 0.0
        while remaining > 1e-10 and self._lots:
            lot_units, lot_cost = self._lots[0]
            if lot_units <= remaining:
                cost_basis += lot_units * lot_cost
                sold += lot_units
                remaining -= lot_units
                self.total_units -= lot_units
                self._lots.popleft()
            else:
                cost_basis += remaining * lot_cost
                sold += remaining
                self._lots[0][0] -= remaining
                self.total_units -= remaining
                remaining = 0.0
        return cost_basis, sold

    @property
    def avg_cost_eur(self) -> float:
        """Weighted average cost per unit across remaining lots."""
        if self.total_units <= 0:
            return 0.0
        total_cost = sum(u * c for u, c in self._lots)
        return total_cost / self.total_units

    @property
    def remaining_lots(self) -> list[dict]:
        return [{"units": u, "cost_per_unit_eur": c} for u, c in self._lots]


# ---------------------------------------------------------------------------
# Portfolio status calculation
# ---------------------------------------------------------------------------

def calculate_portfolio_status(
    asset: str,
    trades: list[dict],
    current_price_eur: float,
    dca_out_base: float,
    dca_out_step: float,
) -> dict:
    """
    Given a list of trade dicts for an asset, calculate portfolio status.
    Trades must be plain dicts with keys: date, asset, side, units, price_eur, fee_eur.
    """
    fifo = FIFOQueue()
    total_invested = 0.0
    total_proceeds = 0.0
    realized_gain = 0.0
    buy_count = 0
    sell_count = 0

    for t in sorted(trades, key=lambda x: x["date"]):
        if t["side"] == "buy":
            fifo.buy(t["units"], t["price_eur"], t["fee_eur"])
            total_invested += t["units"] * t["price_eur"] + t["fee_eur"]
            buy_count += 1
        elif t["side"] == "sell":
            cost_basis, sold = fifo.sell(t["units"])
            proceeds = sold * t["price_eur"] - t["fee_eur"]
            realized_gain += proceeds - cost_basis
            total_proceeds += proceeds
            sell_count += 1

    units_held = fifo.total_units
    avg_cost = fifo.avg_cost_eur
    current_value = units_held * current_price_eur
    unrealized_gain = current_value - (units_held * avg_cost) if avg_cost > 0 else 0.0
    unrealized_pct = (unrealized_gain / (units_held * avg_cost) * 100) if avg_cost > 0 and units_held > 0 else 0.0

    # Estimated IRPF if sold entirely today
    irpf_estimate = compute_spanish_tax(max(unrealized_gain, 0))

    # Next DCA-out level
    next_dca_level = None
    next_dca_units = None
    next_dca_eur = None
    level = dca_out_base
    while level <= current_price_eur:
        level += dca_out_step
    if level <= dca_out_base * 10:  # sanity cap
        next_dca_level = level
        next_dca_units = units_held * 0.03
        next_dca_eur = next_dca_units * current_price_eur

    return {
        "asset": asset,
        "units_held": units_held,
        "avg_cost_eur": avg_cost,
        "current_price_eur": current_price_eur,
        "current_value_eur": current_value,
        "total_invested_eur": total_invested,
        "unrealized_gain_eur": unrealized_gain,
        "unrealized_pct": unrealized_pct,
        "realized_gain_eur": realized_gain,
        "irpf_estimate_eur": irpf_estimate,
        "irpf_rate_pct": (irpf_estimate / unrealized_gain * 100) if unrealized_gain > 0 else 0.0,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "next_dca_level_eur": next_dca_level,
        "next_dca_units": next_dca_units,
        "next_dca_eur": next_dca_eur,
    }


# ---------------------------------------------------------------------------
# Tax report (IRPF Spain)
# ---------------------------------------------------------------------------

def calculate_tax_report(all_trades: list[dict], year: int) -> dict:
    """Generate the IRPF fiscal report for a given year.

    Processes all trades chronologically to maintain correct FIFO state,
    then extracts sells that occurred within 'year'.

    Returns dict with:
      - rows: list[dict] — one row per sell event in the year
          keys: date, asset, units, sale_price_eur, cost_basis_eur,
                proceeds_eur, gain_eur
      - total_gain_eur: net realized gain for the year (losses offset gains)
      - total_irpf_eur: estimated IRPF on total_gain_eur
      - effective_rate_pct: effective tax rate
      - bracket_breakdown: list[dict] with (limit_label, rate, tax_eur) per bracket
    """
    from collections import defaultdict

    # Group trades by asset, sort globally by date for FIFO correctness
    assets = defaultdict(list)
    for t in sorted(all_trades, key=lambda x: x["date"]):
        assets[t["asset"]].append(t)

    rows: list[dict] = []

    for asset, trades in assets.items():
        fifo = FIFOQueue()
        for t in trades:
            if t["side"] == "buy":
                fifo.buy(t["units"], t["price_eur"], t["fee_eur"])
            elif t["side"] == "sell":
                cost_basis, actual_sold = fifo.sell(t["units"])
                proceeds = actual_sold * t["price_eur"] - t["fee_eur"]
                gain = proceeds - cost_basis
                trade_date = t["date"]
                trade_year = trade_date.year if hasattr(trade_date, "year") else int(str(trade_date)[:4])
                if trade_year == year:
                    rows.append({
                        "date": trade_date,
                        "asset": asset,
                        "units": actual_sold,
                        "sale_price_eur": t["price_eur"],
                        "cost_basis_eur": cost_basis,
                        "proceeds_eur": proceeds,
                        "gain_eur": gain,
                    })

    rows.sort(key=lambda r: r["date"])

    total_gain = sum(r["gain_eur"] for r in rows)
    total_irpf = compute_spanish_tax(max(total_gain, 0))
    effective_rate = (total_irpf / total_gain * 100) if total_gain > 0 else 0.0

    # Bracket breakdown (for display)
    bracket_breakdown: list[dict] = []
    if total_gain > 0:
        prev = 0.0
        bracket_labels = ["<=6.000 EUR", "6.001-50.000 EUR", "50.001-200.000 EUR", "200.001-300.000 EUR", ">300.000 EUR"]
        for (limit, rate), label in zip(_SPAIN_TAX_BRACKETS, bracket_labels):
            taxable = min(total_gain, limit) - prev
            if taxable <= 0:
                break
            bracket_breakdown.append({
                "label": label,
                "rate_pct": rate * 100,
                "taxable_eur": taxable,
                "tax_eur": taxable * rate,
            })
            prev = limit
            if total_gain <= limit:
                break

    return {
        "year": year,
        "rows": rows,
        "total_gain_eur": total_gain,
        "total_irpf_eur": total_irpf,
        "effective_rate_pct": effective_rate,
        "bracket_breakdown": bracket_breakdown,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def trades_to_csv(trades: list[dict]) -> str:
    """Serialize trade dicts to CSV string for backup."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "asset", "asset_class", "side", "units", "price_eur", "fee_eur", "source", "notes"])
    for t in sorted(trades, key=lambda x: x["date"]):
        d = t["date"]
        writer.writerow([
            d.strftime("%Y-%m-%d") if isinstance(d, datetime) else str(d),
            t["asset"],
            t.get("asset_class") or "crypto",
            t["side"],
            "{:.8f}".format(t["units"]),
            "{:.2f}".format(t["price_eur"]),
            "{:.2f}".format(t["fee_eur"]),
            t.get("source") or "",
            t.get("notes") or "",
        ])
    return buf.getvalue()
