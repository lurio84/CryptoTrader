"""Final review: validate every assumption in the strategy with data."""

import numpy as np
import pandas as pd
import requests
from backtesting.data_loader import load_backtest_data
from backtesting.crash_dca_engine import CrashDCAEngine, CrashDCASettings
from backtesting.dca_engine import DCABacktestEngine
from data.sentiment import SentimentCollector
from data.database import init_db

BEST_CRASH = CrashDCASettings(
    crash_threshold_1=-0.15, crash_threshold_2=-0.20, crash_threshold_3=-0.30,
    crash_multiplier_1=5.0, crash_multiplier_2=8.0, crash_multiplier_3=10.0,
)


def fetch_eth_mvrv_history():
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {"assets": "eth", "metrics": "CapMVRVCur", "frequency": "1d",
              "start_time": "2020-01-01", "page_size": 10000, "paging_from": "start"}
    while True:
        r = requests.get(url, params=params, timeout=30)
        data = r.json().get("data", [])
        if not data:
            break
        all_data.extend(data)
        npt = r.json().get("next_page_token")
        if not npt:
            break
        params["next_page_token"] = npt
    records = [{"timestamp": pd.Timestamp(d["time"]),
                "mvrv": float(d["CapMVRVCur"]) if d.get("CapMVRVCur") else None}
               for d in all_data]
    return pd.DataFrame(records)


def main():
    init_db()

    print("=" * 70)
    print("  FINAL STRATEGY REVIEW")
    print("  Checking every assumption against real data")
    print("=" * 70)

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 1: DCA in BTC generates positive returns long-term
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  1. DOES DCA IN BTC GENERATE POSITIVE RETURNS?")
    print("=" * 70)

    btc = load_backtest_data("BTC/USDT", "1h", since="2020-01-01")
    btc["timestamp"] = pd.to_datetime(btc["timestamp"], utc=True)

    # Simulate 8 EUR/week DCA in BTC
    daily_btc = btc.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    btc_coins = 0.0
    btc_invested = 0.0
    for i, row in daily_btc.iterrows():
        if i % 7 == 0:
            btc_coins += 8.0 / row["close"]
            btc_invested += 8.0

    btc_value = btc_coins * daily_btc.iloc[-1]["close"]
    btc_ret = (btc_value - btc_invested) / btc_invested * 100
    years = len(daily_btc) / 365
    btc_annual = ((btc_value / btc_invested) ** (1/years) - 1) * 100

    print(f"\n  BTC DCA 8 EUR/week ({daily_btc.iloc[0]['timestamp'].date()} -> {daily_btc.iloc[-1]['timestamp'].date()}):")
    print(f"    Invested: {btc_invested:,.0f} EUR")
    print(f"    Value:    {btc_value:,.0f} EUR")
    print(f"    Return:   {btc_ret:+.1f}%")
    print(f"    Annualized: {btc_annual:+.1f}%")
    print(f"    VERDICT: {'CONFIRMED' if btc_ret > 0 else 'FAILED'}")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 2: DCA in ETH generates positive returns
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  2. DOES DCA IN ETH GENERATE POSITIVE RETURNS?")
    print("=" * 70)

    eth = load_backtest_data("ETH/USDT", "1h", since="2020-01-01")
    eth["timestamp"] = pd.to_datetime(eth["timestamp"], utc=True)
    daily_eth = eth.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()

    eth_coins = 0.0
    eth_invested = 0.0
    for i, row in daily_eth.iterrows():
        if i % 7 == 0:
            eth_coins += 2.0 / row["close"]
            eth_invested += 2.0

    eth_value = eth_coins * daily_eth.iloc[-1]["close"]
    eth_ret = (eth_value - eth_invested) / eth_invested * 100
    eth_annual = ((eth_value / eth_invested) ** (1/years) - 1) * 100

    print(f"\n  ETH DCA 2 EUR/week ({daily_eth.iloc[0]['timestamp'].date()} -> {daily_eth.iloc[-1]['timestamp'].date()}):")
    print(f"    Invested: {eth_invested:,.0f} EUR")
    print(f"    Value:    {eth_value:,.0f} EUR")
    print(f"    Return:   {eth_ret:+.1f}%")
    print(f"    Annualized: {eth_annual:+.1f}%")
    print(f"    VERDICT: {'CONFIRMED' if eth_ret > 0 else 'WARNING - ETH underperformed'}")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 3: Crash buying adds alpha over plain DCA
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  3. DOES CRASH BUYING ADD VALUE OVER PLAIN DCA?")
    print("=" * 70)

    engine = CrashDCAEngine(crash_settings=BEST_CRASH)

    # Test on multiple periods
    periods = [
        ("2020-01-01", "2022-12-31", "2020-2022 (bull+crash)"),
        ("2023-01-01", "2024-12-31", "2023-2024 (recovery+bull)"),
        ("2025-01-01", None, "2025-2026 (current)"),
        ("2020-01-01", None, "2020-2026 (full period)"),
    ]

    print(f"\n  {'Period':<28} {'CrashDCA':>9} {'FixedDCA':>9} {'Diff':>8} {'Crashes':>8} {'Verdict':>10}")
    print(f"  {'-'*75}")

    wins = 0
    total = 0
    for since, until, label in periods:
        df = load_backtest_data("BTC/USDT", "1h", since=since, until=until)
        result = engine.run(df, "BTC/USDT")
        diff = result.vs_fixed_pct
        verdict = "BETTER" if diff > 0 else "WORSE"
        if diff > 0:
            wins += 1
        total += 1
        print(f"  {label:<28} {result.return_pct:>+8.1f}% {result.fixed_return_pct:>+8.1f}% "
              f"{diff:>+7.1f}% {result.crash_buys:>8} {verdict:>10}")

    print(f"\n  Crash DCA beats Fixed DCA: {wins}/{total} periods")
    print(f"  VERDICT: {'CONFIRMED' if wins > total/2 else 'WEAK/FAILED'}")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 4: Funding rate negative is a buy signal
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  4. IS NEGATIVE FUNDING RATE A RELIABLE BUY SIGNAL?")
    print("=" * 70)

    sent_collector = SentimentCollector()
    sentiment = sent_collector.load_sentiment()
    sentiment["timestamp"] = pd.to_datetime(sentiment["timestamp"], utc=True)
    sentiment["date"] = sentiment["timestamp"].dt.normalize()

    daily_btc["date"] = daily_btc["timestamp"].dt.normalize()
    daily_btc["ret_7d"] = daily_btc["close"].pct_change(7).shift(-7) * 100
    daily_btc["ret_30d"] = daily_btc["close"].pct_change(30).shift(-30) * 100

    merged = daily_btc.merge(sentiment[["date", "funding_rate_btc"]], on="date", how="left")
    merged = merged.dropna(subset=["funding_rate_btc", "ret_7d"])

    neg_funding = merged[merged["funding_rate_btc"] < -0.0001]
    normal = merged[(merged["funding_rate_btc"] >= 0) & (merged["funding_rate_btc"] < 0.0003)]

    if len(neg_funding) >= 5:
        nf_7d = neg_funding["ret_7d"].mean()
        nf_30d = neg_funding["ret_30d"].dropna().mean()
        nf_wr7 = (neg_funding["ret_7d"] > 0).mean() * 100
        nf_wr30 = (neg_funding["ret_30d"].dropna() > 0).mean() * 100
        norm_7d = normal["ret_7d"].mean()
        norm_30d = normal["ret_30d"].dropna().mean()

        print(f"\n  Negative funding (<-0.01%, n={len(neg_funding)}):")
        print(f"    7d return:  {nf_7d:+.1f}% (win rate {nf_wr7:.0f}%)")
        print(f"    30d return: {nf_30d:+.1f}% (win rate {nf_wr30:.0f}%)")
        print(f"  Normal funding (n={len(normal)}):")
        print(f"    7d return:  {norm_7d:+.1f}%")
        print(f"    30d return: {norm_30d:+.1f}%")
        print(f"  Edge: {nf_30d - norm_30d:+.1f}% at 30d")
        print(f"  VERDICT: {'CONFIRMED' if nf_30d > norm_30d and nf_wr30 > 60 else 'WEAK'}")
    else:
        print(f"  Not enough negative funding data (n={len(neg_funding)})")
        print(f"  VERDICT: INSUFFICIENT DATA")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 5: ETH MVRV < 1.0 is a buy signal
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  5. IS ETH MVRV < 1.0 A RELIABLE BUY SIGNAL?")
    print("=" * 70)

    print("  Fetching ETH MVRV history...")
    mvrv_df = fetch_eth_mvrv_history()
    mvrv_df["date"] = mvrv_df["timestamp"].dt.normalize()

    daily_eth["date"] = daily_eth["timestamp"].dt.normalize()
    daily_eth["ret_30d"] = daily_eth["close"].pct_change(30).shift(-30) * 100
    daily_eth["ret_90d"] = daily_eth["close"].pct_change(90).shift(-90) * 100

    merged_eth = daily_eth.merge(mvrv_df[["date", "mvrv"]], on="date", how="left")
    merged_eth["mvrv"] = merged_eth["mvrv"].ffill()
    merged_eth = merged_eth.dropna(subset=["mvrv", "ret_30d"])

    # Split in-sample / out-of-sample
    split = pd.Timestamp("2024-01-01", tz="UTC")
    is_df = merged_eth[merged_eth["timestamp"] < split]
    oos_df = merged_eth[merged_eth["timestamp"] >= split]

    for label, df_slice in [("In-sample (2020-2023)", is_df), ("Out-of-sample (2024-2026)", oos_df)]:
        under1 = df_slice[df_slice["mvrv"] < 1.0]
        under08 = df_slice[df_slice["mvrv"] < 0.8]
        above1 = df_slice[df_slice["mvrv"] >= 1.0]

        print(f"\n  {label}:")
        if len(under1) > 10:
            print(f"    MVRV < 1.0 (n={len(under1)}): 30d ret={under1['ret_30d'].mean():+.1f}%, "
                  f"win={( under1['ret_30d'] > 0).mean()*100:.0f}%, "
                  f"90d ret={under1['ret_90d'].dropna().mean():+.1f}%")
        if len(under08) > 5:
            print(f"    MVRV < 0.8 (n={len(under08)}): 30d ret={under08['ret_30d'].mean():+.1f}%, "
                  f"win={( under08['ret_30d'] > 0).mean()*100:.0f}%, "
                  f"90d ret={under08['ret_90d'].dropna().mean():+.1f}%")
        if len(above1) > 10:
            print(f"    MVRV >= 1.0 (n={len(above1)}): 30d ret={above1['ret_30d'].mean():+.1f}%, "
                  f"win={(above1['ret_30d'] > 0).mean()*100:.0f}%")

    # Overall verdict
    all_under1 = merged_eth[merged_eth["mvrv"] < 1.0]
    all_above1 = merged_eth[merged_eth["mvrv"] >= 1.0]
    if len(all_under1) > 10:
        edge = all_under1["ret_30d"].mean() - all_above1["ret_30d"].mean()
        is_under1 = is_df[is_df["mvrv"] < 1.0]["ret_30d"].mean()
        oos_under1 = oos_df[oos_df["mvrv"] < 1.0]["ret_30d"].mean() if len(oos_df[oos_df["mvrv"] < 1.0]) > 5 else None
        consistent = oos_under1 is not None and is_under1 > 0 and oos_under1 > 0
        print(f"\n  Edge over MVRV >= 1.0: {edge:+.1f}% at 30d")
        print(f"  IS positive: {is_under1 > 0} | OOS positive: {oos_under1 is not None and oos_under1 > 0}")
        print(f"  VERDICT: {'CONFIRMED' if consistent else 'WEAK - not consistent OOS'}")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 6: NOT selling after rallies is correct
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  6. IS 'NEVER SELL' THE CORRECT APPROACH?")
    print("=" * 70)

    daily_btc_full = btc.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily_btc_full["ret_30d"] = daily_btc_full["close"].pct_change(30)
    daily_btc_full["fwd_30d"] = daily_btc_full["close"].pct_change(30).shift(-30) * 100
    daily_btc_full["fwd_90d"] = daily_btc_full["close"].pct_change(90).shift(-90) * 100

    rally_30 = daily_btc_full[daily_btc_full["ret_30d"] >= 0.30].dropna(subset=["fwd_30d"])
    rally_50 = daily_btc_full[daily_btc_full["ret_30d"] >= 0.50].dropna(subset=["fwd_30d"])

    print(f"\n  After +30% rally in 30d (n={len(rally_30)}):")
    print(f"    Next 30d: {rally_30['fwd_30d'].mean():+.1f}% (win rate {(rally_30['fwd_30d']>0).mean()*100:.0f}%)")
    if len(rally_30["fwd_90d"].dropna()) > 5:
        print(f"    Next 90d: {rally_30['fwd_90d'].dropna().mean():+.1f}% (win rate {(rally_30['fwd_90d'].dropna()>0).mean()*100:.0f}%)")

    if len(rally_50) > 3:
        print(f"  After +50% rally in 30d (n={len(rally_50)}):")
        print(f"    Next 30d: {rally_50['fwd_30d'].mean():+.1f}% (win rate {(rally_50['fwd_30d']>0).mean()*100:.0f}%)")

    sell_correct = rally_30["fwd_30d"].mean() > 0
    print(f"\n  If you sold after +30% rally, you'd miss {rally_30['fwd_30d'].mean():+.1f}% more gains")
    print(f"  VERDICT: {'CONFIRMED - holding is better' if sell_correct else 'FAILED - selling may be better'}")

    # ══════════════════════════════════════════════════════════════
    # ASSUMPTION 7: F&G Index does NOT work as buy signal
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  7. CONFIRMING F&G INDEX DOES NOT WORK")
    print("=" * 70)

    fg_merged = daily_btc.merge(sentiment[["date", "fear_greed_value"]], on="date", how="left")
    fg_merged["fear_greed_value"] = fg_merged["fear_greed_value"].ffill()
    fg_merged = fg_merged.dropna(subset=["fear_greed_value", "ret_30d"])

    extreme_fear = fg_merged[fg_merged["fear_greed_value"] <= 15]
    neutral = fg_merged[(fg_merged["fear_greed_value"] >= 35) & (fg_merged["fear_greed_value"] <= 50)]
    all_days = fg_merged

    print(f"\n  Extreme Fear F&G <= 15 (n={len(extreme_fear)}):")
    print(f"    30d return: {extreme_fear['ret_30d'].mean():+.1f}%")
    print(f"  Neutral F&G 35-50 (n={len(neutral)}):")
    print(f"    30d return: {neutral['ret_30d'].mean():+.1f}%")
    print(f"  All days baseline (n={len(all_days)}):")
    print(f"    30d return: {all_days['ret_30d'].mean():+.1f}%")

    fg_works = extreme_fear["ret_30d"].mean() > all_days["ret_30d"].mean()
    print(f"\n  Extreme Fear beats baseline: {fg_works}")
    print(f"  VERDICT: {'FAILED - we were wrong, F&G works' if fg_works else 'CONFIRMED - F&G does not add value'}")

    # ══════════════════════════════════════════════════════════════
    # OVERALL STRATEGY SCORECARD
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  STRATEGY SCORECARD")
    print("=" * 70)

    checks = [
        ("BTC DCA generates positive returns", btc_ret > 0),
        ("ETH DCA generates positive returns", eth_ret > 0),
        ("Crash buying adds value over plain DCA", wins > total / 2),
        ("Negative funding is a buy signal", len(neg_funding) >= 5 and nf_wr30 > 60),
        ("Never sell after rallies", sell_correct),
        ("F&G excluded correctly", not fg_works),
    ]

    print()
    passed = 0
    for name, result in checks:
        status = "PASS" if result else "FAIL"
        if result:
            passed += 1
        print(f"  [{status}] {name}")

    print(f"\n  Score: {passed}/{len(checks)}")

    if passed == len(checks):
        print("  ALL CHECKS PASSED - Strategy is validated")
    elif passed >= len(checks) - 1:
        print("  MOSTLY VALIDATED - One weak point, strategy is reasonable")
    else:
        print("  NEEDS REVIEW - Multiple assumptions don't hold")

    # Current signal status
    print(f"\n{'='*70}")
    print("  CURRENT MARKET STATUS (live)")
    print("=" * 70)

    last_mvrv = mvrv_df.dropna(subset=["mvrv"]).iloc[-1]
    print(f"\n  ETH MVRV: {last_mvrv['mvrv']:.3f} ({last_mvrv['timestamp'].date()})")
    if last_mvrv["mvrv"] < 0.8:
        print(f"    -> RED ALERT: Deep value zone. Strong buy signal.")
    elif last_mvrv["mvrv"] < 1.0:
        print(f"    -> YELLOW: Undervalued territory. Watch closely.")
    else:
        print(f"    -> Normal. No action needed.")


if __name__ == "__main__":
    main()
