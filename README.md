# CryptoTrader Advisor

Personal investment advisor that monitors BTC and ETH signals and sends Discord alerts when action is needed. Built on statistical analysis of 6+ years of real market data.

## Strategy (validated with data 2020-2026)

**Base: Weekly Sparplans in Trade Republic (automatic, 0 EUR fees)**
- BTC: 8 EUR/week
- ETH: 2 EUR/week (+ staking enabled)
- S&P 500 + other stocks: 25 EUR/week (existing portfolio)
- Total: 140 EUR/month

**Alerts: Manual extra buys when signals trigger (1 EUR fee, 2-5 times/year)**
- BTC crash >15% in 24h -> buy extra 100-150 EUR BTC
- BTC funding rate very negative (<-0.01%) -> buy extra 100 EUR BTC
- ETH MVRV < 0.8 -> buy extra 100 EUR ETH

**Key findings from research:**
- DCA in BTC: +16.5% annualized (2020-2026)
- DCA in ETH: +14.2% annualized (2020-2026)
- Crash buying adds +10-43% over plain DCA when crashes occur
- Negative funding rate: +23% avg return at 30d, 88% win rate
- ETH MVRV < 0.8: +34% avg return at 30d, 89% win rate
- Fear & Greed Index does NOT predict well (excluded from strategy)
- Selling after rallies is a BAD idea (momentum continues)

## Quick Start

```bash
# Install (requires Python 3.12)
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[all]"

# Quick signal check
.venv/Scripts/python main.py check

# Web dashboard (instant load, auto-refreshes every 60s)
.venv/Scripts/python main.py dashboard

# Check + send Discord notification
.venv/Scripts/python main.py check --notify
```

## Commands

| Command | Description |
|---------|-------------|
| `check` | Quick signal check - shows current status and alerts |
| `check --notify` | Same + sends Discord alert if signal triggered |
| `dashboard` | Web dashboard at localhost:8000 |
| `monitor` | Background monitor (checks every hour) |
| `collect --symbols BTC/USDT --since 2020-01-01` | Download historical price data |
| `sentiment --since 2020-01-01` | Download Fear & Greed + funding rate data |
| `backtest --symbol BTC/USDT --strategies sma rsi bollinger` | Run strategy backtests |
| `dca-backtest --symbols BTC/USDT ETH/USDT` | Run DCA backtest |
| `info` | Show configuration |

## Setup Discord Alerts

1. Create a channel in your Discord server (e.g. #crypto-alerts)
2. Channel Settings > Integrations > Webhooks > New Webhook
3. Copy the webhook URL
4. Create `.env` in project root:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
   ```

## GitHub Actions (automatic alerts every 4h)

The workflow at `.github/workflows/crypto-check.yml` runs every 4 hours automatically — no local machine needed.

Setup:
1. Push this repo to GitHub
2. Go to Settings > Secrets and variables > Actions
3. Add secret: `DISCORD_WEBHOOK_URL` (your webhook URL)
4. The workflow runs automatically on schedule

## Data Sources (all free, no API key needed)

| Source | Data |
|--------|------|
| CoinGecko | BTC/ETH prices and 24h change |
| OKX | BTC funding rate (live) |
| CoinMetrics | ETH MVRV ratio |
| alternative.me | Fear & Greed Index |

## Project Structure

```
cryptotrader/
|
|-- main.py                      # CLI entry point (all commands)
|-- .env.example                 # Environment variables template
|-- pyproject.toml               # Dependencies and project config
|
|-- config/
|   |-- settings.py              # All configuration (Pydantic)
|
|-- data/
|   |-- collector.py             # OHLCV price data (Binance via ccxt)
|   |-- sentiment.py             # Fear & Greed Index + funding rates
|   |-- models.py                # SQLAlchemy models
|   |-- database.py              # SQLite connection + sessions
|
|-- alerts/
|   |-- discord_bot.py           # Discord alerts + signal checking logic
|   |-- monitor.py               # APScheduler background monitor
|
|-- dashboard/
|   |-- app.py                   # FastAPI web dashboard
|   |-- templates/index.html     # Dashboard UI (dark theme, auto-refresh)
|
|-- strategies/                  # SMA/RSI/Bollinger (tested, not used in prod)
|-- backtesting/                 # Backtest engines and metrics
|-- tests/                       # 41 tests
|
|-- .github/workflows/
    |-- crypto-check.yml         # Auto check every 4h + Discord alert
```

## Research Summary

9 analyses on 6 years of data (2020-2026):

1. **Crash buying (-15% drops)**: +9.3% avg rebound at 7d, 77% win rate (BTC)
2. **Negative funding rate**: +23% at 30d, 88% win rate - strongest signal
3. **ETH MVRV < 0.8**: +34% at 30d, 89% win rate - survives out-of-sample
4. **Momentum continues**: after +30% rally, next 30d still +10.8% (don't sell)
5. **F&G Index fails**: extreme fear gives WORSE returns than baseline
6. **Technical indicators (SMA/RSI/BB)**: none beat buy & hold consistently

## Tech Stack

Python 3.12, ccxt, pandas, numpy, ta, SQLAlchemy, SQLite, FastAPI, Jinja2, APScheduler, pydantic-settings, GitHub Actions
