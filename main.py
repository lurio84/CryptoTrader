"""CryptoTrader Bot - Entry point."""

import argparse
import sys

from cli.commands_ops import cmd_check, cmd_digest, cmd_dashboard, cmd_monitor, cmd_drift_check
from cli.commands_portfolio import cmd_portfolio
from cli.commands_analysis import cmd_rebalance, cmd_retirement_plan
from cli.commands_data import cmd_collect, cmd_update, cmd_backtest, cmd_sentiment, cmd_dca_backtest, cmd_info, STRATEGIES


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader Bot")
    subparsers = parser.add_subparsers(dest="command")

    # collect
    p_collect = subparsers.add_parser("collect", help="Download historical data")
    p_collect.add_argument("--symbols", nargs="+", help="Trading pairs (e.g. BTC/USDT ETH/USDT)")
    p_collect.add_argument("--timeframe", help="Candle timeframe (e.g. 1h, 4h)")
    p_collect.add_argument("--since", help="Start date YYYY-MM-DD")

    # update
    p_update = subparsers.add_parser("update", help="Update with latest candles")
    p_update.add_argument("--symbols", nargs="+")
    p_update.add_argument("--timeframe")

    # backtest
    p_bt = subparsers.add_parser("backtest", help="Run strategy backtest")
    p_bt.add_argument("--symbol", help="Trading pair (e.g. BTC/USDT)")
    p_bt.add_argument("--timeframe", help="Candle timeframe (e.g. 1h, 4h)")
    p_bt.add_argument("--since", help="Start date YYYY-MM-DD")
    p_bt.add_argument("--until", help="End date YYYY-MM-DD")
    p_bt.add_argument("--capital", type=float, help="Initial capital in USDT (default: 500)")
    p_bt.add_argument("--strategies", nargs="+", choices=list(STRATEGIES.keys()),
                       help="Strategies to test (default: all)")

    # sentiment
    p_sent = subparsers.add_parser("sentiment", help="Download sentiment data")
    p_sent.add_argument("--since", help="Start date YYYY-MM-DD")

    # dca-backtest
    p_dca = subparsers.add_parser("dca-backtest", help="Run DCA backtest")
    p_dca.add_argument("--symbols", nargs="+", help="Trading pairs")
    p_dca.add_argument("--timeframe", help="Candle timeframe")
    p_dca.add_argument("--since", help="Start date YYYY-MM-DD")

    # check
    p_check = subparsers.add_parser("check", help="Quick signal check")
    p_check.add_argument("--notify", action="store_true", help="Send Discord alert if signal triggered")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Run web dashboard")
    p_dash.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Run alert monitor")
    p_mon.add_argument("--interval", type=int, default=1, help="Check interval in hours (default: 1)")

    # rebalance
    p_reb = subparsers.add_parser("rebalance", help="Check if annual rebalancing is needed (all 6 assets)")
    p_reb.add_argument("--btc", type=float, required=True, help="BTC holdings in units (e.g. 0.05)")
    p_reb.add_argument("--eth", type=float, required=True, help="ETH holdings in units (e.g. 0.5)")
    p_reb.add_argument("--sp500", type=float, default=0.0, help="S&P500 ETF current value in EUR")
    p_reb.add_argument("--semis", type=float, default=0.0, help="Semiconductors ETF current value in EUR")
    p_reb.add_argument("--realty", type=float, default=0.0, help="Realty Income current value in EUR")
    p_reb.add_argument("--uranium", type=float, default=0.0, help="Uranium ETF current value in EUR")

    # portfolio
    p_port = subparsers.add_parser("portfolio", help="Personal portfolio tracker (FIFO / IRPF)")
    port_sub = p_port.add_subparsers(dest="portfolio_cmd")

    _all_assets = [
        "BTC", "ETH",
        "SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM",
        "btc", "eth",
        "sp500", "semiconductors", "realty_income", "uranium",
    ]
    _trade_sources = ["sparplan", "crash_buy", "mvrv_buy", "dca_out", "rebalance", "manual"]

    p_buy = port_sub.add_parser("add-buy", help="Register a buy trade")
    p_buy.add_argument("--asset", required=True, choices=_all_assets,
                       help="Asset: BTC, ETH, SP500, SEMICONDUCTORS, REALTY_INCOME, URANIUM")
    p_buy.add_argument("--units", type=float, required=True, help="Units bought (e.g. 0.001 for BTC, 1.5 for SPY)")
    p_buy.add_argument("--price-eur", type=float, required=True, help="Price in EUR per unit")
    p_buy.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    p_buy.add_argument("--fee-eur", type=float, default=0.0, help="Fee in EUR (default 0; use 1 for manual TR buy)")
    p_buy.add_argument("--source", default="sparplan", choices=_trade_sources, help="Origin of the trade")
    p_buy.add_argument("--notes", help="Optional comment")

    p_sell = port_sub.add_parser("add-sell", help="Register a sell trade")
    p_sell.add_argument("--asset", required=True, choices=_all_assets,
                        help="Asset: BTC, ETH, SP500, SEMICONDUCTORS, REALTY_INCOME, URANIUM")
    p_sell.add_argument("--units", type=float, required=True, help="Units sold")
    p_sell.add_argument("--price-eur", type=float, required=True, help="Price in EUR per unit")
    p_sell.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    p_sell.add_argument("--fee-eur", type=float, default=1.0, help="Fee in EUR (default 1 EUR flat in TR)")
    p_sell.add_argument("--source", default="dca_out", choices=_trade_sources)
    p_sell.add_argument("--notes", help="Optional comment")

    port_sub.add_parser("show", help="Show portfolio status with FIFO P&L and IRPF estimate")
    port_sub.add_parser("history", help="List all registered trades")
    port_sub.add_parser("export", help="Export all trades as CSV (for backup)")

    p_import = port_sub.add_parser("import", help="Import trades from CSV file (same format as 'portfolio export')")
    p_import.add_argument("file", help="Path to CSV file")
    p_import.add_argument("--dry-run", action="store_true", help="Parse and validate without inserting into DB")

    p_tax = port_sub.add_parser("tax-report", help="Informe IRPF anual de ventas realizadas")
    p_tax.add_argument("--year", type=int, default=None, help="Anno fiscal (default: anno en curso)")
    p_tax.add_argument("--csv", action="store_true", help="Output en formato CSV")

    # digest
    p_digest = subparsers.add_parser("digest", help="Send weekly digest to Discord")
    p_digest.add_argument("--notify", action="store_true", help="Actually send to Discord (default: preview only)")

    # retirement-plan
    p_ret = subparsers.add_parser("retirement-plan", help="Monte Carlo retirement projection")
    p_ret.add_argument("--age",         type=int,   default=30,         help="Edad actual (default 30)")
    p_ret.add_argument("--retire-age",  type=int,   default=65,         help="Edad de jubilacion (default 65)")
    p_ret.add_argument("--target-eur",  type=float, default=1_000_000,  help="Objetivo de cartera en EUR (default 1000000)")
    p_ret.add_argument("--monthly",     type=float, default=140.0,      help="DCA mensual en EUR (default 140)")
    p_ret.add_argument("--simulations", type=int,   default=5000,       help="Numero de simulaciones (default 5000)")
    p_ret.add_argument("--inflation",   type=float, default=0.0,        help="Tasa anual de inflacion para deflactar a EUR reales (default 0.0, ej: 0.025)")

    # drift-check
    p_drift = subparsers.add_parser("drift-check", help="Check portfolio drift vs Sparplan targets")
    p_drift.add_argument("--notify", action="store_true", help="Send Discord alert if drift >10pp")

    # info
    subparsers.add_parser("info", help="Show configuration")

    args = parser.parse_args()

    commands = {
        "collect":        cmd_collect,
        "update":         cmd_update,
        "backtest":       cmd_backtest,
        "sentiment":      cmd_sentiment,
        "dca-backtest":   cmd_dca_backtest,
        "check":          cmd_check,
        "portfolio":      cmd_portfolio,
        "digest":         cmd_digest,
        "dashboard":      cmd_dashboard,
        "monitor":        cmd_monitor,
        "rebalance":      cmd_rebalance,
        "retirement-plan":cmd_retirement_plan,
        "drift-check":    cmd_drift_check,
        "info":           cmd_info,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
