# CryptoTrader Advisor - Setup Guide

## Quick Start (local)

```bash
cd cryptotrader
.venv/Scripts/python main.py check    # Quick signal check
.venv/Scripts/python main.py dashboard # Web dashboard at localhost:8000
```

## Telegram Bot Setup (5 minutes)

1. Open Telegram, search for @BotFather
2. Send `/newbot`
3. Choose a name (e.g., "CryptoTrader Advisor")
4. Choose a username (e.g., "my_crypto_advisor_bot")
5. BotFather gives you a token like `123456:ABC-DEF...`
6. To get your chat ID:
   - Send any message to your new bot
   - Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   - Find `"chat":{"id":123456789}` - that number is your chat ID
7. Create `.env` file in the project root:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=123456789
   ```
8. Test: `.venv/Scripts/python main.py check --notify`

## GitHub Actions Setup (automatic alerts every 4h)

1. Push this repo to GitHub
2. Go to repo Settings > Secrets and variables > Actions
3. Add two secrets:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your chat ID
4. The workflow runs every 4 hours automatically
5. You can also trigger manually: Actions tab > "Crypto Signal Check" > Run workflow

## Daily Usage

Your Sparplans in Trade Republic run automatically. You only need to act when:

1. You get a Telegram alert, OR
2. You run `python main.py check` and see a signal

### What to do when alerts trigger:

| Alert | Action | Amount |
|-------|--------|--------|
| BTC CRASH (>15% drop) | Buy BTC manually in TR | 100-150 EUR |
| Negative Funding | Buy BTC manually in TR | 100 EUR |
| ETH MVRV < 0.8 | Buy ETH manually in TR | 100 EUR |
| ETH MVRV < 1.0 | Consider increasing ETH Sparplan | - |
| No alerts | Do nothing, Sparplan handles it | - |
