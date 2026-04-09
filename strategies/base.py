from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    signal: Signal
    price: float
    timestamp: pd.Timestamp
    strategy: str
    confidence: float = 1.0  # 0-1, used for position sizing
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    name: str = "base"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add signal column to DataFrame.

        Must add a 'signal' column with Signal enum values.
        Can also add indicator columns used for the strategy.

        Args:
            df: DataFrame with OHLCV columns (open, high, low, close, volume, timestamp)

        Returns:
            DataFrame with added 'signal' and indicator columns.
        """
        ...

    def get_params(self) -> dict:
        """Return strategy parameters for logging/display."""
        return {}
