"""Signal Generation and Orchestration Service."""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.candle import CandleBase
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import (
    MarketScanResponse,
    MarketScanSymbolResult,
    RiskParameters,
    ScoreBreakdown,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.services.indicators import IndicatorService
from app.services.liquidity import LiquidityService
from app.services.news import NewsFilterEngine
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.signals.risk_manager import RiskManager
from app.services.signals.scoring_engine import SignalScoringEngine
from app.services.structure import MultiTimeframeStructureEngine, StructureEngine


class SignalGenerator:
    """End-to-end signal evaluation, multi-factor scoring, risk management, and market scanner."""

    def __init__(
        self,
        confluence_engine: Optional[ConfluenceEngine] = None,
        liquidity_service: Optional[LiquidityService] = None,
        mtf_engine: Optional[MultiTimeframeStructureEngine] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        scoring_engine: Optional[SignalScoringEngine] = None,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.confluence_engine = confluence_engine or ConfluenceEngine(
            liquidity_service=liquidity_service,
            mtf_engine=mtf_engine,
            indicator_service=indicator_service,
            news_filter=news_filter,
            risk_manager=risk_manager,
        )
        self.liquidity_service = self.confluence_engine.liquidity_service
        self.mtf_engine = self.confluence_engine.mtf_engine
        self.indicator_service = self.confluence_engine.indicator_service
        self.news_filter = self.confluence_engine.news_filter
        self.scoring_engine = scoring_engine or SignalScoringEngine()
        self.risk_manager = self.confluence_engine.risk_manager

    @staticmethod
    def generate_fingerprint(
        symbol: str,
        timeframe: str,
        direction: SignalDirection,
        entry_price: float,
        stop_loss: float,
        timestamp: datetime,
    ) -> str:
        """Generate unique SHA-256 fingerprint for deduplication."""
        return ConfluenceEngine.generate_fingerprint(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            timestamp=timestamp,
        )

    def evaluate_market_signal(
        self,
        candles_primary: Sequence[Union[CandleBase, Any]],
        symbol: str = "EUR/USD",
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
    ) -> SignalResponse:
        """Run full evaluation pipeline on candles and generate SignalResponse."""
        return self.confluence_engine.evaluate(
            symbol=symbol,
            candles_primary=candles_primary,
            timeframe=timeframe,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
            account_balance=account_balance,
            risk_percent=risk_percent,
        )


    def persist_signal_if_qualified(self, db: Session, signal_resp: SignalResponse) -> Optional[Signal]:
        """Save qualified actionable BUY/SELL signals into the database if not already present."""
        if signal_resp.direction == SignalDirection.WAIT:
            return None

        # Check existing fingerprint
        stmt = select(Signal).where(Signal.fingerprint == signal_resp.fingerprint)
        existing = db.scalars(stmt).first()
        if existing:
            return existing

        db_signal = Signal(
            symbol=signal_resp.symbol,
            timeframe=signal_resp.timeframe,
            direction=signal_resp.direction.value,
            setup_score=signal_resp.setup_score,
            entry_price=signal_resp.entry_price,
            stop_loss=signal_resp.stop_loss,
            take_profit_1=signal_resp.take_profit_1,
            take_profit_2=signal_resp.take_profit_2,
            risk_reward=signal_resp.risk_reward,
            fingerprint=signal_resp.fingerprint,
            reasons=signal_resp.reasons,
            status=signal_resp.status.value,
            is_broadcasted=signal_resp.is_broadcasted,
            timestamp=signal_resp.timestamp,
        )
        try:
            db.add(db_signal)
            db.commit()
            db.refresh(db_signal)
            logger.info(
                f"PERSISTED QUALIFIED SIGNAL: [{db_signal.direction}] {db_signal.symbol} "
                f"(Score: {db_signal.setup_score:.1f}, SL: {db_signal.stop_loss}, TP1: {db_signal.take_profit_1})"
            )
            return db_signal
        except Exception as e:
            db.rollback()
            existing_after_collision = db.scalars(stmt).first()
            if existing_after_collision:
                return existing_after_collision
            logger.warning(f"Could not persist signal {signal_resp.fingerprint}: {e}")
            return None

    def scan_all_symbols(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        timeframe: str = "1h",
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
        persist_qualified: bool = True,
    ) -> MarketScanResponse:
        """Scan multiple currency pairs, evaluate setups, check news blackouts, and generate signals."""
        target_symbols = symbols or settings.SUPPORTED_SYMBOLS
        results: List[MarketScanSymbolResult] = []
        actionable_count = 0
        now_utc = datetime.now(timezone.utc)

        for sym in target_symbols:
            # Query 1h, 4h, 15m candles from DB
            c1h = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == timeframe)
                    .order_by(desc(Candle.timestamp))
                    .limit(200)
                ).all()
            )
            c1h.reverse()

            c4h = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "4h")
                    .order_by(desc(Candle.timestamp))
                    .limit(100)
                ).all()
            )
            c4h.reverse()

            c15m = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "15m")
                    .order_by(desc(Candle.timestamp))
                    .limit(100)
                ).all()
            )
            c15m.reverse()

            if not c1h:
                results.append(
                    MarketScanSymbolResult(
                        symbol=sym,
                        timeframe=timeframe,
                        direction=SignalDirection.WAIT,
                        setup_score=0.0,
                        is_actionable=False,
                        signal=None,
                        blackout_blocked=False,
                        reasons=["No candle data available in database for this symbol."],
                    )
                )
                continue

            # Check News Blackout
            news_res = self.news_filter.check_from_db(
                db=db,
                symbol=sym,
                target_time=now_utc,
            )

            # Evaluate Signal
            sig = self.evaluate_market_signal(
                candles_primary=c1h,
                symbol=sym,
                timeframe=timeframe,
                candles_4h=c4h if c4h else None,
                candles_15m=c15m if c15m else None,
                news_check=news_res,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )

            is_act = sig.direction in (SignalDirection.BUY, SignalDirection.SELL)
            if is_act:
                actionable_count += 1
                if persist_qualified:
                    db_sig = self.persist_signal_if_qualified(db, sig)
                    if db_sig:
                        sig.id = db_sig.id

            results.append(
                MarketScanSymbolResult(
                    symbol=sym,
                    timeframe=timeframe,
                    direction=sig.direction,
                    setup_score=sig.setup_score,
                    is_actionable=is_act,
                    signal=sig,
                    blackout_blocked=news_res.is_blackout,
                    reasons=sig.reasons,
                )
            )

        return MarketScanResponse(
            timestamp=now_utc,
            scanned_count=len(target_symbols),
            actionable_count=actionable_count,
            results=results,
        )
