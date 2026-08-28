"""API dependencies."""

from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.services.market_data import (
    BaseMarketDataProvider,
    IngestionService,
    get_market_data_provider,
)


from app.services.structure import StructureEngine, MultiTimeframeStructureEngine
from app.services.liquidity import LiquidityService
from app.services.indicators import IndicatorService
from app.services.news import (
    BaseNewsProvider,
    ForexFactoryProvider,
    MockNewsProvider,
    NewsFilterEngine,
    NewsIngestionService,
)


def get_provider() -> BaseMarketDataProvider:
    """Dependency for market data provider."""
    return get_market_data_provider(settings.MARKET_DATA_PROVIDER)


def get_ingestion_service(
    db: Session = Depends(get_db),
    provider: BaseMarketDataProvider = Depends(get_provider),
) -> IngestionService:
    """Dependency for ingestion service."""
    return IngestionService(provider=provider, db=db)


def get_structure_engine() -> StructureEngine:
    """Dependency for structure engine."""
    return StructureEngine(
        default_lookback=settings.SWING_LOOKBACK,
        default_tolerance_percent=settings.SR_TOLERANCE_PERCENT,
    )


def get_mtf_structure_engine(
    structure_engine: StructureEngine = Depends(get_structure_engine),
) -> MultiTimeframeStructureEngine:
    """Dependency for multi-timeframe structure engine."""
    return MultiTimeframeStructureEngine(structure_engine=structure_engine)


def get_liquidity_service(
    structure_engine: StructureEngine = Depends(get_structure_engine),
) -> LiquidityService:
    """Dependency for liquidity and advanced structure service."""
    return LiquidityService(structure_engine=structure_engine)


def get_indicator_service() -> IndicatorService:
    """Dependency for technical indicators and price action service."""
    return IndicatorService()


def get_news_provider() -> BaseNewsProvider:
    """Dependency for economic calendar news provider."""
    return ForexFactoryProvider()


def get_news_ingestion_service(
    db: Session = Depends(get_db),
    provider: BaseNewsProvider = Depends(get_news_provider),
) -> NewsIngestionService:
    """Dependency for economic news ingestion service."""
    return NewsIngestionService(provider=provider, db=db)


def get_news_filter_engine() -> NewsFilterEngine:
    """Dependency for economic news blackout filter engine."""
    return NewsFilterEngine(
        before_minutes=settings.NEWS_BLACKOUT_BEFORE_MINUTES,
        after_minutes=settings.NEWS_BLACKOUT_AFTER_MINUTES,
    )


from app.services.signals import RiskManager, SignalScoringEngine, SignalGenerator




def get_risk_manager() -> RiskManager:
    """Dependency for trade risk and position sizing manager."""
    return RiskManager()


def get_scoring_engine() -> SignalScoringEngine:
    """Dependency for deterministic signal scoring engine."""
    return SignalScoringEngine(min_score_threshold=settings.MIN_SETUP_SCORE)


def get_signal_generator(
    liquidity_service: LiquidityService = Depends(get_liquidity_service),
    mtf_engine: MultiTimeframeStructureEngine = Depends(get_mtf_structure_engine),
    indicator_service: IndicatorService = Depends(get_indicator_service),
    news_filter: NewsFilterEngine = Depends(get_news_filter_engine),
    scoring_engine: SignalScoringEngine = Depends(get_scoring_engine),
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> SignalGenerator:
    """Dependency for signal generator and market scanner service."""
    return SignalGenerator(
        liquidity_service=liquidity_service,
        mtf_engine=mtf_engine,
        indicator_service=indicator_service,
        news_filter=news_filter,
        scoring_engine=scoring_engine,
        risk_manager=risk_manager,
    )


from app.services.backtesting import BacktestEngine, ParameterOptimizer, BacktestService


def get_backtest_engine(
    signal_generator: SignalGenerator = Depends(get_signal_generator),
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> BacktestEngine:
    """Dependency for BacktestEngine."""
    return BacktestEngine(signal_generator=signal_generator, risk_manager=risk_manager)


def get_backtest_service(
    engine: BacktestEngine = Depends(get_backtest_engine),
) -> BacktestService:
    """Dependency for BacktestService."""
    return BacktestService(engine=engine)


from app.services.paper_trading import (
    VirtualAccountManager,
    PaperOrderExecutor,
    PaperPositionManager,
    PaperTradingService,
)


def get_virtual_account_manager() -> VirtualAccountManager:
    """Dependency for VirtualAccountManager."""
    return VirtualAccountManager()


def get_paper_trading_service(
    account_manager: VirtualAccountManager = Depends(get_virtual_account_manager),
    risk_manager: RiskManager = Depends(get_risk_manager),
    signal_generator: SignalGenerator = Depends(get_signal_generator),
) -> PaperTradingService:
    """Dependency for PaperTradingService."""
    order_executor = PaperOrderExecutor(
        account_manager=account_manager,
        risk_manager=risk_manager,
        signal_generator=signal_generator,
    )
    position_manager = PaperPositionManager(
        account_manager=account_manager,
        risk_manager=risk_manager,
    )
    return PaperTradingService(
        account_manager=account_manager,
        order_executor=order_executor,
        position_manager=position_manager,
    )


from app.services.telegram import (
    BaseTelegramClient,
    get_telegram_client,
    TelegramCommandHandler,
    AutomatedMarketScanner,
    TelegramBotService,
    get_shared_scanner,
)


_singleton_telegram_client: Optional[BaseTelegramClient] = None
_singleton_bot_service: Optional[TelegramBotService] = None


def get_telegram_client_dep() -> BaseTelegramClient:
    """Dependency for Telegram client."""
    global _singleton_telegram_client
    if _singleton_telegram_client is None:
        _singleton_telegram_client = get_telegram_client()
    return _singleton_telegram_client


def get_telegram_bot_service(
    telegram_client: BaseTelegramClient = Depends(get_telegram_client_dep),
    signal_generator: SignalGenerator = Depends(get_signal_generator),
    paper_service: PaperTradingService = Depends(get_paper_trading_service),
    news_filter: NewsFilterEngine = Depends(get_news_filter_engine),
    market_provider: BaseMarketDataProvider = Depends(get_provider),
    news_provider: BaseNewsProvider = Depends(get_news_provider),
) -> TelegramBotService:
    """Dependency for TelegramBotService."""
    global _singleton_bot_service
    if _singleton_bot_service is None:
        cmd_handler = TelegramCommandHandler(
            signal_generator=signal_generator,
            paper_service=paper_service,
            news_filter=news_filter,
            telegram_client=telegram_client,
        )
        scanner = get_shared_scanner()
        scanner.signal_generator = signal_generator
        scanner.paper_service = paper_service
        scanner.telegram_client = telegram_client
        scanner.market_provider = market_provider
        scanner.news_provider = news_provider
        _singleton_bot_service = TelegramBotService(
            client=telegram_client,
            command_handler=cmd_handler,
            scanner=scanner,
        )
    return _singleton_bot_service



