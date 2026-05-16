"""dca_out_modalities_research.py
==================================
Research: comparar tres modalidades de DCA-out sobre BTC (2018-2026).

Motivacion
----------
La produccion implementa "rolling 30d": cada nivel arma su propio cooldown
de 30 dias y puede re-disparar indefinidamente. En un bull run prolongado
(BTC parado sobre $120k durante 6 meses) eso implica vender ~9% cada 30d
= ~50% del BTC. El audit MEDIO 9 no aclaro si esa era la intencion.

Este script no toca produccion; compara 3 modalidades sobre el dataset
historico para que Lucas decida.

Modalidades
-----------
1. Rolling 30d (produccion): cada nivel re-arma cooldown 30d, sin tope.
2. Unico por nivel: 3% UNA sola vez por nivel cruzado. No re-trigger nunca.
3. Hibrido con cap 30%: rolling 30d pero parar cuando el total de BTC
   vendido alcanza el 30% del total comprado lifetime.

Setup
-----
- Periodo:       2018-01-01 -> 2026-04-01 (matches Research 3/4/14)
- Weekly DCA:    8 EUR/semana BTC Sparplan (TR free)
- Fee venta:     1 EUR flat (TR manual sell)
- Tax:           Spain IRPF 2024, FIFO, EUR/USD=1.10
- Niveles BTC:   base=$80k, step=$20k, max=$500k, pct=3%

Metricas
--------
- Invested (EUR)
- End value pre-tax / after-tax (EUR)
- CAGR after-tax (%)
- Max drawdown del equity curve (peak-to-trough %)
- N ventas
- % unidades vendidas / total unidades compradas

Run
---
    python research/dca_out_modalities_research.py
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANALYSIS_START = "2018-01-01"
ANALYSIS_END   = "2026-04-01"

WEEKLY_BTC_EUR = 8.0
SELL_FEE_EUR   = 1.0
EUR_USD_AVG    = 1.10

BTC_BASE_USD     = 80_000
BTC_STEP_USD     = 20_000
BTC_MAX_USD      = 500_000
BTC_DCAOUT_PCT   = 3.0
COOLDOWN_DAYS    = 30
HYBRID_CAP_FRAC  = 0.30  # cap total units sold at 30% of total bought

SPAIN_TAX_BRACKETS = [
    (6_000,       0.19),
    (50_000,      0.21),
    (200_000,     0.23),
    (300_000,     0.27),
    (float("inf"), 0.28),
]

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "research_cache"
BTC_CACHE = CACHE_DIR / "btc_cm.csv"
RESULTS_FILE = CACHE_DIR / "dca_out_modalities_results.txt"

Modality = Literal["rolling", "single", "hybrid"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_btc_prices() -> pd.DataFrame:
    if not BTC_CACHE.exists():
        raise SystemExit("Missing cache {}. Run exit_strategy_research.py first.".format(BTC_CACHE))
    df = pd.read_csv(BTC_CACHE, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df[(df["date"] >= ANALYSIS_START) & (df["date"] < ANALYSIS_END)]
    # btc_cm.csv uses 'PriceUSD' or 'price' depending on the snapshot
    price_col = "price" if "price" in df.columns else "PriceUSD"
    df = df.rename(columns={price_col: "price"})
    return df[["date", "price"]].sort_values("date").reset_index(drop=True)


def cagr(start_eur: float, end_eur: float, years: float) -> float:
    if start_eur <= 0 or end_eur <= 0 or years <= 0:
        return 0.0
    return (end_eur / start_eur) ** (1 / years) - 1


def compute_irpf(gain_eur: float) -> float:
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


def max_drawdown(equity: list[float]) -> float:
    peak = -float("inf")
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return worst * 100.0  # negative pct


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(prices_df: pd.DataFrame, modality: Modality) -> dict:
    cost_basis: deque = deque()  # FIFO: list of (units, eur_cost_per_unit)
    total_invested_eur = 0.0
    total_units_bought = 0.0     # lifetime units bought via Sparplan
    total_units_now = 0.0        # current BTC in wallet
    units_sold = 0.0
    cash_eur = 0.0
    total_sold_eur = 0.0
    yearly_gains: dict[int, float] = {}
    level_cooldowns: dict[int, pd.Timestamp | None] = {}
    levels_fired: set[int] = set()
    n_sales = 0
    equity_curve: list[float] = []

    for _, row in prices_df.iterrows():
        date = row["date"]
        price_usd = float(row["price"])
        if price_usd <= 0:
            equity_curve.append(cash_eur)
            continue
        price_eur = price_usd / EUR_USD_AVG

        # 1. Weekly Sparplan buy (Mondays)
        if date.weekday() == 0:
            units = WEEKLY_BTC_EUR / price_eur
            cost_basis.append((units, price_eur))
            total_invested_eur += WEEKLY_BTC_EUR
            total_units_bought += units
            total_units_now += units

        # 2. Check DCA-out levels
        if total_units_now > 0:
            level = BTC_BASE_USD
            while level <= BTC_MAX_USD:
                if price_usd < level:
                    break

                # Modality-specific gating
                fire = False
                if modality == "single":
                    fire = level not in levels_fired
                else:  # rolling or hybrid
                    last_fire = level_cooldowns.get(level)
                    if last_fire is None or (date - last_fire) >= timedelta(days=COOLDOWN_DAYS):
                        fire = True
                    if modality == "hybrid" and fire:
                        # Cap: stop selling once 30% of lifetime units have been sold
                        if total_units_bought > 0 and (units_sold / total_units_bought) >= HYBRID_CAP_FRAC:
                            fire = False

                if fire:
                    units_to_sell = total_units_now * (BTC_DCAOUT_PCT / 100.0)
                    if 0 < units_to_sell <= total_units_now:
                        proceeds_eur = units_to_sell * price_eur - SELL_FEE_EUR
                        # FIFO cost basis consumption
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
                        yearly_gains[date.year] = yearly_gains.get(date.year, 0.0) + gain_eur
                        cash_eur += proceeds_eur
                        total_sold_eur += proceeds_eur
                        total_units_now -= units_to_sell
                        units_sold += units_to_sell
                        n_sales += 1
                        level_cooldowns[level] = date
                        levels_fired.add(level)
                level += BTC_STEP_USD

        # Track daily equity (cash + holdings at current price, before final tax)
        equity_curve.append(cash_eur + total_units_now * price_eur)

    # End-of-period valuation
    final_price_usd = prices_df["price"].iloc[-1]
    final_price_eur = final_price_usd / EUR_USD_AVG
    remaining_value_eur = total_units_now * final_price_eur

    # Tax: realized per-year (progressive brackets) + unrealized assuming full liquidation
    tax_realized = sum(compute_irpf(g) for g in yearly_gains.values() if g > 0)
    remaining_cost_eur = sum(u * c for u, c in cost_basis)
    unrealized_gain = remaining_value_eur - remaining_cost_eur
    tax_unrealized = compute_irpf(unrealized_gain)

    end_value_pre_tax = cash_eur + remaining_value_eur
    end_value_after_tax = end_value_pre_tax - tax_realized - tax_unrealized

    years = (prices_df["date"].iloc[-1] - prices_df["date"].iloc[0]).days / 365.25

    pct_units_sold = (units_sold / total_units_bought * 100.0) if total_units_bought > 0 else 0.0

    return {
        "modality": modality,
        "invested_eur": total_invested_eur,
        "end_value_pre_tax": end_value_pre_tax,
        "tax_realized": tax_realized,
        "tax_unrealized": tax_unrealized,
        "end_value_after_tax": end_value_after_tax,
        "cagr_after_tax": cagr(total_invested_eur, end_value_after_tax, years),
        "max_drawdown_pct": max_drawdown(equity_curve),
        "n_sales": n_sales,
        "units_bought": total_units_bought,
        "units_sold": units_sold,
        "pct_units_sold": pct_units_sold,
        "total_sold_eur": total_sold_eur,
        "cash_eur": cash_eur,
        "remaining_value_eur": remaining_value_eur,
        "years": years,
    }


def simulate_hold(prices_df: pd.DataFrame) -> dict:
    cost_basis: deque = deque()
    total_invested_eur = 0.0
    total_units = 0.0
    equity_curve: list[float] = []

    for _, row in prices_df.iterrows():
        date = row["date"]
        price_usd = float(row["price"])
        if price_usd <= 0:
            equity_curve.append(0.0)
            continue
        price_eur = price_usd / EUR_USD_AVG
        if date.weekday() == 0:
            units = WEEKLY_BTC_EUR / price_eur
            cost_basis.append((units, price_eur))
            total_invested_eur += WEEKLY_BTC_EUR
            total_units += units
        equity_curve.append(total_units * price_eur)

    final_price_eur = prices_df["price"].iloc[-1] / EUR_USD_AVG
    end_value_pre_tax = total_units * final_price_eur
    gain = end_value_pre_tax - total_invested_eur
    tax = compute_irpf(gain)
    end_value_after_tax = end_value_pre_tax - tax

    years = (prices_df["date"].iloc[-1] - prices_df["date"].iloc[0]).days / 365.25

    return {
        "modality": "hold",
        "invested_eur": total_invested_eur,
        "end_value_pre_tax": end_value_pre_tax,
        "tax_realized": 0.0,
        "tax_unrealized": tax,
        "end_value_after_tax": end_value_after_tax,
        "cagr_after_tax": cagr(total_invested_eur, end_value_after_tax, years),
        "max_drawdown_pct": max_drawdown(equity_curve),
        "n_sales": 0,
        "units_bought": total_units,
        "units_sold": 0.0,
        "pct_units_sold": 0.0,
        "total_sold_eur": 0.0,
        "cash_eur": 0.0,
        "remaining_value_eur": end_value_pre_tax,
        "years": years,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_row(r: dict) -> str:
    name = {
        "hold":    "HOLD (sin DCA-out)",
        "rolling": "Rolling 30d (PRODUCCION)",
        "single":  "Unico por nivel",
        "hybrid":  "Hibrido (cap 30% lifetime)",
    }[r["modality"]]
    return (
        "  {name:<28} {inv:>9,.0f} {end:>11,.0f} {tax:>8,.0f} {after:>11,.0f} "
        "{cagr:>6.1f}% {dd:>7.1f}% {sells:>7} {pctu:>7.1f}% {sold:>9,.0f}".format(
            name=name,
            inv=r["invested_eur"],
            end=r["end_value_pre_tax"],
            tax=r["tax_realized"] + r["tax_unrealized"],
            after=r["end_value_after_tax"],
            cagr=r["cagr_after_tax"] * 100,
            dd=r["max_drawdown_pct"],
            sells=r["n_sales"],
            pctu=r["pct_units_sold"],
            sold=r["total_sold_eur"],
        )
    )


def main() -> None:
    print("BTC DCA-OUT MODALITIES RESEARCH")
    print("=" * 70)
    print("  Periodo: {} - {}".format(ANALYSIS_START, ANALYSIS_END))
    print("  Weekly Sparplan: {:.1f} EUR  |  EUR/USD={}".format(WEEKLY_BTC_EUR, EUR_USD_AVG))
    print("  DCA-out: base=${} step=${} pct={}% cooldown={}d max=${}".format(
        BTC_BASE_USD, BTC_STEP_USD, BTC_DCAOUT_PCT, COOLDOWN_DAYS, BTC_MAX_USD,
    ))
    print("  Hybrid cap: {:.0f}% del total comprado".format(HYBRID_CAP_FRAC * 100))
    print()

    df = load_btc_prices()
    print("  BTC price series: N={}  range=${:,.0f}-${:,.0f}  last=${:,.0f}".format(
        len(df), df["price"].min(), df["price"].max(), df["price"].iloc[-1],
    ))
    print()

    results = [
        simulate_hold(df),
        simulate(df, "rolling"),
        simulate(df, "single"),
        simulate(df, "hybrid"),
    ]

    hdr = (
        "  {:<28} {:>9} {:>11} {:>8} {:>11} {:>7} {:>8} {:>7} {:>8} {:>9}".format(
            "modalidad", "invested", "end_value", "tax", "after_tax",
            "CAGR", "max_DD", "n_sales", "pct_sld", "sold_eur",
        )
    )
    sep = "  " + "-" * 110

    out_lines = [
        "BTC DCA-OUT MODALITIES RESEARCH",
        "=" * 70,
        "  Periodo: {} - {}".format(ANALYSIS_START, ANALYSIS_END),
        "  Weekly: {:.1f} EUR  |  base=${}k step=${}k pct={}% cap_hybrid={:.0f}%".format(
            WEEKLY_BTC_EUR, BTC_BASE_USD // 1000, BTC_STEP_USD // 1000,
            BTC_DCAOUT_PCT, HYBRID_CAP_FRAC * 100,
        ),
        "",
        hdr,
        sep,
    ]

    print(hdr)
    print(sep)
    for r in results:
        line = _print_row(r)
        print(line)
        out_lines.append(line)

    # Deltas
    hold_after = results[0]["end_value_after_tax"]
    out_lines += ["", "DELTA vs HOLD (after-tax EUR, pp CAGR)", "-" * 70]
    print()
    print("DELTA vs HOLD (after-tax EUR, pp CAGR)")
    print("-" * 70)
    for r in results[1:]:
        delta_eur = r["end_value_after_tax"] - hold_after
        delta_pct = (delta_eur / hold_after) * 100 if hold_after > 0 else 0.0
        pp = (r["cagr_after_tax"] - results[0]["cagr_after_tax"]) * 100
        line = "  {:<28} {:+,.0f} EUR ({:+.1f}%)  CAGR {:+.2f}pp".format(
            {
                "rolling": "Rolling 30d (PRODUCCION)",
                "single":  "Unico por nivel",
                "hybrid":  "Hibrido (cap 30% lifetime)",
            }[r["modality"]],
            delta_eur, delta_pct, pp,
        )
        out_lines.append(line)
        print(line)

    # Conclusion narrative
    best = max(results, key=lambda r: r["end_value_after_tax"])
    conclusion = [
        "",
        "CONCLUSION",
        "=" * 70,
        "  Modalidad con mejor end_value after-tax: {} -> {:,.0f} EUR".format(
            best["modality"], best["end_value_after_tax"],
        ),
        "  Diferencia vs HOLD: {:+,.0f} EUR".format(best["end_value_after_tax"] - hold_after),
        "  % unidades BTC vendidas en mejor modalidad: {:.1f}%".format(best["pct_units_sold"]),
        "",
        "  Trade-offs:",
        "    - Rolling 30d: maxima captura de subidas, mayor n_sales y tax drag,",
        "      mayor % BTC vendido. Riesgo regret si BTC sigue subiendo.",
        "    - Unico por nivel: minima exposicion a regret pero deja sin capturar",
        "      retracements/re-tests de niveles altos.",
        "    - Hibrido cap 30%: rolling hasta tope. Acota la conversion a cash.",
    ]
    out_lines += conclusion
    for line in conclusion:
        print(line)

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print()
    print("  Results saved to {}".format(RESULTS_FILE))


if __name__ == "__main__":
    main()
