"""Projection and analysis CLI commands: sparplan-projection, fx, compare-periods.

All local-only. fx uses FRED (public CSV, no API key).
compare-periods uses yfinance (lazy import -- never imported at module level).
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# C5: sparplan-projection -- deterministic compound growth projection
# ---------------------------------------------------------------------------

def cmd_sparplan_projection(args: argparse.Namespace) -> None:
    """Project Sparplan portfolio value over N months at a fixed annual return.

    Deterministic (no randomness). Each month:
      value = value * (1 + monthly_return) + SPARPLAN_MONTHLY_TOTAL
    Output: per-year summary + per-asset breakdown at the end.
    """
    from cli.constants import SPARPLAN_MONTHLY

    months = int(args.months)
    annual_return = float(args.ret)

    if months <= 0:
        print("Error: --months debe ser positivo.")
        return
    if annual_return < -1:
        print("Error: --return debe ser > -1.0 (ej: 0.15 para 15%).")
        return

    monthly_ret = (1 + annual_return) ** (1 / 12) - 1
    monthly_total = sum(SPARPLAN_MONTHLY.values())  # 140 EUR

    print(f"SPARPLAN PROJECTION -- {months} meses, retorno anual {annual_return * 100:.1f}%")
    print("=" * 70)
    print(f"  DCA mensual: {monthly_total:.0f} EUR/mes | Retorno mensual: {monthly_ret * 100:.4f}%")
    print()
    print(f"  {'Mes':>4}  {'Anno':>5}  {'Aportado':>12}  {'Valor':>12}  {'Ganancia':>12}")
    print(f"  {'-'*4}  {'-'*5}  {'-'*12}  {'-'*12}  {'-'*12}")

    value = 0.0
    for month in range(1, months + 1):
        value = value * (1 + monthly_ret) + monthly_total
        contributed = month * monthly_total
        gain = value - contributed

        if month % 12 == 0 or month == months:
            anno = month // 12 if month % 12 == 0 else month / 12
            print(
                f"  {month:>4}  {anno:>5.1f}  "
                f"{contributed:>12,.0f}  {value:>12,.0f}  {gain:>+12,.0f}"
            )

    print()
    contributed_total = months * monthly_total
    gain_total = value - contributed_total
    print(f"  Resumen final ({months} meses = {months / 12:.1f} anos):")
    print(f"    Total aportado:    {contributed_total:>12,.0f} EUR")
    print(f"    Valor proyectado:  {value:>12,.0f} EUR")
    print(f"    Ganancia total:    {gain_total:>+12,.0f} EUR")
    print(f"    Multiplicador:     {value / contributed_total:.2f}x")
    print()
    print("  Distribucion por activo (targets Sparplan):")
    for asset, monthly_eur in sorted(SPARPLAN_MONTHLY.items(), key=lambda x: -x[1]):
        asset_value = value * (monthly_eur / monthly_total)
        asset_contributed = months * monthly_eur
        print(
            f"    {asset:<16} contribuido {asset_contributed:>8,.0f} EUR -> "
            f"proyectado {asset_value:>10,.0f} EUR"
        )


# ---------------------------------------------------------------------------
# C6: fx -- EUR/USD spot rate from FRED + 30d change + ATH/ATL
# ---------------------------------------------------------------------------

def cmd_fx(args: argparse.Namespace) -> None:
    """Show EUR/USD spot rate (30d change, ATH/ATL) from FRED public CSV.

    Source: FRED DEXUSEU (USD per 1 EUR). No API key required.
    """
    import io
    import requests
    import pandas as pd

    pair = (args.pair or "EURUSD").upper()
    fred_id = "DEXUSEU"  # Only EUR/USD supported for now

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        print(f"Error al conectar con FRED: {exc}")
        return

    try:
        df = pd.read_csv(io.StringIO(resp.text), parse_dates=["observation_date"])
        df = df.rename(columns={"observation_date": "DATE", fred_id: "rate"})
        df = df.dropna(subset=["rate"])
        df = df[df["rate"] > 0].sort_values("DATE")
    except Exception as exc:
        print(f"Error al parsear datos FRED: {exc}")
        return

    if df.empty:
        print("No hay datos disponibles.")
        return

    spot = df["rate"].iloc[-1]
    spot_date = df["DATE"].iloc[-1].strftime("%Y-%m-%d")

    df_30d = df[df["DATE"] >= df["DATE"].iloc[-1] - pd.Timedelta(days=30)]
    rate_30d_ago = df_30d["rate"].iloc[0] if len(df_30d) >= 2 else None
    change_30d = ((spot / rate_30d_ago) - 1) * 100 if rate_30d_ago else None

    ath = df["rate"].max()
    atl = df["rate"].min()
    ath_date = df.loc[df["rate"].idxmax(), "DATE"].strftime("%Y-%m-%d")
    atl_date = df.loc[df["rate"].idxmin(), "DATE"].strftime("%Y-%m-%d")

    pct_from_ath = (spot / ath - 1) * 100
    pct_from_atl = (spot / atl - 1) * 100

    print(f"EUR/USD ({pair})  --  Fuente: FRED {fred_id}")
    print("=" * 52)
    print(f"  Spot ({spot_date}):     {spot:.4f}")
    if change_30d is not None:
        arrow = "+" if change_30d >= 0 else ""
        print(f"  Cambio 30d:            {arrow}{change_30d:.2f}%  (base: {rate_30d_ago:.4f})")
    print()
    print(f"  ATH historico:         {ath:.4f}  ({ath_date})  [{pct_from_ath:+.1f}% vs spot]")
    print(f"  ATL historico:         {atl:.4f}  ({atl_date})  [{pct_from_atl:+.1f}% vs spot]")
    print()
    print(f"  Interpretacion: 1 EUR = {spot:.4f} USD | 1 USD = {1 / spot:.4f} EUR")
    print(f"  Promedio historico research (2018-2026): 1.10")


# ---------------------------------------------------------------------------
# C7: compare-periods -- return/volatility/correlation between two date ranges
# ---------------------------------------------------------------------------

def cmd_compare_periods(args: argparse.Namespace) -> None:
    """Compare return, volatility and SP500 correlation for two time periods.

    Uses yfinance (LOCAL ONLY -- lazy import, never in alerts/ or CI).
    --p1 and --p2 must be formatted as START:END (e.g. 2020-01-01:2021-01-01).
    """
    import yfinance as yf
    import pandas as pd

    asset = args.asset.upper()
    ticker_map = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "SP500": "SPY",
        "SEMICONDUCTORS": "SOXX",
        "REALTY_INCOME": "O",
        "URANIUM": "URA",
    }
    sp500_ticker = "SPY"

    if asset not in ticker_map:
        print(f"Error: activo no soportado: {asset}. Opciones: {', '.join(ticker_map)}")
        return

    def _parse_range(s: str) -> tuple[str, str]:
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError(f"Formato invalido: '{s}'. Usa START:END (YYYY-MM-DD:YYYY-MM-DD)")
        return parts[0].strip(), parts[1].strip()

    try:
        p1_start, p1_end = _parse_range(args.p1)
        p2_start, p2_end = _parse_range(args.p2)
    except ValueError as exc:
        print(f"Error: {exc}")
        return

    ticker = ticker_map[asset]

    def _fetch(tk: str, start: str, end: str) -> pd.Series:
        raw = yf.download(tk, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
        if raw.empty:
            return pd.Series(dtype=float)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return raw["Close"].squeeze().dropna()

    def _stats(prices: pd.Series, sp_prices: pd.Series, label: str) -> dict:
        if prices.empty:
            return {"label": label, "error": "sin datos"}
        returns = prices.pct_change().dropna()
        total_ret = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
        annual_vol = returns.std() * (252 ** 0.5) * 100
        corr = None
        if not sp_prices.empty and len(sp_prices) > 5:
            sp_ret = sp_prices.pct_change().dropna()
            aligned = returns.align(sp_ret, join="inner")[0], returns.align(sp_ret, join="inner")[1]
            if len(aligned[0]) > 5:
                corr = float(aligned[0].corr(aligned[1]))
        return {
            "label": label,
            "start": str(prices.index[0].date()),
            "end": str(prices.index[-1].date()),
            "n_days": len(prices),
            "total_return_pct": round(total_ret, 2),
            "annual_vol_pct": round(annual_vol, 2),
            "corr_sp500": round(corr, 3) if corr is not None else None,
        }

    print(f"Descargando datos ({asset}, SP500)... ", end="", flush=True)
    try:
        p1_prices = _fetch(ticker, p1_start, p1_end)
        p2_prices = _fetch(ticker, p2_start, p2_end)
        sp1_prices = _fetch(sp500_ticker, p1_start, p1_end)
        sp2_prices = _fetch(sp500_ticker, p2_start, p2_end)
    except Exception as exc:
        print(f"\nError descargando datos: {exc}")
        return
    print("ok")

    s1 = _stats(p1_prices, sp1_prices, f"P1 ({p1_start} : {p1_end})")
    s2 = _stats(p2_prices, sp2_prices, f"P2 ({p2_start} : {p2_end})")

    def _row(s: dict) -> None:
        if "error" in s:
            print(f"  {s['label']}: {s['error']}")
            return
        print(f"  {s['label']}")
        print(f"    Rango real:      {s['start']} - {s['end']} ({s['n_days']} sesiones)")
        print(f"    Retorno total:   {s['total_return_pct']:+.1f}%")
        print(f"    Volatilidad:     {s['annual_vol_pct']:.1f}% anualizada")
        if s["corr_sp500"] is not None:
            print(f"    Corr. SP500:     {s['corr_sp500']:.3f}")
        else:
            print("    Corr. SP500:     n/a")

    print()
    print(f"COMPARE-PERIODS -- {asset}")
    print("=" * 64)
    _row(s1)
    print()
    _row(s2)

    # Delta summary
    if "error" not in s1 and "error" not in s2:
        delta_ret = s2["total_return_pct"] - s1["total_return_pct"]
        delta_vol = s2["annual_vol_pct"] - s1["annual_vol_pct"]
        print()
        print(f"  Delta P2 vs P1:")
        print(f"    Retorno:         {delta_ret:+.1f}pp")
        print(f"    Volatilidad:     {delta_vol:+.1f}pp")
