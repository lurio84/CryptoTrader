from __future__ import annotations

from dataclasses import dataclass
import pandas as pd
import numpy as np

from config.settings import settings, DCASettings


@dataclass
class DCABacktestResult:
    """Results comparing Smart DCA vs Fixed DCA vs Buy & Hold."""

    # Smart DCA (sentiment-based)
    smart_total_invested: float
    smart_final_value: float
    smart_return_pct: float
    smart_avg_buy_price: float
    smart_total_buys: int
    smart_total_fees: float

    # Fixed DCA (same amount every period)
    fixed_total_invested: float
    fixed_final_value: float
    fixed_return_pct: float
    fixed_avg_buy_price: float

    # Buy & Hold (lump sum at start)
    bh_total_invested: float
    bh_final_value: float
    bh_return_pct: float

    # Comparison
    smart_vs_fixed_pct: float
    smart_vs_bh_pct: float

    # Series for plotting
    smart_equity: pd.Series
    fixed_equity: pd.Series
    buy_log: pd.DataFrame

    start_date: str
    end_date: str
    symbol: str

    def summary(self) -> str:
        return (
            f"{'='*55}\n"
            f"  DCA BACKTEST: {self.symbol} ({self.start_date} -> {self.end_date})\n"
            f"{'='*55}\n"
            f"\n  SMART DCA (sentiment-based):\n"
            f"    Total Invested:  {self.smart_total_invested:.2f} USDT\n"
            f"    Final Value:     {self.smart_final_value:.2f} USDT\n"
            f"    Return:          {self.smart_return_pct:+.2f}%\n"
            f"    Avg Buy Price:   {self.smart_avg_buy_price:.2f}\n"
            f"    Total Buys:      {self.smart_total_buys}\n"
            f"    Fees Paid:       {self.smart_total_fees:.2f} USDT\n"
            f"\n  FIXED DCA (same amount every week):\n"
            f"    Total Invested:  {self.fixed_total_invested:.2f} USDT\n"
            f"    Final Value:     {self.fixed_final_value:.2f} USDT\n"
            f"    Return:          {self.fixed_return_pct:+.2f}%\n"
            f"    Avg Buy Price:   {self.fixed_avg_buy_price:.2f}\n"
            f"\n  BUY & HOLD (lump sum):\n"
            f"    Total Invested:  {self.bh_total_invested:.2f} USDT\n"
            f"    Final Value:     {self.bh_final_value:.2f} USDT\n"
            f"    Return:          {self.bh_return_pct:+.2f}%\n"
            f"\n  {'-'*55}\n"
            f"  Smart DCA vs Fixed DCA:  {self.smart_vs_fixed_pct:+.2f}%\n"
            f"  Smart DCA vs Buy & Hold: {self.smart_vs_bh_pct:+.2f}%\n"
            f"{'='*55}"
        )


class DCABacktestEngine:
    """Backtests DCA strategies with sentiment data."""

    def __init__(
        self,
        dca_settings: DCASettings | None = None,
        taker_fee: float | None = None,
        slippage: float | None = None,
    ):
        self.dca = dca_settings or settings.dca
        self.taker_fee = taker_fee if taker_fee is not None else settings.taker_fee_pct
        self.slippage = slippage if slippage is not None else settings.slippage_pct

    def run(
        self,
        df_candles: pd.DataFrame,
        df_sentiment: pd.DataFrame,
        symbol: str = "BTC/USDT",
    ) -> DCABacktestResult:
        """Run DCA backtest comparing smart vs fixed vs buy & hold.

        Args:
            df_candles: OHLCV DataFrame with 'timestamp' and 'close'
            df_sentiment: Sentiment DataFrame with 'timestamp', 'fear_greed_value', 'funding_rate_btc'
            symbol: Trading pair name
        """
        # Resample candles to daily close
        df_candles = df_candles.copy()
        df_candles["timestamp"] = pd.to_datetime(df_candles["timestamp"], utc=True)
        daily = (
            df_candles.set_index("timestamp")
            .resample("D")["close"]
            .last()
            .dropna()
            .reset_index()
        )

        # Merge with sentiment (daily)
        df_sentiment = df_sentiment.copy()
        df_sentiment["timestamp"] = pd.to_datetime(df_sentiment["timestamp"], utc=True)
        df_sentiment["date"] = df_sentiment["timestamp"].dt.normalize()
        daily["date"] = daily["timestamp"].dt.normalize()

        merged = daily.merge(
            df_sentiment[["date", "fear_greed_value", "funding_rate_btc"]],
            on="date",
            how="left",
        )
        # Forward-fill sentiment for days without data
        merged["fear_greed_value"] = merged["fear_greed_value"].ffill()
        merged["funding_rate_btc"] = merged["funding_rate_btc"].ffill()
        merged = merged.dropna(subset=["fear_greed_value"]).reset_index(drop=True)

        if merged.empty:
            raise ValueError("No overlapping data between candles and sentiment")

        # DCA period in days
        period_days = self.dca.period_hours // 24
        buy_days = list(range(0, len(merged), period_days))

        # -- Smart DCA --
        smart_position = 0.0
        smart_invested = 0.0
        smart_fees = 0.0
        smart_equity_values = []
        buy_log_records = []

        # -- Fixed DCA --
        fixed_position = 0.0
        fixed_invested = 0.0

        for i, row in merged.iterrows():
            price = row["close"]

            if i in buy_days:
                fg = int(row["fear_greed_value"])
                fr = row.get("funding_rate_btc")
                fr = fr if pd.notna(fr) else None

                # Smart DCA
                multiplier = self.dca.get_multiplier(fg, fr)
                smart_amount = self.dca.base_amount_usdt * multiplier

                if smart_amount > 0:
                    exec_price = price * (1 + self.slippage)
                    fee = smart_amount * self.taker_fee
                    net = smart_amount - fee
                    bought = net / exec_price
                    smart_position += bought
                    smart_invested += smart_amount
                    smart_fees += fee

                    buy_log_records.append({
                        "date": row["date"],
                        "price": price,
                        "fear_greed": fg,
                        "funding_rate": fr,
                        "multiplier": multiplier,
                        "amount_usdt": smart_amount,
                        "bought": bought,
                    })

                # Fixed DCA (always same amount)
                fixed_amount = self.dca.base_amount_usdt
                exec_price_f = price * (1 + self.slippage)
                fee_f = fixed_amount * self.taker_fee
                net_f = fixed_amount - fee_f
                fixed_position += net_f / exec_price_f
                fixed_invested += fixed_amount

            smart_equity_values.append(smart_position * price)

        # Final values
        last_price = merged["close"].iloc[-1]
        exit_price = last_price * (1 - self.slippage)
        smart_final = smart_position * exit_price
        fixed_final = fixed_position * exit_price

        # Buy & Hold: invest same total as fixed DCA at start
        bh_invested = fixed_invested
        first_price = merged["close"].iloc[0]
        bh_position = bh_invested / (first_price * (1 + self.slippage))
        bh_final = bh_position * exit_price

        # Returns
        smart_return = ((smart_final - smart_invested) / smart_invested * 100) if smart_invested > 0 else 0
        fixed_return = ((fixed_final - fixed_invested) / fixed_invested * 100) if fixed_invested > 0 else 0
        bh_return = ((bh_final - bh_invested) / bh_invested * 100) if bh_invested > 0 else 0

        # Average buy prices
        smart_avg = (smart_invested / smart_position) if smart_position > 0 else 0
        fixed_avg = (fixed_invested / fixed_position) if fixed_position > 0 else 0

        # Comparison
        smart_vs_fixed = smart_return - fixed_return
        smart_vs_bh = smart_return - bh_return

        return DCABacktestResult(
            smart_total_invested=round(smart_invested, 2),
            smart_final_value=round(smart_final, 2),
            smart_return_pct=round(smart_return, 2),
            smart_avg_buy_price=round(smart_avg, 2),
            smart_total_buys=len(buy_log_records),
            smart_total_fees=round(smart_fees, 2),
            fixed_total_invested=round(fixed_invested, 2),
            fixed_final_value=round(fixed_final, 2),
            fixed_return_pct=round(fixed_return, 2),
            fixed_avg_buy_price=round(fixed_avg, 2),
            bh_total_invested=round(bh_invested, 2),
            bh_final_value=round(bh_final, 2),
            bh_return_pct=round(bh_return, 2),
            smart_vs_fixed_pct=round(smart_vs_fixed, 2),
            smart_vs_bh_pct=round(smart_vs_bh, 2),
            smart_equity=pd.Series(smart_equity_values),
            fixed_equity=pd.Series([fixed_position * merged["close"].iloc[j] for j in range(len(merged))]),
            buy_log=pd.DataFrame(buy_log_records),
            start_date=str(merged["date"].iloc[0].date()),
            end_date=str(merged["date"].iloc[-1].date()),
            symbol=symbol,
        )
