"""Analysis commands: rebalance, retirement-plan."""

import argparse
import sys

from cli.constants import SPARPLAN_TARGETS


def cmd_rebalance(args: argparse.Namespace) -> None:
    """Calculate if annual portfolio rebalancing is needed (all 6 assets)."""
    import requests as req

    THRESHOLD_PP = 10.0

    print("CryptoTrader - Rebalanceo Anual (6 activos)")
    print("=" * 60)

    try:
        resp = req.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "eur"},
            timeout=10,
        )
        resp.raise_for_status()
        cg = resp.json()
        btc_eur = cg["bitcoin"]["eur"]
        eth_eur = cg["ethereum"]["eur"]
    except Exception as e:
        print(f"Error fetching prices from CoinGecko: {e}")
        sys.exit(1)

    values = {
        "BTC":            args.btc * btc_eur,
        "ETH":            args.eth * eth_eur,
        "SP500":          args.sp500,
        "SEMICONDUCTORS": args.semis,
        "REALTY_INCOME":  args.realty,
        "URANIUM":        args.uranium,
    }
    total = sum(values.values())

    if total <= 0:
        print("Error: el total de la cartera es 0.")
        sys.exit(1)

    print("\n  Precios crypto actuales:")
    print(f"    BTC: {btc_eur:>10,.0f} EUR  |  ETH: {eth_eur:>10,.0f} EUR")

    print(f"\n  {'Activo':<16} {'Valor EUR':>10}  {'Actual%':>7}  {'Target%':>7}  {'Drift':>7}  Estado")
    print(f"  {'-'*16} {'-'*10}  {'-'*7}  {'-'*7}  {'-'*7}  ------")

    actions = []

    for asset, target_pct in SPARPLAN_TARGETS.items():
        val = values.get(asset, 0.0)
        actual_pct = val / total * 100
        drift = actual_pct - target_pct
        if abs(drift) > THRESHOLD_PP:
            estado = "[REBALANCEAR]"
            actions.append((asset, drift, val, target_pct, total))
        elif abs(drift) > THRESHOLD_PP / 2:
            estado = "[WATCH]"
        else:
            estado = "[OK]"
        print(f"  {asset:<16} {val:>10,.0f}E  {actual_pct:>6.1f}%  {target_pct:>6.1f}%  {drift:>+6.1f}pp  {estado}")

    print(f"  {'TOTAL':<16} {total:>10,.0f}E")

    if actions:
        print(f"\n  Acciones recomendadas (threshold: |drift| > {THRESHOLD_PP:.0f}pp):")
        for asset, drift, val, target_pct, total_v in actions:
            target_value = total_v * target_pct / 100
            if drift > 0:
                diff_eur = val - target_value
                print(f"    [VENDER] {asset}: sobrepesado {drift:+.1f}pp -> vende ~{diff_eur:,.0f} EUR en TR")
                print("             Reinvertir en activos bajo su target")
            else:
                diff_eur = target_value - val
                print(f"    [COMPRAR] {asset}: infrapesado {drift:.1f}pp -> compra ~{diff_eur:,.0f} EUR extra en TR")
        print("\n  Costes: ~1 EUR flat fee por operacion en TR")
        print("  IRPF: tributa la plusvalia en ventas (precio venta - coste FIFO)")
        print("  Research: rebalanceo anual mejora CAGR de 12.5%% a 14.7%% (datos 2018-2026)")
    else:
        print("\n  Cartera dentro de rangos normales. No es necesario rebalancear.")

    print(f"\n{'='*60}")


def cmd_retirement_plan(args: argparse.Namespace) -> None:
    """Monte Carlo retirement projection using bootstrap resampling of historical returns."""
    from analysis.monte_carlo import run_monte_carlo

    n_years = args.retire_age - args.age
    if n_years <= 0:
        print("Error: retire-age debe ser mayor que age.")
        sys.exit(1)

    print("Monte Carlo - Proyeccion de Jubilacion")
    print("=" * 60)
    print(f"  Edad actual: {args.age}  |  Jubilacion: {args.retire_age}  |  Horizonte: {n_years} anos")
    print(f"  DCA mensual: {args.monthly:.0f} EUR  |  Objetivo: {args.target_eur:,.0f} EUR")
    print(f"  Simulaciones: {args.simulations:,}  |  Metodo: bootstrap resampling retornos historicos")
    print("  Activos: BTC/ETH (yfinance), SPY/SOXX/O/URA (yfinance)")
    print()
    print("  Ejecutando simulacion (puede tardar ~20-30s)...")

    result = run_monte_carlo(
        n_years=n_years,
        monthly_contribution_eur=args.monthly,
        target_eur=args.target_eur,
        n_simulations=args.simulations,
        current_portfolio_eur=0.0,
    )

    print()
    print(f"  {'Ano':>3}  {'Edad':>4}  {'P10 (EUR)':>12}  {'P25 (EUR)':>12}  {'Mediana':>12}  {'P75 (EUR)':>12}  {'P90 (EUR)':>12}")
    print(f"  {'-'*3}  {'-'*4}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")

    step = max(1, n_years // 15)
    for i, yr in enumerate(result.years):
        if yr % step != 0 and yr != n_years:
            continue
        age_at = args.age + yr
        print(
            f"  {yr:>3}  {age_at:>4}  "
            f"{result.p10[i]:>11,.0f}E  "
            f"{result.p25[i]:>11,.0f}E  "
            f"{result.p50[i]:>11,.0f}E  "
            f"{result.p75[i]:>11,.0f}E  "
            f"{result.p90[i]:>11,.0f}E"
        )

    print(f"\n{'='*60}")
    print(f"RESUMEN AL RETIRO (ano {n_years}, edad {args.retire_age})")
    print(f"{'='*60}")
    print(f"  Mediana cartera:        {result.median_at_retirement:>12,.0f} EUR")
    print(f"  Prob. alcanzar objetivo:{result.prob_reach_target * 100:>11.1f}%")
    print(f"  Retiro mensual (4%):    {result.safe_withdrawal_rate_4pct:>12,.0f} EUR/mes")
    print(f"  Datos historicos:       {result.data_start_year}-{result.data_end_year}  "
          f"({result.data_months} meses alineados)")
    print("\n  NOTA: Proyeccion basada en retornos historicos. El futuro puede diferir.")
    print("  Sin impuestos intermedios, sin inflacion ajustada.")
    print(f"  Dataset limitado a {result.data_start_year}-{result.data_end_year} "
          f"(inicio datos ETH). Incluye bull run crypto 2020-2021 y 2023-2024.")
    print(f"{'='*60}")
