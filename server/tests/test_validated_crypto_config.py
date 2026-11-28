"""Regression: live crypto strategy/risk config matches the validated sweep."""

import pytest

from app.core.config import settings
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.signals.crypto_risk_engine import (
    BTC_ATR_MULTIPLIER,
    CryptoVolatilityRiskEngine,
)
from app.services.signals.risk_engine import RiskEngine
from app.services.strategies.btc_momentum_strategy import BTCMomentumStrategy
from app.services.strategies.strategy_manager import StrategyManager


def test_strategy_manager_uses_validated_btc_config():
    manager = StrategyManager()
    btc = next(s for s in manager.strategies if isinstance(s, BTCMomentumStrategy))

    assert btc._min_score_threshold == 85.0
    assert btc.adx_threshold == 25.0
    assert btc.min_volume == 1.0


def test_strategy_routing_is_per_symbol():
    manager = StrategyManager()
    btc_routes = manager.strategies_for("BTC/USD")
    xau_routes = manager.strategies_for("XAU/USD")

    assert [s.name for s in btc_routes] == ["BTC Momentum"]
    assert all(not isinstance(s, BTCMomentumStrategy) for s in xau_routes)
    assert any(s.name == "Strategy A (SMC Sniper)" for s in xau_routes)


def test_atr_multiplier_matches_final_backtest_constant():
    assert BTC_ATR_MULTIPLIER == 3.5
    assert CryptoVolatilityRiskEngine().atr_multiplier == 3.5


def test_confluence_routes_risk_engine_by_symbol():
    engine = ConfluenceEngine()
    btc_engine = engine._risk_engine_for("BTC/USD")
    xau_engine = engine._risk_engine_for("XAU/USD")

    assert isinstance(btc_engine, CryptoVolatilityRiskEngine)
    assert btc_engine.atr_multiplier == 3.5
    assert isinstance(xau_engine, RiskEngine)
    assert not isinstance(xau_engine, CryptoVolatilityRiskEngine)


@pytest.mark.asyncio
async def test_signal_btcusd_and_scan_include_both_instruments(test_db_session):
    from app.schemas.telegram import TelegramCommandRequest
    from app.services.market_data.mock_provider import MockMarketDataProvider
    from app.services.telegram.client import MockTelegramClient
    from app.services.telegram.command_handler import TelegramCommandHandler

    original = list(settings.SUPPORTED_SYMBOLS)
    settings.SUPPORTED_SYMBOLS = ["XAU/USD", "BTC/USD"]
    try:
        handler = TelegramCommandHandler(
            market_provider=MockMarketDataProvider(),
            telegram_client=MockTelegramClient(),
        )

        signal = await handler.handle_command(
            test_db_session, TelegramCommandRequest(command="/signal btcusd")
        )
        assert signal.handled_successfully is True
        text = signal.reply_text
        assert "Unsupported Pair" not in text
        assert "BTC/USD" in text
        assert "BTC Momentum" in text
        assert "Confluence Score" in text
        assert "ADX (14)" in text

        scan = await handler.handle_command(
            test_db_session, TelegramCommandRequest(command="/scan")
        )
        assert scan.handled_successfully is True
        digest = scan.reply_text
        assert "XAU/USD" in digest
        assert "BTC/USD" in digest
        assert "BTC Momentum" in digest
        assert "&gt;= 85" in digest  # HTML-escaped in Telegram HTML parse_mode
        assert "&gt;= 60" in digest
    finally:
        settings.SUPPORTED_SYMBOLS = original
