"""full_plan_simulation_2020.py
==============================
Simula el plan completo de inversion en crypto desde 2020-01-01 hasta 2026-04-01.

Plan simulado:
  BTC:
    - Sparplan: 8 EUR/semana (cada lunes)
    - Extra crash buy: 125 EUR cuando BTC cae >15% en 24h (cooldown 6h -> 1 dia)
    - DCA-out: vender 3% cada $20k por encima de $80k (cooldown 30 dias)

  ETH:
    - Sparplan: 2 EUR/semana (cada lunes)
    - Extra MVRV < 0.8: 100 EUR compra (cooldown 24h)
    - Extra MVRV 0.8-1.0: ignorado (solo aumentar Sparplan, no modelable facilmente)
    - DCA-out: vender 3% cada $1k por encima de $3k (cooldown 30 dias)

  Staking ETH: +4% anualizado sobre ETH holdings (aprox. rendimiento TR staking)

  Fees: 0 EUR en Sparplans (TR gratis), 1 EUR en compras manuales y ventas DCA-out

  Sin impuestos (para ver bruto) y con impuestos IRPF Espana (para ver neto).

Nota: USD/EUR conversion via precio de BTC/ETH en EUR vs USD.
El script usa precios en USD de CoinMetrics y asume EUR/USD = precio_eur_btc / precio_usd_btc.
Para simplificar: usamos CoinGecko EUR proxy. Dado que no tenemos serie historica EUR/USD
en cache, usamos una EUR/USD aproximada de 1.10 (media 2020-2026 razonable).
Esto no afecta significativamente los resultados ya que las compras en EUR se convierten
al tipo del dia de compra (price_usd / 1.10 = price_eur).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

START = "2020-01-01"
END   = "2026-04-01"

# Sparplans
BTC_WEEKLY_EUR = 8.0
ETH_WEEKLY_EUR = 2.0

# Extra compras
BTC_CRASH_BUY_EUR     = 125.0   # cuando BTC cae >15% en 24h
BTC_CRASH_THRESHOLD   = -0.15   # -15%
BTC_CRASH_COOLDOWN    = 1       # dias (6h -> redondeamos a 1 dia)

ETH_MVRV_BUY_EUR      = 100.0   # cuando MVRV < 0.8
ETH_MVRV_THRESHOLD    = 0.8
ETH_MVRV_COOLDOWN     = 7       # dias (alineado con produccion)

# DCA-out BTC: 3% cada $20k por encima de $80k
BTC_DCAOUT_BASE       = 80_000
BTC_DCAOUT_STEP       = 20_000
BTC_DCAOUT_PCT        = 0.03
BTC_DCAOUT_COOLDOWN   = 30      # dias

# DCA-out ETH: 3% cada $1k por encima de $3k
ETH_DCAOUT_BASE       = 3_000
ETH_DCAOUT_STEP       = 1_000
ETH_DCAOUT_PCT        = 0.03
ETH_DCAOUT_COOLDOWN   = 30      # dias

# ETH staking reward (anualizado, aplicado diariamente)
ETH_STAKING_APR       = 0.04

# Fees
SPARPLAN_FEE_EUR      = 0.0   # Trade Republic Sparplan = gratis
MANUAL_BUY_FEE_EUR    = 1.0   # compra manual (crash, MVRV)
SELL_FEE_EUR          = 1.0   # venta DCA-out

# EUR/USD aproximacion (media 2020-2026)
EURUSD = 1.10

CACHE_DIR = Path(__file__).parent.parent / "data" / "research_cache"

# Spain IRPF 2024
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

def load_prices(symbol: str) -> pd.Series:
    df = pd.read_csv(CACHE_DIR / f"{symbol}_cm.csv", parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date").sort_values("date").set_index("date")
    return df["price"].loc[START:END]


def load_eth_mvrv() -> pd.Series:
    df = pd.read_csv(CACHE_DIR / "eth_mvrv.csv", parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date").sort_values("date").set_index("date")
    return df["mvrv"].loc[START:END]


def usd_to_eur(usd: float) -> float:
    return usd / EURUSD


def eur_to_usd(eur: float) -> float:
    return eur * EURUSD


def compute_spanish_tax(annual_gain_eur: float) -> float:
    if annual_gain_eur <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for limit, rate in SPAIN_TAX_BRACKETS:
        chunk = min(annual_gain_eur, limit) - prev
        if chunk <= 0:
            break
        tax += chunk * rate
        prev = limit
        if annual_gain_eur <= limit:
            break
    return tax


class FIFOCostBasis:
    def __init__(self):
        self._queue: deque[list[float]] = deque()
        self.total_units: float = 0.0

    def buy(self, units: float, cost_per_unit_eur: float) -> None:
        self._queue.append([units, cost_per_unit_eur])
        self.total_units += units

    def sell(self, units_to_sell: float) -> float:
        """Returns total cost basis (EUR) of sold units."""
        if units_to_sell <= 0:
            return 0.0
        units_to_sell = min(units_to_sell, self.total_units)
        cost_basis = 0.0
        remaining = units_to_sell
        while remaining > 1e-12 and self._queue:
            lot_units, lot_cost = self._queue[0]
            if lot_units <= remaining:
                cost_basis += lot_units * lot_cost
                remaining -= lot_units
                self._queue.popleft()
            else:
                cost_basis += remaining * lot_cost
                self._queue[0][0] -= remaining
                remaining = 0.0
        self.total_units = max(0.0, self.total_units - units_to_sell)
        return cost_basis


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(apply_taxes: bool = False) -> dict:
    btc_prices = load_prices("btc")
    eth_prices = load_prices("eth")
    eth_mvrv   = load_eth_mvrv()

    # Align to common dates
    dates = btc_prices.index.intersection(eth_prices.index)
    dates = dates[dates >= pd.Timestamp(START)]

    btc_prices = btc_prices.reindex(dates).ffill()
    eth_prices = eth_prices.reindex(dates).ffill()
    eth_mvrv   = eth_mvrv.reindex(dates).ffill().fillna(1.5)

    # Weekly buy dates (cada lunes, o el dia habil mas cercano)
    weekly_dates: set[pd.Timestamp] = set()
    d = pd.Timestamp(START)
    while d <= dates[-1]:
        pos = dates.searchsorted(d)
        if pos < len(dates):
            weekly_dates.add(dates[pos])
        d += pd.Timedelta(days=7)

    # State
    btc_units = 0.0
    eth_units = 0.0
    cash_eur  = 0.0   # cash generado por DCA-out ventas (neto de impuestos)

    btc_fifo = FIFOCostBasis()
    eth_fifo = FIFOCostBasis()

    total_invested_eur = 0.0
    total_fees_eur     = 0.0
    total_taxes_eur    = 0.0

    btc_crash_last     = pd.Timestamp("1900-01-01")
    eth_mvrv_buy_last  = pd.Timestamp("1900-01-01")
    btc_dcaout_last    = pd.Timestamp("1900-01-01")
    eth_dcaout_last    = pd.Timestamp("1900-01-01")
    btc_dcaout_triggered: set[int] = set()  # niveles ya ejecutados en este ciclo
    eth_dcaout_triggered: set[int] = set()

    # Log detallado
    events = []

    annual_gains: dict[int, float] = {}   # para impuestos anuales (solo si apply_taxes)

    def record_tax_gain(date: pd.Timestamp, gain_eur: float):
        if not apply_taxes or gain_eur <= 0:
            return 0.0
        year = date.year
        annual_gains[year] = annual_gains.get(year, 0.0) + gain_eur
        return 0.0  # impuestos se calculan al final del ano

    prev_btc_price = btc_prices.iloc[0]

    for date in dates:
        btc_price_usd = btc_prices[date]
        eth_price_usd = eth_prices[date]
        btc_price_eur = usd_to_eur(btc_price_usd)
        eth_price_eur = usd_to_eur(eth_price_usd)
        mvrv          = eth_mvrv[date]

        # -- ETH staking: acumula unidades diariamente --
        daily_staking_rate = ETH_STAKING_APR / 365.0
        eth_staking_units  = eth_units * daily_staking_rate
        if eth_staking_units > 0:
            eth_units += eth_staking_units
            # Staking en TR: no evento fiscal en Espana hasta venta (debatible,
            # pero usamos criterio conservador: el staking reward se anota
            # al precio del dia como coste base cero -- simplificacion).
            eth_fifo.buy(eth_staking_units, 0.0)  # coste base 0 (reward)

        # ---- SPARPLAN SEMANAL ----
        if date in weekly_dates:
            # BTC sparplan
            fee = SPARPLAN_FEE_EUR
            spent_eur = BTC_WEEKLY_EUR - fee
            units_bought = spent_eur / btc_price_eur
            btc_units += units_bought
            btc_fifo.buy(units_bought, btc_price_eur)
            total_invested_eur += BTC_WEEKLY_EUR
            total_fees_eur += fee
            events.append((date, "BTC_SPARPLAN", BTC_WEEKLY_EUR, btc_price_eur, units_bought))

            # ETH sparplan
            fee = SPARPLAN_FEE_EUR
            spent_eur = ETH_WEEKLY_EUR - fee
            units_bought = spent_eur / eth_price_eur
            eth_units += units_bought
            eth_fifo.buy(units_bought, eth_price_eur)
            total_invested_eur += ETH_WEEKLY_EUR
            total_fees_eur += fee
            events.append((date, "ETH_SPARPLAN", ETH_WEEKLY_EUR, eth_price_eur, units_bought))

        # ---- BTC CRASH BUY ----
        btc_24h_return = (btc_price_usd / prev_btc_price - 1) if prev_btc_price > 0 else 0
        if (btc_24h_return <= BTC_CRASH_THRESHOLD and
                (date - btc_crash_last).days >= BTC_CRASH_COOLDOWN):
            fee = MANUAL_BUY_FEE_EUR
            spent_eur = BTC_CRASH_BUY_EUR - fee
            units_bought = spent_eur / btc_price_eur
            btc_units += units_bought
            btc_fifo.buy(units_bought, btc_price_eur)
            total_invested_eur += BTC_CRASH_BUY_EUR
            total_fees_eur += fee
            btc_crash_last = date
            events.append((date, "BTC_CRASH_BUY", BTC_CRASH_BUY_EUR, btc_price_eur, units_bought))

        # ---- ETH MVRV < 0.8 BUY ----
        if (mvrv < ETH_MVRV_THRESHOLD and
                (date - eth_mvrv_buy_last).days >= ETH_MVRV_COOLDOWN):
            fee = MANUAL_BUY_FEE_EUR
            spent_eur = ETH_MVRV_BUY_EUR - fee
            units_bought = spent_eur / eth_price_eur
            eth_units += units_bought
            eth_fifo.buy(units_bought, eth_price_eur)
            total_invested_eur += ETH_MVRV_BUY_EUR
            total_fees_eur += fee
            eth_mvrv_buy_last = date
            events.append((date, "ETH_MVRV_BUY", ETH_MVRV_BUY_EUR, eth_price_eur, units_bought))

        # ---- BTC DCA-OUT ----
        if btc_units > 0:
            if btc_price_usd >= BTC_DCAOUT_BASE:
                # Calcular nivel actual
                level = int((btc_price_usd - BTC_DCAOUT_BASE) / BTC_DCAOUT_STEP)
                if (level not in btc_dcaout_triggered and
                        (date - btc_dcaout_last).days >= BTC_DCAOUT_COOLDOWN):
                    units_to_sell = btc_units * BTC_DCAOUT_PCT
                    cost_basis = btc_fifo.sell(units_to_sell)
                    proceeds_eur = units_to_sell * btc_price_eur - SELL_FEE_EUR
                    gain_eur = proceeds_eur - cost_basis
                    btc_units -= units_to_sell

                    tax_eur = 0.0
                    if apply_taxes and gain_eur > 0:
                        record_tax_gain(date, gain_eur)

                    cash_eur += proceeds_eur
                    total_fees_eur += SELL_FEE_EUR
                    btc_dcaout_triggered.add(level)
                    btc_dcaout_last = date
                    events.append((date, f"BTC_DCAOUT_L{level}", -units_to_sell * btc_price_eur,
                                   btc_price_eur, -units_to_sell))
            else:
                # BTC volvio a bajar de $80k -- reset triggers para siguiente ciclo
                btc_dcaout_triggered.clear()

        # ---- ETH DCA-OUT ----
        if eth_units > 0:
            if eth_price_usd >= ETH_DCAOUT_BASE:
                level = int((eth_price_usd - ETH_DCAOUT_BASE) / ETH_DCAOUT_STEP)
                if (level not in eth_dcaout_triggered and
                        (date - eth_dcaout_last).days >= ETH_DCAOUT_COOLDOWN):
                    units_to_sell = eth_units * ETH_DCAOUT_PCT
                    cost_basis = eth_fifo.sell(units_to_sell)
                    proceeds_eur = units_to_sell * eth_price_eur - SELL_FEE_EUR
                    gain_eur = proceeds_eur - cost_basis
                    eth_units -= units_to_sell

                    if apply_taxes and gain_eur > 0:
                        record_tax_gain(date, gain_eur)

                    cash_eur += proceeds_eur
                    total_fees_eur += SELL_FEE_EUR
                    eth_dcaout_triggered.add(level)
                    eth_dcaout_last = date
                    events.append((date, f"ETH_DCAOUT_L{level}", -units_to_sell * eth_price_eur,
                                   eth_price_eur, -units_to_sell))

        prev_btc_price = btc_price_usd

    # -- Calcular impuestos anuales acumulados --
    if apply_taxes:
        for year, annual_gain in annual_gains.items():
            tax = compute_spanish_tax(annual_gain)
            total_taxes_eur += tax

    # -- Estado final --
    final_btc_price_usd = btc_prices.iloc[-1]
    final_eth_price_usd = eth_prices.iloc[-1]
    final_btc_eur = usd_to_eur(final_btc_price_usd)
    final_eth_eur = usd_to_eur(final_eth_price_usd)

    btc_value_eur = btc_units * final_btc_eur
    eth_value_eur = eth_units * final_eth_eur
    total_portfolio_eur = btc_value_eur + eth_value_eur + cash_eur - (total_taxes_eur if apply_taxes else 0)
    total_return_pct = (total_portfolio_eur / total_invested_eur - 1) * 100

    return {
        "start": START,
        "end": END,
        "apply_taxes": apply_taxes,
        "total_invested_eur": total_invested_eur,
        "btc_units": btc_units,
        "eth_units": eth_units,
        "cash_eur": cash_eur,
        "btc_value_eur": btc_value_eur,
        "eth_value_eur": eth_value_eur,
        "total_portfolio_eur": total_portfolio_eur,
        "total_return_pct": total_return_pct,
        "total_fees_eur": total_fees_eur,
        "total_taxes_eur": total_taxes_eur,
        "final_btc_price_usd": final_btc_price_usd,
        "final_eth_price_usd": final_eth_price_usd,
        "events": events,
    }


def print_events(events: list, label: str):
    crash_buys = [(d, e, a) for d, e, a, _, _ in events if e == "BTC_CRASH_BUY"]
    mvrv_buys  = [(d, a) for d, e, a, _, _ in events if e == "ETH_MVRV_BUY"]
    btc_outs   = [(d, e, a, p) for d, e, a, p, _ in events if "BTC_DCAOUT" in e]
    eth_outs   = [(d, e, a, p) for d, e, a, p, _ in events if "ETH_DCAOUT" in e]
    btc_weeks  = sum(1 for _, e, _, _, _ in events if e == "BTC_SPARPLAN")
    eth_weeks  = sum(1 for _, e, _, _, _ in events if e == "ETH_SPARPLAN")

    print(f"\n  === Eventos {label} ===")
    print(f"  Semanas Sparplan BTC: {btc_weeks}  ({btc_weeks * BTC_WEEKLY_EUR:.0f} EUR)")
    print(f"  Semanas Sparplan ETH: {eth_weeks}  ({eth_weeks * ETH_WEEKLY_EUR:.0f} EUR)")

    print(f"\n  BTC Crash buys ({len(crash_buys)} eventos):")
    for d, e, a in crash_buys[:20]:
        print(f"    {d.date()}  {a:.0f} EUR")
    if len(crash_buys) > 20:
        print(f"    ... y {len(crash_buys)-20} mas")

    print(f"\n  ETH MVRV<0.8 buys ({len(mvrv_buys)} eventos - primeros 10 y ultimos 5):")
    for d, a in mvrv_buys[:10]:
        print(f"    {d.date()}  {a:.0f} EUR")
    if len(mvrv_buys) > 15:
        print(f"    ...")
        for d, a in mvrv_buys[-5:]:
            print(f"    {d.date()}  {a:.0f} EUR")
    elif len(mvrv_buys) > 10:
        for d, a in mvrv_buys[10:]:
            print(f"    {d.date()}  {a:.0f} EUR")

    print(f"\n  BTC DCA-out ventas ({len(btc_outs)} eventos):")
    for d, e, a, p in btc_outs:
        print(f"    {d.date()}  {e}  precio ${p * EURUSD:,.0f}  recibe {abs(a):.0f} EUR")

    print(f"\n  ETH DCA-out ventas ({len(eth_outs)} eventos):")
    for d, e, a, p in eth_outs:
        print(f"    {d.date()}  {e}  precio ${p * EURUSD:,.0f}  recibe {abs(a):.0f} EUR")


def print_result(r: dict):
    label = "CON IRPF" if r["apply_taxes"] else "SIN IMPUESTOS"
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  RESULTADO FINAL {label}")
    print(sep)
    print(f"  Periodo          : {r['start']} -> {r['end']}")
    print(f"  EUR/USD asumido  : {EURUSD}")
    print()
    print(f"  INVERSION TOTAL  : {r['total_invested_eur']:>10,.0f} EUR")
    print(f"  Fees pagados     : {r['total_fees_eur']:>10,.0f} EUR")
    if r["apply_taxes"]:
        print(f"  Impuestos IRPF   : {r['total_taxes_eur']:>10,.0f} EUR")
    print()
    print(f"  BTC en cartera   : {r['btc_units']:.6f} BTC")
    print(f"  ETH en cartera   : {r['eth_units']:.4f} ETH")
    print(f"  BTC precio final : ${r['final_btc_price_usd']:>10,.0f} ({usd_to_eur(r['final_btc_price_usd']):,.0f} EUR)")
    print(f"  ETH precio final : ${r['final_eth_price_usd']:>10,.0f} ({usd_to_eur(r['final_eth_price_usd']):,.0f} EUR)")
    print()
    print(f"  Valor BTC        : {r['btc_value_eur']:>10,.0f} EUR")
    print(f"  Valor ETH        : {r['eth_value_eur']:>10,.0f} EUR")
    print(f"  Cash (DCA-out)   : {r['cash_eur']:>10,.0f} EUR")
    print(f"  {'- Impuestos' if r['apply_taxes'] else '':12}   {-r['total_taxes_eur'] if r['apply_taxes'] else 0:>10,.0f} EUR")
    print(f"  {'=' * 38}")
    print(f"  TOTAL PORTFOLIO  : {r['total_portfolio_eur']:>10,.0f} EUR")
    print(f"  Retorno total    : {r['total_return_pct']:>+.1f}%")
    print(f"  Multiplicador    : x{r['total_portfolio_eur'] / r['total_invested_eur']:.2f}")
    years = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
    cagr_val = (r['total_portfolio_eur'] / r['total_invested_eur']) ** (1 / years) - 1
    print(f"  CAGR             : {cagr_val * 100:.1f}%/ano")
    print()

    # Desglose de inversion
    btc_sparplan = sum(a for _, e, a, _, _ in r["events"] if e == "BTC_SPARPLAN")
    eth_sparplan = sum(a for _, e, a, _, _ in r["events"] if e == "ETH_SPARPLAN")
    crash_total  = sum(a for _, e, a, _, _ in r["events"] if e == "BTC_CRASH_BUY")
    mvrv_total   = sum(a for _, e, a, _, _ in r["events"] if e == "ETH_MVRV_BUY")
    n_crash = sum(1 for _, e, _, _, _ in r["events"] if e == "BTC_CRASH_BUY")
    n_mvrv  = sum(1 for _, e, _, _, _ in r["events"] if e == "ETH_MVRV_BUY")
    n_btc_out = sum(1 for _, e, _, _, _ in r["events"] if "BTC_DCAOUT" in e)
    n_eth_out = sum(1 for _, e, _, _, _ in r["events"] if "ETH_DCAOUT" in e)

    print(f"  DESGLOSE INVERSION:")
    print(f"    BTC Sparplan    : {btc_sparplan:>8,.0f} EUR")
    print(f"    ETH Sparplan    : {eth_sparplan:>8,.0f} EUR")
    print(f"    BTC crash buys  : {crash_total:>8,.0f} EUR  ({n_crash} eventos)")
    print(f"    ETH MVRV buys   : {mvrv_total:>8,.0f} EUR  ({n_mvrv} eventos)")
    print(f"    BTC ventas DCA-out: {n_btc_out} ventas")
    print(f"    ETH ventas DCA-out: {n_eth_out} ventas")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nSimulando plan completo crypto 2020-2026...")
    print(f"Configuracion: BTC {BTC_WEEKLY_EUR} EUR/sem + ETH {ETH_WEEKLY_EUR} EUR/sem")
    print(f"  + crash buys + MVRV buys + DCA-out + staking ETH {ETH_STAKING_APR*100:.0f}%")

    r_bruto = simulate(apply_taxes=False)
    print_result(r_bruto)
    print_events(r_bruto["events"], "detallado")

    r_neto = simulate(apply_taxes=True)
    print_result(r_neto)

    # Comparativa rapida
    print("\n" + "=" * 65)
    print("  COMPARATIVA RAPIDA")
    print("=" * 65)
    print(f"  Total invertido    : {r_bruto['total_invested_eur']:,.0f} EUR")
    print(f"  Portfolio bruto    : {r_bruto['total_portfolio_eur']:,.0f} EUR  (+{r_bruto['total_return_pct']:.0f}%)")
    print(f"  Portfolio neto IRPF: {r_neto['total_portfolio_eur']:,.0f} EUR  (+{r_neto['total_return_pct']:.0f}%)")
    print(f"  Diferencia imptos  : {r_bruto['total_portfolio_eur'] - r_neto['total_portfolio_eur']:,.0f} EUR")

    # Solo sparplan sin extras
    print("\n  [Para referencia: si solo hubiera hecho Sparplan sin extras ni DCA-out]")
    btc_only_sparplan = sum(a for _, e, a, _, _ in r_bruto["events"] if e == "BTC_SPARPLAN")
    eth_only_sparplan = sum(a for _, e, a, _, _ in r_bruto["events"] if e == "ETH_SPARPLAN")
    btc_sparplan_units = sum(u for _, e, _, _, u in r_bruto["events"] if e == "BTC_SPARPLAN")
    eth_sparplan_units = sum(u for _, e, _, _, u in r_bruto["events"] if e == "ETH_SPARPLAN")
    sparplan_val = (btc_sparplan_units * usd_to_eur(r_bruto["final_btc_price_usd"]) +
                    eth_sparplan_units * usd_to_eur(r_bruto["final_eth_price_usd"]))
    sparplan_inv = btc_only_sparplan + eth_only_sparplan
    print(f"  Solo Sparplan invertido : {sparplan_inv:,.0f} EUR")
    print(f"  Solo Sparplan valor fin : {sparplan_val:,.0f} EUR  (+{(sparplan_val/sparplan_inv-1)*100:.0f}%)")
    print()
    print("  NOTA: Simulacion usa EUR/USD fijo = 1.10 (media 2020-2026).")
    print("  NOTA: ETH staking contabilizado como acumulacion de unidades.")
    print("  NOTA: MVRV buys tienen cooldown 7 dias (alineado con produccion).")
