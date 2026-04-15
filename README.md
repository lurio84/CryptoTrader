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
- S&P 500 crash -7% over 5 trading days → buy extra BTC + S&P 500 ETF

**DCA-out alerts (systematic profit-taking, 1 EUR fee per sale)**
- BTC >= $80k: sell 3% of BTC holdings every +$20k (cooldown 30d per level)
- ETH >= $3k: sell 3% of ETH holdings every +$1k (cooldown 30d per level)

**Annual rebalancing (manual, ~1 EUR fee)**
- Rebalance if BTC or ETH drifts >10% above target allocation
- Backtest: +209% vs +164% no-rebalance over 8 years, Calmar ratio 0.39 vs 0.23

## Key Research Findings (formal IS/OOS methodology, April 2026)

All production signals validated via IS/OOS split + Mann-Whitney U + bootstrap CI (N=10,000).
See `RESEARCH_ACTIVE.md` for full results per signal.

| Signal | Research | Edge | Notes |
|--------|----------|------|-------|
| BTC crash <=-15% 24h (buy) | Research 8 | +10.6pp delta 7d, p=0.020, N=13 | RED, MAINTAIN |
| BTC funding <-0.01% (buy) | Research 12 | +3.7pp delta 7d, p<0.001, OOS +2.5%, WR 67% | RED, validated 2026-04 |
| S&P 500 <-7% 5d (buy) | Research 6 | +6.1% at 4w, p=0.003, N=13 | RED, active |
| BTC DCA-out systematic (sell) | Research 3 + 4 | +115pp after-tax vs hold | Simulation, 1 cycle |
| ETH DCA-out systematic (sell) | Research 14 | +45% after-tax (+5.35pp CAGR) | Validated 2026-04 |
| Annual rebalancing | Research 1 | +45pp vs no-rebalance, -18pp drawdown | High, 9 cycles |

**Signals tested and discarded:** Fear & Greed Index, SMA/RSI/Bollinger, ETH/BTC MVRV as buy/sell signal (Research 7, 13), MA ratio as sell signal, RSI weekly overbought, NVT ratio, halving timing, DXY/BTC correlation, stablecoin dominance, term structure basis. Common pattern: momentum/valuation extremes in crypto predict *continuation*, not reversal. See `RESEARCH_ARCHIVE.md`.

## Simulated Plan Performance (2020-2026)

Full plan simulation with validated signals:
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

| Alert | Condition | Action | Cooldown | Research |
|-------|-----------|--------|----------|----------|
| BTC Crash | BTC drops >15% in 24h | Buy extra BTC | 6h | R8 |
| Funding Negative | BTC funding < -0.01% | Buy extra BTC | 24h | R12 |
| S&P 500 Crash | S&P500 <=-7% in 5d | Buy extra BTC + SP500 ETF | 7d | R6 |
| BTC DCA-out | BTC >= $80k (+$20k steps) | Sell 3% BTC holdings | 30d/level | R3 |
| ETH DCA-out | ETH >= $3k (+$1k steps) | Sell 3% ETH holdings | 30d/level | R14 |
| Rebalance Drift | Asset drifts >10pp from target | Rebalance portfolio | 7d | R1 |
| Dead Canary | No heartbeat in >10h | Check GitHub Actions | 6h | infra |

## Data Sources (all free, no API key needed)

| Source | Data |
|--------|------|
| CoinGecko | BTC/ETH live prices (USD + EUR) |
| OKX | BTC funding rate (live) |
| CoinMetrics | ETH + BTC MVRV ratio (informational only, see Research 13) |
| FRED | S&P 500 daily (crash detection) |
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
|-- tests/                       # 60+ tests
|-- .github/workflows/
    |-- crypto-check.yml         # Auto check every 4h
```

## Tech Stack

Python 3.12, pandas, numpy, SQLAlchemy, SQLite, FastAPI, GitHub Actions