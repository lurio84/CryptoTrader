import pandas as pd

from strategies.base import BaseStrategy, Signal


class SMACrossover(BaseStrategy):
    """Simple Moving Average Crossover strategy.

    Buy when fast SMA crosses above slow SMA (golden cross).
    Sell when fast SMA crosses below slow SMA (death cross).
    Best in trending markets. Generates false signals in sideways markets.
    """

    name = "sma_crossover"

    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        if fast_period >= slow_period:
            raise ValueError(f"fast_period ({fast_period}) must be less than slow_period ({slow_period})")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sma_fast"] = df["close"].rolling(window=self.fast_period).mean()
        df["sma_slow"] = df["close"].rolling(window=self.slow_period).mean()

        # Previous values for crossover detection
        df["sma_fast_prev"] = df["sma_fast"].shift(1)
        df["sma_slow_prev"] = df["sma_slow"].shift(1)

        df["signal"] = Signal.HOLD

        # Golden cross: fast crosses above slow
        buy_mask = (df["sma_fast_prev"] <= df["sma_slow_prev"]) & (
            df["sma_fast"] > df["sma_slow"]
        )
        df.loc[buy_mask, "signal"] = Signal.BUY

        # Death cross: fast crosses below slow
        sell_mask = (df["sma_fast_prev"] >= df["sma_slow_prev"]) & (
            df["sma_fast"] < df["sma_slow"]
        )
        df.loc[sell_mask, "signal"] = Signal.SELL

        df.drop(columns=["sma_fast_prev", "sma_slow_prev"], inplace=True)
        return df

    def get_params(self) -> dict:
        return {"fast_period": self.fast_period, "slow_period": self.slow_period}
