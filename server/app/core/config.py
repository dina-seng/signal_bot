"""Application configuration management using Pydantic Settings."""

from typing import List, Optional
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json

# Centralized single source of truth for active traded instruments
ACTIVE_SYMBOLS: List[str] = ["XAU/USD"]


class Settings(BaseSettings):
    """Central configuration for the Forex Market Analysis & Signal Bot."""

    # Project metadata
    PROJECT_NAME: str = "Forex Market Analysis & Telegram Signal Bot"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite:///./trade.db"

    # Market Instruments and Timeframes (Strict Single-Asset: ACTIVE_SYMBOLS)
    SUPPORTED_SYMBOLS: List[str] = list(ACTIVE_SYMBOLS)
    SUPPORTED_TIMEFRAMES: List[str] = ["15m", "1h", "4h"]

    # Market Structure & Analysis Strategy Config (Milestones 2-6)
    SWING_LOOKBACK: int = Field(default=2, ge=1, description="Candle lookback for swing high/low")
    SR_TOLERANCE_PERCENT: float = Field(default=0.1, ge=0.01, description="Support/Resistance grouping tolerance %")
    EMA_FAST: int = 20
    EMA_MID: int = 50
    EMA_SLOW: int = 200
    RSI_PERIOD: int = 14
    ATR_PERIOD: int = 14

    # Scoring & Risk Parameters
    MIN_SETUP_SCORE: float = Field(
        # Aligned with the canonical Baseline v2 strategy floor (60.0).
        default=60.0,
        ge=0.0,
        le=100.0,
        validation_alias=AliasChoices("MIN_SETUP_SCORE", "MIN_CONFLUENCE_SCORE"),
    )
    MIN_RR: float = Field(
        default=2.0,
        ge=1.0,
        validation_alias=AliasChoices("MIN_RR", "MIN_RR_TP1"),
    )
    MIN_RR_TP1: float = Field(
        default=2.0,
        ge=1.0,
        validation_alias=AliasChoices("MIN_RR_TP1", "MIN_RR"),
    )
    MIN_RR_TP2: float = Field(default=3.0, ge=1.0)
    MAX_RISK_PERCENT: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        validation_alias=AliasChoices("MAX_RISK_PERCENT", "RISK_PER_ORDER_PCT"),
    )

    # Backtesting & Execution Friction (USD per ounce for XAU/USD)
    XAUUSD_SPREAD: float = Field(
        default=0.30,
        ge=0.0,
        description="Execution spread in USD for XAU/USD",
        validation_alias=AliasChoices("XAUUSD_SPREAD", "BACKTEST_SPREAD_USD"),
    )
    XAUUSD_SLIPPAGE: float = Field(
        default=0.10,
        ge=0.0,
        description="Execution slippage in USD for XAU/USD",
        validation_alias=AliasChoices("XAUUSD_SLIPPAGE", "BACKTEST_SLIPPAGE_USD"),
    )

    # Fundamental & News Blackout (Milestone 5)
    NEWS_BLACKOUT_BEFORE_MINUTES: int = Field(
        default=30,
        validation_alias=AliasChoices("NEWS_BLACKOUT_BEFORE_MINUTES", "NEWS_BUFFER_PRE_MIN"),
    )
    NEWS_BLACKOUT_AFTER_MINUTES: int = Field(
        default=15,
        validation_alias=AliasChoices("NEWS_BLACKOUT_AFTER_MINUTES", "NEWS_BUFFER_POST_MIN"),
    )

    # Providers & External APIs
    MARKET_DATA_PROVIDER: str = "twelvedata"
    NEWS_PROVIDER: str = "forexfactory"
    MODE: str = Field(
        default="paper",
        validation_alias=AliasChoices("MODE", "APP_MODE"),
    )
    QUOTE_POLL_SECONDS: int = 15
    # Deprecated: provider labels are minute-rounded, so this can never trip. Kept for
    # config compatibility only; staleness is now derived from last_price_change_at.
    QUOTE_MAX_AGE_SECONDS: int = 120
    # Provider granularity is ~1 minute, so a 60s cache costs zero freshness while
    # cutting provider credits ~6x versus the old 3s cache.
    QUOTE_CACHE_TTL_SECONDS: int = 60
    # With no recent dashboard heartbeat, fall back to a slow lazy refresh cadence.
    QUOTE_IDLE_CACHE_TTL_SECONDS: int = 300
    # A dashboard heartbeat younger than this counts as an active viewer.
    QUOTE_PRESENCE_TTL_SECONDS: int = 60
    # STALE when the price itself has not changed for this long during market hours.
    QUOTE_STALE_AFTER_SECONDS: int = 180
    QUOTE_MAX_DEVIATION_PCT: float = 0.05
    YAHOO_GOLD_SYMBOL: str = "XAUUSD=X"
    TWELVE_DATA_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("TWELVE_DATA_API_KEY", "TWELVEDATA_API_KEY"),
    )
    ALPHA_VANTAGE_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None

    @property
    def TWELVEDATA_API_KEY(self) -> Optional[str]:
        """Backwards compatibility alias for TWELVE_DATA_API_KEY."""
        return self.TWELVE_DATA_API_KEY

    # Telegram Bot (Milestone 9)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None

    # User / Presentation Timezone
    # IANA timezone string for formatting Telegram notifications and display (e.g., "Asia/Bangkok", "America/New_York", "Europe/London", "UTC")
    USER_TIMEZONE: str = "UTC"

    # Automated Background Scanner & Signal Dispatching (Milestone 9)
    SCANNER_ENABLED: bool = True
    SCANNER_INTERVAL_MINUTES: int = 15
    SCANNER_TIMEFRAMES: List[str] = ["1h", "15m"]
    SCANNER_AUTO_TRADE_PAPER: bool = True
    SIGNAL_COOLDOWN_HOURS: int = Field(
        default=2,
        ge=0,
        description="Cooldown window in hours to suppress duplicate signals",
        validation_alias=AliasChoices("SIGNAL_COOLDOWN_HOURS", "DUPLICATE_COOLDOWN_HOURS"),
    )

    # Paper Trading mode
    PAPER_TRADING: bool = True

    model_config = SettingsConfigDict(
        env_file=[".env", "server/.env"],
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("SUPPORTED_SYMBOLS", "SUPPORTED_TIMEFRAMES", "SCANNER_TIMEFRAMES", mode="before")
    @classmethod
    def parse_list_from_str(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("SUPPORTED_SYMBOLS", mode="after")
    @classmethod
    def quarantine_unsupported_symbols(cls, value: List[str]) -> List[str]:
        # Strict single-asset gold enforcement: strictly allow active symbols
        filtered = [s for s in value if s in ACTIVE_SYMBOLS]
        return filtered if filtered else list(ACTIVE_SYMBOLS)


settings = Settings()
