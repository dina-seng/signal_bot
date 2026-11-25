"""Application configuration management using Pydantic Settings."""

from typing import Annotated, List, Optional
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
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
    PARTIAL_CLOSE_AT_TP1: bool = Field(
        default=False,
        description="Enable 50% scale-out at TP1 (legacy 2R/3R). Default: full 3R exit.",
    )
    MIN_RR_TP1: float = Field(
        default=3.0,
        ge=1.0,
        validation_alias=AliasChoices("MIN_RR_TP1", "MIN_RR"),
    )
    MIN_RR_TP2: float = Field(default=3.0, ge=1.0)
    BROKER_SPEC: str = Field(
        default="exness_standard_xauusd",
        description="Paper-trading broker lot specification profile",
    )
    MAX_LOT_SIZE: float = Field(
        default=100.0,
        ge=0.01,
        description="Upper lot bound for paper execution (config-driven, never hardcoded at call sites)",
    )
    MAX_OPEN_POSITIONS: int = Field(
        default=6,
        ge=1,
        description="Global cap on simultaneously open paper positions for auto-execution",
    )
    AUTO_EXEC_MAX_SL_POINTS: float = Field(
        default=15.0,
        gt=0,
        description="Max 15m structural SL distance (price points) eligible for auto-execution",
    )
    MAX_RISK_PERCENT: float = Field(
        default=5.0,
        ge=0.1,
        le=5.0,
        validation_alias=AliasChoices("MAX_RISK_PERCENT", "RISK_PER_ORDER_PCT"),
    )
    # Historical research/backtests keep their own default so a live paper-risk
    # change never silently mutates research signal populations.
    RESEARCH_RISK_PERCENT: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        description="Risk % used by research/backtest harnesses only",
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
    # Short TTL for live quote/candle provider ticks (single-flight cache in
    # front of the upstream provider).
    QUOTE_CACHE_TTL_SECONDS: float = Field(
        default=5.0,
        ge=0,
        description="TTL for cached quote/candle provider ticks (seconds)",
    )
    # API-layer quote *response* cache. Provider granularity is ~1 minute, so a
    # 60s response cache costs zero freshness while cutting provider credits.
    QUOTE_RESPONSE_CACHE_TTL_SECONDS: int = 60
    # With no recent dashboard heartbeat, fall back to a slow lazy refresh cadence.
    QUOTE_IDLE_CACHE_TTL_SECONDS: int = 300
    # A dashboard heartbeat younger than this counts as an active viewer.
    QUOTE_PRESENCE_TTL_SECONDS: int = 60
    # STALE when the price itself has not changed for this long during market hours.
    QUOTE_STALE_AFTER_SECONDS: int = 180
    QUOTE_MAX_DEVIATION_PCT: float = 0.05

    # API transport / dashboard aggregation (all tunables are env-driven)
    # Exact cross-origin frontend origins. Env values may be a single URL, a
    # comma-separated list, or a JSON list. Never empty: a silent empty value
    # makes CORSMiddleware reject every preflight with "no ACAO header".
    FRONTEND_ORIGIN: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: [
            "https://quanview.dinacreator.space",
            "http://localhost:3000",
        ],
        description="Allowed browser origins for credentialed CORS requests",
    )
    CORS_MAX_AGE_SECONDS: int = Field(
        default=86400,
        ge=0,
        description="Browser preflight cache lifetime for CORS (seconds)",
    )
    DASHBOARD_POLL_SECONDS: int = Field(
        default=15,
        ge=1,
        description="Main dashboard snapshot poll interval (seconds)",
    )
    DASHBOARD_CANDLE_LIMIT: int = Field(default=60, ge=1, le=500)
    DASHBOARD_DERIVED_LIMIT: int = Field(default=200, ge=20, le=2000)
    DASHBOARD_NEWS_LIMIT: int = Field(default=30, ge=1, le=500)
    DASHBOARD_SIGNALS_LIMIT: int = Field(default=25, ge=1, le=500)
    DASHBOARD_TRADE_HISTORY_LIMIT: int = Field(default=50, ge=1, le=500)

    # Provider cache + request coalescing
    PROVIDER_CACHE_ENABLED: bool = True
    DERIVED_CACHE_TTL_SECONDS: float = Field(
        default=30.0,
        ge=0,
        description="TTL for derived indicators/structure/liquidity results (seconds)",
    )
    STALE_ON_THROTTLE: bool = Field(
        default=True,
        description="Serve the last-good cached value when the upstream provider throttles",
    )
    LATENCY_SAMPLE_SIZE: int = Field(
        default=200,
        ge=10,
        description="Number of recent request latency samples kept in memory",
    )
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
    # Username used by the frontend deep link: https://t.me/<username>?start=login
    TELEGRAM_BOT_USERNAME: str = Field(
        default="signalTheBEST_bot",
        validation_alias=AliasChoices(
            "TELEGRAM_BOT_USERNAME", "NEXT_PUBLIC_TELEGRAM_BOT_USERNAME"
        ),
        description="Telegram bot username for the magic-link deep link",
    )

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

    # Milestone 2 — Telegram authentication & multi-user broadcasting
    AUTH_ENABLED: bool = True
    JWT_SECRET_KEY: str = Field(
        default="dev-only-session-secret-change-me",
        min_length=8,
        description="HS256 signing secret for dashboard session cookies",
    )
    SESSION_TTL_SECONDS: int = Field(default=7 * 24 * 3600, ge=60)
    SESSION_COOKIE_NAME: str = "quantview_session"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"
    LOGIN_LINK_TTL_SECONDS: int = Field(default=300, ge=30)
    MAGIC_LINK_BASE_URL: str = "https://quanview.dinacreator.space"
    ADMIN_TELEGRAM_ID: Optional[int] = None
    TELEGRAM_BROADCAST_DELAY_SECONDS: float = Field(default=0.5, ge=0.0)
    # Official Telegram Login Widget verification
    WIDGET_AUTH_MAX_AGE_SECONDS: int = Field(default=3600, ge=30)
    WIDGET_SESSION_TTL_SECONDS: int = Field(default=30 * 24 * 3600, ge=60)
    WIDGET_COOKIE_SECURE: bool = True
    WIDGET_COOKIE_SAMESITE: str = "none"
    DASHBOARD_REDIRECT_URL: str = "https://quanview.dinacreator.space/dashboard"

    model_config = SettingsConfigDict(
        env_file=[".env", "server/.env"],
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator(
        "SUPPORTED_SYMBOLS",
        "SUPPORTED_TIMEFRAMES",
        "SCANNER_TIMEFRAMES",
        "FRONTEND_ORIGIN",
        mode="before",
    )
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

    @field_validator("FRONTEND_ORIGIN", mode="after")
    @classmethod
    def ensure_frontend_origins(cls, value: List[str]) -> List[str]:
        cleaned = [str(item).strip().rstrip("/") for item in value if str(item).strip()]
        if not cleaned:
            return ["https://quanview.dinacreator.space", "http://localhost:3000"]
        return cleaned

    @field_validator("SUPPORTED_SYMBOLS", mode="after")
    @classmethod
    def quarantine_unsupported_symbols(cls, value: List[str]) -> List[str]:
        # Strict single-asset gold enforcement: strictly allow active symbols
        filtered = [s for s in value if s in ACTIVE_SYMBOLS]
        return filtered if filtered else list(ACTIVE_SYMBOLS)


settings = Settings()
