"""Crash DCA Engine - DCA that invests extra after significant price drops.

Based on research findings:
- Buying after -15% crashes gives +7.6% avg rebound (85% win rate BTC)
- Buying after -10% crashes gives +2.3% avg rebound (77% win rate BTC)
- F&G index does NOT predict well - removed as signal
- Base DCA weekly as foundation
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from config.settings import settings


@dataclass
class CrashDCASettings:
    base_amount_usdt: float = 50.0
    period_hours: int = 168  # weekly

    # Crash detection (rolling 24h return)
    crash_threshold_1: float = -0.10  # -10% in 24h
    crash_threshold_2: float = -0.15  # -15% in 24h
    crash_threshold_3: float = -0.20  # -20% in 24h

    # Extra investment on crash (multiplier of base_amount)
    crash_multiplier_1: float = 2.0   # invest 2x extra on -10%
    crash_multiplier_2: float = 4.0   # invest 4x extra on -15%
    crash_multiplier_3: float = 6.0   # invest 6x extra on -20%

    # Cooldown: don't trigger crash buy again within N hours
    crash_cooldown_hours: int = 48


@dataclass
class CrashDCAResult:
    # Strategy results
    total_invested: float
    final_value: float
    return_pct: float
    avg_buy_price: float
    total_buys: int
    dca_buys: int
    crash_buys: int
    crash_invested: float
    total_fees: float

    # Fixed DCA comparison
    fixed_invested: float
    fixed_final_value: float
    fixed_return_pct: float
    fixed_avg_buy_price: float

    # Buy & Hold comparison
    bh_invested: float
    bh_final_value: float
    bh_return_pct: float

    # Deltas
    vs_fixed_pct: float
    vs_bh_pct: float

    # Data
    equity_curve: pd.Series
    buy_log: pd.DataFrame
    symbol: str
    start_date: str
    end_date: str

    def summary(self) -> str:
        return (
            f"{'='*58}\n"
            f"  CRASH DCA: {self.symbol} ({self.start_date} -> {self.end_date})\n"
            f"{'='*58}\n"
            f"\n  CRASH DCA STRATEGY:\n"
            f"    Total Invested:  {self.total_invested:,.2f} USDT\n"
            f"    Final Value:     {self.final_value:,.2f} USDT\n"
            f"    Return:          {self.return_pct:+.2f}%\n"
            f"    Avg Buy Price:   {self.avg_buy_price:,.2f}\n"
            f"    Regular DCA buys:{self.dca_buys:>5}\n"
            f"    Crash buys:      {self.crash_buys:>5} ({self.crash_invested:,.0f} USDT extra)\n"
            f"    Fees Paid:       {self.total_fees:.2f} USDT\n"
            f"\n  FIXED DCA:\n"
            f"    Total Invested:  {self.fixed_invested:,.2f} USDT\n"
            f"    Final Value:     {self.fixed_final_value:,.2f} USDT\n"
            f"    Return:          {self.fixed_return_pct:+.2f}%\n"
            f"\n  BUY & HOLD:\n"
            f"    Total Invested:  {self.bh_invested:,.2f} USDT\n"
            f"    Final Value:     {self.bh_final_value:,.2f} USDT\n"
            f"    Return:          {self.bh_return_pct:+.2f}%\n"
            f"\n  {'-'*58}\n"
            f"  Crash DCA vs Fixed DCA:  {self.vs_fixed_pct:+.2f}%\n"
            f"  Crash DCA vs Buy & Hold: {self.vs_bh_pct:+.2f}%\n"
            f"{'='*58}"
        )


class CrashDCAEngine:
    """Backtests crash-based DCA strategy."""

    def __init__(
        self,
        crash_settings: CrashDCASettings | None = None,
        taker_fee: float | None = None,
        slippage: float | None = None,
    ):
        self.s = crash_settings or CrashDCASettings()
        self.taker_fee = taker_fee if taker_fee is not None else settings.taker_fee_pct
        self.slippage = slippage if slippage is not None else settings.slippage_pct

    def _execute_buy(self, amount_usdt: float, price: float) -> tuple[float, float]:
        """Execute a buy, returns (coins_bought, fee)."""
        exec_price = price * (1 + self.slippage)
        fee = amount_usdt * self.taker_fee
        net = amount_usdt - fee
        coins = net / exec_price
        return coins, fee

    def run(self, df_candles: pd.DataFrame, symbol: str = "BTC/USDT") -> CrashDCAResult:
        df = df_candles.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # Daily OHLC
        daily = df.set_index("timestamp").resample("D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna().reset_index()

        # 24h rolling return (on hourly data for crash detection)
        df["ret_24h"] = df["close"].pct_change(24)

        # Identify crash events on hourly data, then map to daily
        crash_events = []
        last_crash_idx = -999
        for i, row in df.iterrows():
            if i - last_crash_idx < self.s.crash_cooldown_hours:
                continue
            ret = row["ret_24h"]
            if pd.isna(ret):
                continue
            if ret <= self.s.crash_threshold_3:
                crash_events.append((row["timestamp"], self.s.crash_multiplier_3, ret))
                last_crash_idx = i
            elif ret <= self.s.crash_threshold_2:
                crash_events.append((row["timestamp"], self.s.crash_multiplier_2, ret))
                last_crash_idx = i
            elif ret <= self.s.crash_threshold_1:
                crash_events.append((row["timestamp"], self.s.crash_multiplier_1, ret))
                last_crash_idx = i

        # Map crash events to dates
        crash_dates = {}
        for ts, mult, ret in crash_events:
            date = ts.normalize()
            if date not in crash_dates or mult > crash_dates[date][0]:
                crash_dates[date] = (mult, ret)

        # DCA buy dates (weekly)
        period_days = self.s.period_hours // 24
        dca_days = set(daily.index[::period_days])

        # ── Run simulation ──
        position = 0.0
        invested = 0.0
        fees = 0.0
        dca_buys = 0
        crash_buys_count = 0
        crash_invested = 0.0
        buy_log = []

        # Fixed DCA tracking
        fixed_position = 0.0
        fixed_invested = 0.0

        equity_values = []

        for i, row in daily.iterrows():
            price = row["close"]
            date = row["timestamp"].normalize()

            # Regular DCA buy
            if i in dca_days:
                coins, fee = self._execute_buy(self.s.base_amount_usdt, price)
                position += coins
                invested += self.s.base_amount_usdt
                fees += fee
                dca_buys += 1

                buy_log.append({
                    "date": date, "price": price, "type": "dca",
                    "amount_usdt": self.s.base_amount_usdt, "coins": coins,
                    "multiplier": 1.0, "crash_ret": None,
                })

                # Fixed DCA always buys
                f_coins, _ = self._execute_buy(self.s.base_amount_usdt, price)
                fixed_position += f_coins
                fixed_invested += self.s.base_amount_usdt

            # Crash buy (additional to DCA)
            if date in crash_dates:
                mult, crash_ret = crash_dates[date]
                extra = self.s.base_amount_usdt * mult
                coins, fee = self._execute_buy(extra, price)
                position += coins
                invested += extra
                fees += fee
                crash_buys_count += 1
                crash_invested += extra

                buy_log.append({
                    "date": date, "price": price, "type": "crash",
                    "amount_usdt": extra, "coins": coins,
                    "multiplier": mult, "crash_ret": crash_ret,
                })

            equity_values.append(position * price)

        # Final values
        last_price = daily["close"].iloc[-1]
        final_value = position * last_price
        fixed_final = fixed_position * last_price

        # Buy & Hold
        bh_invested = fixed_invested
        first_price = daily["close"].iloc[0]
        bh_coins, _ = self._execute_buy(bh_invested, first_price)
        bh_final = bh_coins * last_price

        # Returns
        ret = ((final_value - invested) / invested * 100) if invested > 0 else 0
        fixed_ret = ((fixed_final - fixed_invested) / fixed_invested * 100) if fixed_invested > 0 else 0
        bh_ret = ((bh_final - bh_invested) / bh_invested * 100) if bh_invested > 0 else 0

        avg_price = (invested / position) if position > 0 else 0
        fixed_avg = (fixed_invested / fixed_position) if fixed_position > 0 else 0

        return CrashDCAResult(
            total_invested=round(invested, 2),
            final_value=round(final_value, 2),
            return_pct=round(ret, 2),
            avg_buy_price=round(avg_price, 2),
            total_buys=dca_buys + crash_buys_count,
            dca_buys=dca_buys,
            crash_buys=crash_buys_count,
            crash_invested=round(crash_invested, 2),
            total_fees=round(fees, 2),
            fixed_invested=round(fixed_invested, 2),
            fixed_final_value=round(fixed_final, 2),
            fixed_return_pct=round(fixed_ret, 2),
            fixed_avg_buy_price=round(fixed_avg, 2),
            bh_invested=round(bh_invested, 2),
            bh_final_value=round(bh_final, 2),
            bh_return_pct=round(bh_ret, 2),
            vs_fixed_pct=round(ret - fixed_ret, 2),
            vs_bh_pct=round(ret - bh_ret, 2),
            equity_curve=pd.Series(equity_values),
            buy_log=pd.DataFrame(buy_log),
            symbol=symbol,
            start_date=str(daily["timestamp"].iloc[0].date()),
            end_date=str(daily["timestamp"].iloc[-1].date()),
        )
