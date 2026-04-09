from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class BinanceSettings(BaseSettings):
    api_key: str = ""
    api_secret: str = ""

    model_config = SettingsConfigDict(env_prefix="BINANCE_")


class TelegramSettings(BaseSettings):
    bot_token: str = ""
    chat_id: str = ""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")


class DiscordSettings(BaseSettings):
    webhook_url: str = ""

    model_config = SettingsConfigDict(env_prefix="DISCORD_")


class RiskSettings(BaseSettings):
    max_position_pct: float = 0.05
    max_daily_drawdown_pct: float = 0.05
    max_total_drawdown_pct: float = 0.15
    max_simultaneous_trades: int = 3
    default_stop_loss_pct: float = 0.03
    min_risk_reward_ratio: float = 2.0

    model_config = SettingsConfigDict(env_prefix="")


class DCASettings(BaseSettings):
    base_amount_usdt: float = 50.0
    period_hours: int = 168  # weekly
    # Multipliers by Fear & Greed range
    multiplier_extreme_fear: float = 2.0   # F&G 0-15
    multiplier_fear: float = 1.5           # F&G 16-30
    multiplier_neutral: float = 1.0        # F&G 31-50
    multiplier_greed: float = 0.5          # F&G 51-75
    multiplier_extreme_greed: float = 0.0  # F&G 76-100
    # Funding rate adjustment
    funding_high_threshold: float = 0.0005
    funding_low_threshold: float = -0.0001
    funding_adjustment: float = 0.25

    model_config = SettingsConfigDict(env_prefix="DCA_")

    def get_multiplier(self, fear_greed: int, funding_rate: float | None = None) -> float:
        """Get DCA multiplier based on sentiment."""
        if fear_greed <= 15:
            mult = self.multiplier_extreme_fear
        elif fear_greed <= 30:
            mult = self.multiplier_fear
        elif fear_greed <= 50:
            mult = self.multiplier_neutral
        elif fear_greed <= 75:
            mult = self.multiplier_greed
        else:
            mult = self.multiplier_extreme_greed

        if funding_rate is not None and mult > 0:
            if funding_rate > self.funding_high_threshold:
                mult *= (1 - self.funding_adjustment)
            elif funding_rate < self.funding_low_threshold:
                mult *= (1 + self.funding_adjustment)

        return round(mult, 4)


class Settings(BaseSettings):
    trading_mode: str = "paper"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'cryptotrader.db'}"

    default_exchange: str = "binance"
    default_timeframe: str = "1h"
    default_symbols: list[str] = ["BTC/USDT", "ETH/USDT"]

    binance: BinanceSettings = BinanceSettings()
    telegram: TelegramSettings = TelegramSettings()
    discord: DiscordSettings = DiscordSettings()
    risk: RiskSettings = RiskSettings()
    dca: DCASettings = DCASettings()

    # Fees de Binance (tier básico)
    maker_fee_pct: float = 0.001
    taker_fee_pct: float = 0.001
    slippage_pct: float = 0.0005

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
