"""On-chain research: MVRV ratio + Exchange flows as signals for BTC and ETH."""

import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from backtesting.data_loader import load_backtest_data
from data.database import init_db

COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def fetch_onchain(asset: str, since: str = "2020-01-01") -> pd.DataFrame:
    """Fetch MVRV + exchange flows from CoinMetrics."""
    all_data = []
    params = {
        "assets": asset,
        "metrics": "CapMVRVCur,FlowInExNtv,FlowOutExNtv",
        "frequency": "1d",
        "start_time": since,
        "page_size": 10000,
        "paging_from": "start",
    }

    while True:
        r = requests.get(COINMETRICS_URL, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", [])
        if not data:
            break
        all_data.extend(data)
        next_page = body.get("next_page_token")
        if not next_page:
            break
        params["next_page_token"] = next_page

    if not all_data:
        return pd.DataFrame()

    records = []
    for d in all_data:
        records.append({
            "timestamp": pd.Timestamp(d["time"]),
            "mvrv": float(d["CapMVRVCur"]) if d.get("CapMVRVCur") else None,
            "flow_in": float(d["FlowInExNtv"]) if d.get("FlowInExNtv") else None,
            "flow_out": float(d["FlowOutExNtv"]) if d.get("FlowOutExNtv") else None,
        })

    df = pd.DataFrame(records)
    df["net_flow"] = df["flow_in"] - df["flow_out"]  # positive = inflow (bearish)
    df["net_flow_7d"] = df["net_flow"].rolling(7).sum()
    return df


def analysis_mvrv(df_candles: pd.DataFrame, df_onchain: pd.DataFrame, symbol: str):
    """MVRV as buy/sell signal."""
    print(f"\n{'='*70}")
    print(f"  1. MVRV RATIO AS SIGNAL ({symbol})")
    print(f"     MVRV < 1 = market below realized value = historically great buy")
    print(f"     MVRV > 3 = market very overvalued = historically sell zone")
    print(f"{'='*70}")

    daily = df_candles.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily["date"] = daily["timestamp"].dt.normalize()
    daily["ret_30d"] = daily["close"].pct_change(30).shift(-30) * 100
    daily["ret_90d"] = daily["close"].pct_change(90).shift(-90) * 100

    onchain = df_onchain.copy()
    onchain["date"] = onchain["timestamp"].dt.normalize()

    merged = daily.merge(onchain[["date", "mvrv"]], on="date", how="left")
    merged["mvrv"] = merged["mvrv"].ffill()
    merged = merged.dropna(subset=["mvrv", "ret_30d"])

    buckets = [
        ("MVRV < 0.8 (deep value)", merged["mvrv"] < 0.8),
        ("MVRV 0.8-1.0 (undervalued)", (merged["mvrv"] >= 0.8) & (merged["mvrv"] < 1.0)),
        ("MVRV 1.0-1.5 (fair)", (merged["mvrv"] >= 1.0) & (merged["mvrv"] < 1.5)),
        ("MVRV 1.5-2.0 (warm)", (merged["mvrv"] >= 1.5) & (merged["mvrv"] < 2.0)),
        ("MVRV 2.0-3.0 (hot)", (merged["mvrv"] >= 2.0) & (merged["mvrv"] < 3.0)),
        ("MVRV > 3.0 (overheated)", merged["mvrv"] >= 3.0),
    ]

    print(f"\n  {'MVRV Zone':<28} {'N':>5} {'30d Ret':>8} {'30d Win':>8} {'90d Ret':>8} {'90d Win':>8}")
    print(f"  {'-'*65}")

    for label, mask in buckets:
        subset = merged[mask]
        if len(subset) < 10:
            r30 = subset["ret_30d"].mean() if len(subset) > 0 else 0
            print(f"  {label:<28} {len(subset):>5} {r30:>+7.1f}%  (few)")
            continue
        r30 = subset["ret_30d"].mean()
        w30 = (subset["ret_30d"] > 0).mean() * 100
        r90 = subset["ret_90d"].dropna().mean()
        w90 = (subset["ret_90d"].dropna() > 0).mean() * 100
        print(f"  {label:<28} {len(subset):>5} {r30:>+7.1f}% {w30:>7.0f}% {r90:>+7.1f}% {w90:>7.0f}%")

    # Current MVRV
    last = df_onchain.dropna(subset=["mvrv"]).iloc[-1]
    print(f"\n  Current MVRV ({symbol}): {last['mvrv']:.2f} ({last['timestamp'].date()})")


def analysis_exchange_flows(df_candles: pd.DataFrame, df_onchain: pd.DataFrame, symbol: str):
    """Exchange net flows as signal."""
    print(f"\n{'='*70}")
    print(f"  2. EXCHANGE NET FLOWS AS SIGNAL ({symbol})")
    print(f"     Net inflow (positive) = selling pressure = bearish")
    print(f"     Net outflow (negative) = accumulation = bullish")
    print(f"{'='*70}")

    daily = df_candles.set_index("timestamp").resample("D")["close"].last().dropna().reset_index()
    daily["date"] = daily["timestamp"].dt.normalize()
    daily["ret_7d"] = daily["close"].pct_change(7).shift(-7) * 100
    daily["ret_30d"] = daily["close"].pct_change(30).shift(-30) * 100

    onchain = df_onchain.copy()
    onchain["date"] = onchain["timestamp"].dt.normalize()

    merged = daily.merge(onchain[["date", "net_flow_7d"]], on="date", how="left")
    merged["net_flow_7d"] = merged["net_flow_7d"].ffill()
    merged = merged.dropna(subset=["net_flow_7d", "ret_7d"])

    # Quintiles of 7d net flow
    merged["flow_quintile"] = pd.qcut(merged["net_flow_7d"], 5,
        labels=["Q1(outflow)", "Q2", "Q3", "Q4", "Q5(inflow)"])

    print(f"\n  {'Flow Quintile':<16} {'N':>5} {'7d Ret':>8} {'7d Win':>7} {'30d Ret':>8} {'30d Win':>8}")
    print(f"  {'-'*55}")

    for q in ["Q1(outflow)", "Q2", "Q3", "Q4", "Q5(inflow)"]:
        subset = merged[merged["flow_quintile"] == q]
        r7 = subset["ret_7d"].mean()
        w7 = (subset["ret_7d"] > 0).mean() * 100
        r30 = subset["ret_30d"].dropna().mean()
        w30 = (subset["ret_30d"].dropna() > 0).mean() * 100
        print(f"  {q:<16} {len(subset):>5} {r7:>+7.1f}% {w7:>6.0f}% {r30:>+7.1f}% {w30:>7.0f}%")


def analysis_mvrv_combined_crash(df_candles: pd.DataFrame, df_onchain: pd.DataFrame, symbol: str):
    """MVRV + crash as combined signal."""
    print(f"\n{'='*70}")
    print(f"  3. COMBINED: CRASH + MVRV ({symbol})")
    print(f"     Does buying crashes when MVRV is low produce better results?")
    print(f"{'='*70}")

    df = df_candles.copy()
    df["ret_24h"] = df["close"].pct_change(24)
    df["fwd_7d"] = df["close"].pct_change(168).shift(-168) * 100
    df["fwd_30d"] = df["close"].pct_change(720).shift(-720) * 100
    df["date"] = df["timestamp"].dt.normalize()

    onchain = df_onchain.copy()
    onchain["date"] = onchain["timestamp"].dt.normalize()
    df = df.merge(onchain[["date", "mvrv", "net_flow_7d"]], on="date", how="left")
    df["mvrv"] = df["mvrv"].ffill()
    df["net_flow_7d"] = df["net_flow_7d"].ffill()

    signals = [
        ("Crash -10% only", df["ret_24h"] <= -0.10),
        ("Crash -10% + MVRV < 1.5", (df["ret_24h"] <= -0.10) & (df["mvrv"] < 1.5)),
        ("Crash -10% + MVRV < 1.0", (df["ret_24h"] <= -0.10) & (df["mvrv"] < 1.0)),
        ("Crash -10% + outflow (7d)", (df["ret_24h"] <= -0.10) & (df["net_flow_7d"] < 0)),
        ("Crash -10% + MVRV<1.5 + outflow", (df["ret_24h"] <= -0.10) & (df["mvrv"] < 1.5) & (df["net_flow_7d"] < 0)),
        ("MVRV < 1.0 (no crash needed)", df["mvrv"] < 1.0),
        ("MVRV < 0.8 (deep value)", df["mvrv"] < 0.8),
    ]

    print(f"\n  {'Signal':<35} {'N':>5} {'7d Ret':>8} {'7d Win':>7} {'30d Ret':>8} {'30d Win':>7}")
    print(f"  {'-'*73}")

    for label, mask in signals:
        indices = df.index[mask]
        # Deduplicate for crash signals
        if "Crash" in label:
            deduped = []
            last = -100
            for idx in indices:
                if idx - last > 24:
                    deduped.append(idx)
                    last = idx
        else:
            # For MVRV-only: sample daily
            deduped = df[mask].groupby("date").first().index
            deduped = [df[df["date"] == d].index[0] for d in deduped if len(df[df["date"] == d]) > 0]

        rets_7d = [df.loc[i, "fwd_7d"] for i in deduped if pd.notna(df.loc[i, "fwd_7d"])]
        rets_30d = [df.loc[i, "fwd_30d"] for i in deduped if pd.notna(df.loc[i, "fwd_30d"])]

        n = len(deduped)
        if len(rets_7d) < 3:
            print(f"  {label:<35} {n:>5}  too few")
            continue

        r7 = np.mean(rets_7d)
        w7 = sum(1 for r in rets_7d if r > 0) / len(rets_7d) * 100
        r30 = np.mean(rets_30d) if rets_30d else 0
        w30 = (sum(1 for r in rets_30d if r > 0) / len(rets_30d) * 100) if rets_30d else 0

        print(f"  {label:<35} {n:>5} {r7:>+7.1f}% {w7:>6.0f}% {r30:>+7.1f}% {w30:>6.0f}%")


def analysis_robustness(df_candles: pd.DataFrame, df_onchain: pd.DataFrame, symbol: str):
    """In-sample vs out-of-sample for MVRV signals."""
    print(f"\n{'='*70}")
    print(f"  4. ROBUSTNESS: IN-SAMPLE (2020-2023) vs OUT-OF-SAMPLE (2024-2026)")
    print(f"     ({symbol})")
    print(f"{'='*70}")

    df = df_candles.copy()
    df["date"] = df["timestamp"].dt.normalize()
    df["ret_30d_fwd"] = df["close"].pct_change(720).shift(-720) * 100

    onchain = df_onchain.copy()
    onchain["date"] = onchain["timestamp"].dt.normalize()
    df = df.merge(onchain[["date", "mvrv"]], on="date", how="left")
    df["mvrv"] = df["mvrv"].ffill()
    df = df.dropna(subset=["mvrv", "ret_30d_fwd"])

    split = pd.Timestamp("2024-01-01", tz="UTC")
    is_df = df[df["timestamp"] < split]
    oos_df = df[df["timestamp"] >= split]

    patterns = [
        ("Buy when MVRV < 1.0", lambda d: d["mvrv"] < 1.0),
        ("Buy when MVRV < 1.5", lambda d: d["mvrv"] < 1.5),
        ("Avoid when MVRV > 2.5", lambda d: d["mvrv"] > 2.5),
        ("Avoid when MVRV > 3.0", lambda d: d["mvrv"] > 3.0),
    ]

    print(f"\n  {'Pattern':<28} {'IS 30d':>8} {'IS Win':>7} {'IS N':>5} "
          f"{'OOS 30d':>8} {'OOS Win':>8} {'OOS N':>6} {'Stable?':>8}")
    print(f"  {'-'*85}")

    for label, fn in patterns:
        is_m = fn(is_df)
        oos_m = fn(oos_df)

        # Daily sample
        is_sub = is_df[is_m].groupby("date")["ret_30d_fwd"].first()
        oos_sub = oos_df[oos_m].groupby("date")["ret_30d_fwd"].first()

        is_avg = is_sub.mean() if len(is_sub) > 0 else 0
        is_wr = (is_sub > 0).mean() * 100 if len(is_sub) > 0 else 0
        oos_avg = oos_sub.mean() if len(oos_sub) > 0 else 0
        oos_wr = (oos_sub > 0).mean() * 100 if len(oos_sub) > 0 else 0

        same_sign = (is_avg > 0) == (oos_avg > 0) if len(oos_sub) >= 5 else False
        stable = "YES" if same_sign else "NO"

        print(f"  {label:<28} {is_avg:>+7.1f}% {is_wr:>6.0f}% {len(is_sub):>5} "
              f"{oos_avg:>+7.1f}% {oos_wr:>7.0f}% {len(oos_sub):>6} {stable:>8}")


def main():
    init_db()

    for asset, symbol in [("btc", "BTC/USDT"), ("eth", "ETH/USDT")]:
        print(f"\n{'#'*70}")
        print(f"  ANALYZING {symbol} WITH ON-CHAIN DATA")
        print(f"{'#'*70}")

        print(f"\n  Fetching on-chain data for {asset}...")
        onchain = fetch_onchain(asset, since="2020-01-01")
        print(f"  {len(onchain)} days of on-chain data loaded")
        print(f"  MVRV range: {onchain['mvrv'].min():.2f} - {onchain['mvrv'].max():.2f}")
        print(f"  Latest MVRV: {onchain.iloc[-1]['mvrv']:.2f}")

        df = load_backtest_data(symbol, "1h", since="2020-01-01")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        analysis_mvrv(df, onchain, symbol)
        analysis_exchange_flows(df, onchain, symbol)
        analysis_mvrv_combined_crash(df, onchain, symbol)
        analysis_robustness(df, onchain, symbol)


if __name__ == "__main__":
    main()
