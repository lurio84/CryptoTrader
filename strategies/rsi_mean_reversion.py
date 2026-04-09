import pandas as pd
from ta.momentum import RSIIndicator

from strategies.base import BaseStrategy, Signal


class RSIMeanReversion(BaseStrategy):
    """RSI Mean Reversion strategy.

    Buy when RSI drops below oversold level (market oversold, expect bounce).
    Sell when RSI rises above overbought level (market overbought, expect drop).
    Uses volume confirmation to filter false signals.
    Best in ranging/sideways markets. Fails in strong trends.
    """

    name = "rsi_mean_reversion"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        volume_factor: float = 1.0,
    ):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.volume_factor = volume_factor  # min volume relative to average

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        rsi = RSIIndicator(close=df["close"], window=self.rsi_period)
        df["rsi"] = rsi.rsi()

        # Volume filter: only signal when volume >= factor * average
        df["volume_avg"] = df["volume"].rolling(window=20).mean()
        volume_ok = df["volume"] >= (self.volume_factor * df["volume_avg"])

        # Previous RSI for crossover detection
        df["rsi_prev"] = df["rsi"].shift(1)

        df["signal"] = Signal.HOLD

        # Buy: RSI crosses above oversold from below
        buy_mask = (df["rsi_prev"] <= self.oversold) & (df["rsi"] > self.oversold) & volume_ok
        df.loc[buy_mask, "signal"] = Signal.BUY

        # Sell: RSI crosses below overbought from above
        sell_mask = (df["rsi_prev"] >= self.overbought) & (df["rsi"] < self.overbought) & volume_ok
        df.loc[sell_mask, "signal"] = Signal.SELL

        df.drop(columns=["rsi_prev"], inplace=True)
        return df

    def get_params(self) -> dict:
        return {
            "rsi_period": self.rsi_period,
            "oversold": self.oversold,
            "overbought": self.overbought,
            "volume_factor": self.volume_factor,
        }
