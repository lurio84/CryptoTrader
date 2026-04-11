# CryptoTrader Advisor

Personal investment advisor that monitors BTC and ETH signals and sends Discord alerts when action is needed. Built on statistical analysis of 6+ years of real market data (2018-2026).

## Strategy (validated with real data 2018-2026)

**Base: Weekly Sparplans in Trade Republic (automatic, 0 EUR fees)**
- BTC: 8 EUR/week
- ETH: 2 EUR/week (+ staking enabled)
- S&P 500 + other ETFs: 25 EUR/week
- Total: ~140 EUR/month

**Extra buy alerts (0 EUR fees via Sparplan boost, 2-5 times/year)**
- BTC crash >15% in 24h → buy extra BTC (what you can afford)
- BTC funding rate very negative (<-0.01%) → buy extra BTC
- ETH MVRV < 0.8 → increase ETH Sparplan for next execution, then reset

**DCA-out alerts (systematic profit-taking, 1 EUR fee per sale)**
- BTC >= $80k: sell 3% of BTC holdings every +$20k (cooldown 30d per level)
- ETH >= $3k: sell 3% of ETH holdings every +$1k (cooldown 30d per level)

**Annual rebalancing (manual, ~1 EUR fee)**
- Rebalance if BTC or ETH drifts >10% above target allocation
- Backtest: +209% vs +164% no-rebalance over 8 years, Calmar ratio 0.39 vs 0.23

## Key Research Findings (re-validated April 2026)

| Signal | Return | Win Rate | Confidence |
|--------|--------|----------|------------|
| ETH MVRV < 0.8 (buy) | +10.1% at 30d vs +4.2% baseline | 61% | Medium-High |
| ETH MVRV 0.8-1.0 (buy) | +6.3% at 30d vs +4.2% baseline | 54% | Medium |
| BTC crash >15% (buy) | +10.6% at 7d vs +0.8% baseline | 50% | Low (N=4) |
| BTC funding <-0.01% (buy) | +23% at 30d, 88% win rate | Medium | (no free historical data) |
| DCA-out systematic (sell) | +115pp after-tax vs hold | Medium | (in-sample, 1 cycle) |
| Annual rebalancing | +45pp vs no-rebalance, -18pp drawdown | High | (N=9 cycles) |

**Signals tested and discarded:** Fear & Greed Index, SMA/RSI/Bollinger, ETH/BTC MVRV as sell signal, MA ratio as sell signal, RSI weekly overbought, NVT ratio, halving timing. Common pattern: overbought metrics in crypto predict *continuation*, not reversal.

## Simulated Plan Performance (2020-2026)

Full plan simulation with all signals and 7-day MVRV cooldown:
- Invested: **6,120 EUR** | Portfolio: **33,328 EUR** | Return: **+445%** | CAGR: ~31%/yr
- Sparplan only (no alerts): 3,270 EUR → 7,917 EUR (+142%)

## Quick Start

```bash
# Install (requires Python 3.12)
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[all]"

# Quick signal check
.venv/Scripts/python main.py check

# Check + send Discord notification
.venv/Scripts/python main.py check --notify

# Web dashboard at localhost:8000
.venv/Scripts/python main.py dashboard

# Annual rebalance calculator
.venv/Scripts/python main.py rebalance --btc X --eth X --other X
```

## GitHub Actions (automatic alerts every 4h)

The workflow at `.github/workflows/crypto-check.yml` runs at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC — no local machine needed. Alert deduplication DB is cached between runs.

Setup:
1. Push this repo to GitHub
2. Go to Settings > Secrets and variables > Actions
3. Add secret: `DISCORD_WEBHOOK_URL` (your Discord webhook URL)

## Active Alerts

| Alert | Condition | Action | Cooldown |
|-------|-----------|--------|----------|
| BTC Crash | BTC drops >15% in 24h | Buy extra BTC | 6h |
| Funding Negative | BTC funding < -0.01% | Buy extra BTC | 24h |
| ETH MVRV Critical | ETH MVRV < 0.8 | Increase ETH Sparplan | 7d |
| ETH MVRV Low | ETH MVRV 0.8-1.0 | Consider increasing ETH Sparplan | 7d |
| BTC DCA-out | BTC >= $80k (+$20k steps) | Sell 3% BTC holdings | 30d/level |
| ETH DCA-out | ETH >= $3k (+$1k steps) | Sell 3% ETH holdings | 30d/level |

## Data Sources (all free, no API key needed)

| Source | Data |
|--------|------|
| CoinGecko | BTC/ETH live prices (USD + EUR) |
| OKX | BTC funding rate (live) |
| CoinMetrics | ETH MVRV ratio |
| alternative.me | Fear & Greed Index |

## Project Structure

```
|-- main.py                      # CLI entry point
|-- config/settings.py           # Configuration (Pydantic)
|-- alerts/
|   |-- discord_bot.py           # Signal logic + Discord alerts
|   |-- monitor.py               # Background scheduler
|-- data/                        # Data models, DB, collectors
|-- dashboard/                   # FastAPI web dashboard
|-- backtesting/                 # Research scripts (8 analyses, 2018-2026)
|-- tests/                       # 41 tests
|-- .github/workflows/
    |-- crypto-check.yml         # Auto check every 4h
```

## Tech Stack

Python 3.12, pandas, numpy, SQLAlchemy, SQLite, FastAPI, GitHub Actions