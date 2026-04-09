import pandas as pd
from ta.volatility import BollingerBands

from strategies.base import BaseStrategy, Signal


class BollingerBreakout(BaseStrategy):
    """Bollinger Bands + Volume strategy.

    Buy when price touches lower band with decreasing volume (seller exhaustion).
    Sell when price touches upper band with decreasing volume (buyer exhaustion).
    Best in markets with defined volatility. Fails on strong breakouts.
    """

    name = "bollinger_breakout"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        volume_decline_periods: int = 3,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.volume_decline_periods = volume_decline_periods

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        bb = BollingerBands(
            close=df["close"], window=self.bb_period, window_dev=self.bb_std
        )
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_width"] = bb.bollinger_wband()

        # Volume trend: check if volume has been declining
        df["volume_avg_short"] = df["volume"].rolling(window=self.volume_decline_periods).mean()
        df["volume_avg_long"] = df["volume"].rolling(window=self.bb_period).mean()
        volume_declining = df["volume_avg_short"] < df["volume_avg_long"]

        df["signal"] = Signal.HOLD

        # Buy: price at or below lower band + declining volume (seller exhaustion)
        buy_mask = (df["close"] <= df["bb_lower"]) & volume_declining
        df.loc[buy_mask, "signal"] = Signal.BUY

        # Sell: price at or above upper band + declining volume (buyer exhaustion)
        sell_mask = (df["close"] >= df["bb_upper"]) & volume_declining
        df.loc[sell_mask, "signal"] = Signal.SELL

        return df

    def get_params(self) -> dict:
        return {
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "volume_decline_periods": self.volume_decline_periods,
        }
