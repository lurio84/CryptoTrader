"""Final validation: exact Trade Republic strategy simulation.

Simulates exactly what the user would do:
- Sparplan: 25EUR/week BTC + 10EUR/week ETH (0 fees)
- Manual crash buys: 150EUR extra when alert triggers (1EUR fee)
- Funding rate negative: 100EUR extra (1EUR fee)
- ETH MVRV < 0.8: 100EUR extra ETH (1EUR fee)
- Never sell
"""

import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from data.sentiment import SentimentCollector
from data.database import init_db

COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def fetch_mvrv_eth() -> pd.DataFrame:
    params = {
        "assets": "eth", "metrics": "CapMVRVCur", "frequency": "1d",
        "start_time": "2020-01-01", "page_size": 10000, "paging_from": "start",
    }
    all_data = []
    while True:
        r = requests.get(COINMETRICS_URL, params=params, timeout=30)
        data = r.json().get("data", [])
        if not data:
            break
        all_data.extend(data)
        npt = r.json().get("next_page_token")
        if not npt:
            break
        params["next_page_token"] = npt

    records = [{"timestamp": pd.Timestamp(d["time"]),
                "eth_mvrv": float(d["CapMVRVCur"]) if d.get("CapMVRVCur") else None}
               for d in all_data]
    return pd.DataFrame(records)


def simulate(since="2020-01-01"):
    """Run the exact Trade Republic strategy simulation."""
    init_db()

    # Load all data
    btc = load_backtest_data("BTC/USDT", "1h", since=since)
    btc["timestamp"] = pd.to_datetime(btc["timestamp"], utc=True)
    btc_daily = btc.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    btc_daily.columns = ["timestamp", "btc_price"]

    eth = load_backtest_data("ETH/USDT", "1h", since=since)
    eth["timestamp"] = pd.to_datetime(eth["timestamp"], utc=True)
    eth_daily = eth.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    eth_daily.columns = ["timestamp", "eth_price"]

    # Crash detection on hourly data
    btc["ret_24h"] = btc["close"].pct_change(24)
    crash_dates = set()
    last_crash = -999
    for i, row in btc.iterrows():
        if i - last_crash < 48:
            continue
        if pd.notna(row["ret_24h"]) and row["ret_24h"] <= -0.15:
            crash_dates.add(row["timestamp"].normalize())
            last_crash = i

    # Sentiment (funding rates)
    sent_collector = SentimentCollector()
    sentiment = sent_collector.load_sentiment()
    sentiment["timestamp"] = pd.to_datetime(sentiment["timestamp"], utc=True)
    sentiment["date"] = sentiment["timestamp"].dt.normalize()
    funding_neg_dates = set(
        sentiment[sentiment["funding_rate_btc"] < -0.0001]["date"]
    )

    # ETH MVRV
    print("  Fetching ETH MVRV...")
    eth_mvrv = fetch_mvrv_eth()
    eth_mvrv["date"] = eth_mvrv["timestamp"].dt.normalize()
    mvrv_low_dates = set(eth_mvrv[eth_mvrv["eth_mvrv"] < 0.8]["date"])
    # Also track MVRV < 1.0
    mvrv_under1_dates = set(eth_mvrv[eth_mvrv["eth_mvrv"] < 1.0]["date"])

    # Merge daily data
    daily = btc_daily.merge(eth_daily, on="timestamp")
    daily["date"] = daily["timestamp"].dt.normalize()

    # ── SIMULATION ──
    btc_coins = 0.0
    eth_coins = 0.0
    total_invested = 0.0
    total_fees = 0.0

    # Sparplan-only tracking
    sp_btc_coins = 0.0
    sp_eth_coins = 0.0
    sp_invested = 0.0

    buy_log = []
    equity_full = []
    equity_sparplan = []

    sparplan_day = 0  # buy every 7 days

    for i, row in daily.iterrows():
        date = row["date"]
        btc_p = row["btc_price"]
        eth_p = row["eth_price"]

        # Weekly Sparplan (every 7 days, 0 fees)
        if i % 7 == 0:
            # BTC 25 EUR
            btc_coins += 25.0 / btc_p
            sp_btc_coins += 25.0 / btc_p
            total_invested += 25.0
            sp_invested += 25.0

            # ETH 10 EUR
            eth_coins += 10.0 / eth_p
            sp_eth_coins += 10.0 / eth_p
            total_invested += 10.0
            sp_invested += 10.0

        # Crash buy BTC (manual, 1EUR fee)
        if date in crash_dates:
            amount = 150.0
            fee = 1.0
            btc_coins += (amount - fee) / btc_p
            total_invested += amount
            total_fees += fee
            buy_log.append({"date": date, "type": "BTC crash", "amount": amount,
                           "price": btc_p, "fee": fee})

        # Funding negative (manual, 1EUR fee) — only once per event, dedup weekly
        if date in funding_neg_dates and not any(
            b["date"] == date and b["type"] == "BTC funding" for b in buy_log
        ):
            # Check not too close to last funding buy
            recent = [b for b in buy_log if b["type"] == "BTC funding"
                     and (date - b["date"]).days < 7]
            if not recent:
                amount = 100.0
                fee = 1.0
                btc_coins += (amount - fee) / btc_p
                total_invested += amount
                total_fees += fee
                buy_log.append({"date": date, "type": "BTC funding", "amount": amount,
                               "price": btc_p, "fee": fee})

        # ETH MVRV < 0.8 (manual, 1EUR fee) — weekly dedup
        if date in mvrv_low_dates:
            recent = [b for b in buy_log if b["type"] == "ETH MVRV"
                     and (date - b["date"]).days < 7]
            if not recent:
                amount = 100.0
                fee = 1.0
                eth_coins += (amount - fee) / eth_p
                total_invested += amount
                total_fees += fee
                buy_log.append({"date": date, "type": "ETH MVRV", "amount": amount,
                               "price": eth_p, "fee": fee})

        # Track equity
        equity_full.append(btc_coins * btc_p + eth_coins * eth_p)
        equity_sparplan.append(sp_btc_coins * btc_p + sp_eth_coins * eth_p)

    # Final values
    last = daily.iloc[-1]
    final_btc = last["btc_price"]
    final_eth = last["eth_price"]

    full_value = btc_coins * final_btc + eth_coins * final_eth
    sp_value = sp_btc_coins * final_btc + sp_eth_coins * final_eth

    full_ret = (full_value - total_invested) / total_invested * 100
    sp_ret = (sp_value - sp_invested) / sp_invested * 100

    # Print results
    print(f"\n{'='*65}")
    print(f"  FINAL STRATEGY SIMULATION ({daily.iloc[0]['date'].date()} -> {daily.iloc[-1]['date'].date()})")
    print(f"{'='*65}")

    print(f"\n  FULL STRATEGY (Sparplan + Crash/Funding/MVRV alerts):")
    print(f"    Total Invested:   {total_invested:>10,.0f} EUR")
    print(f"    Final Value:      {full_value:>10,.0f} EUR")
    print(f"    Profit:           {full_value - total_invested:>+10,.0f} EUR")
    print(f"    Return:           {full_ret:>+10.1f}%")
    print(f"    Total Fees:       {total_fees:>10,.0f} EUR")
    print(f"    BTC held:         {btc_coins:>13.6f} BTC")
    print(f"    ETH held:         {eth_coins:>13.6f} ETH")

    print(f"\n  SPARPLAN ONLY (no alerts, no manual buys):")
    print(f"    Total Invested:   {sp_invested:>10,.0f} EUR")
    print(f"    Final Value:      {sp_value:>10,.0f} EUR")
    print(f"    Profit:           {sp_value - sp_invested:>+10,.0f} EUR")
    print(f"    Return:           {sp_ret:>+10.1f}%")

    print(f"\n  DIFFERENCE:")
    print(f"    Extra return:     {full_ret - sp_ret:>+10.1f}%")
    print(f"    Extra profit:     {(full_value - total_invested) - (sp_value - sp_invested):>+10,.0f} EUR")
    print(f"    Extra invested:   {total_invested - sp_invested:>10,.0f} EUR")

    # Alert log summary
    crash_buys = [b for b in buy_log if b["type"] == "BTC crash"]
    funding_buys = [b for b in buy_log if b["type"] == "BTC funding"]
    mvrv_buys = [b for b in buy_log if b["type"] == "ETH MVRV"]

    print(f"\n  ALERT BUYS BREAKDOWN:")
    print(f"    BTC crash buys:   {len(crash_buys):>5} (total {sum(b['amount'] for b in crash_buys):,.0f} EUR)")
    print(f"    BTC funding buys: {len(funding_buys):>5} (total {sum(b['amount'] for b in funding_buys):,.0f} EUR)")
    print(f"    ETH MVRV buys:    {len(mvrv_buys):>5} (total {sum(b['amount'] for b in mvrv_buys):,.0f} EUR)")

    # ── Yearly breakdown ──
    print(f"\n{'='*65}")
    print(f"  YEARLY BREAKDOWN")
    print(f"{'='*65}")

    eq_full = pd.Series(equity_full, index=daily["timestamp"])
    eq_sp = pd.Series(equity_sparplan, index=daily["timestamp"])

    years = eq_full.resample("YE").last()
    years_sp = eq_sp.resample("YE").last()

    print(f"\n  {'Year':<8} {'Full Value':>12} {'SP Value':>12} {'Diff':>10}")
    print(f"  {'-'*45}")
    for y in years.index:
        fv = years[y]
        sv = years_sp[y]
        print(f"  {y.year:<8} {fv:>12,.0f} {sv:>12,.0f} {fv-sv:>+10,.0f}")

    last_y = daily.iloc[-1]["timestamp"]
    print(f"  {last_y.year:<8} {equity_full[-1]:>12,.0f} {equity_sparplan[-1]:>12,.0f} "
          f"{equity_full[-1]-equity_sparplan[-1]:>+10,.0f}")


if __name__ == "__main__":
    simulate()
