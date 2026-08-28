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
from app.services.signals.risk_manager import RiskManager
from app.services.signals.scoring_engine import SignalScoringEngine
from app.services.structure import MultiTimeframeStructureEngine, StructureEngine


class SignalGenerator:
    """End-to-end signal evaluation, multi-factor scoring, risk management, and market scanner."""

    def __init__(
        self,
        liquidity_service: Optional[LiquidityService] = None,
        mtf_engine: Optional[MultiTimeframeStructureEngine] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        scoring_engine: Optional[SignalScoringEngine] = None,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.liquidity_service = liquidity_service or LiquidityService()
        self.mtf_engine = mtf_engine or MultiTimeframeStructureEngine()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.scoring_engine = scoring_engine or SignalScoringEngine()
        self.risk_manager = risk_manager or RiskManager()

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
        ts_str = timestamp.isoformat()
        payload = f"{symbol}_{timeframe}_{direction.value}_{entry_price:.5f}_{stop_loss:.5f}_{ts_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
        # 1. SMC Advanced Structure
        structure_analysis = self.liquidity_service.analyze_liquidity_and_structure(
            candles=candles_primary,
            symbol=symbol,
            timeframe=timeframe,
        )

        # 2. Indicators & Price Action
        indicator_analysis = self.indicator_service.analyze_indicators(
            candles=candles_primary,
            symbol=symbol,
            timeframe=timeframe,
        )

        # 3. Multi-Timeframe Alignment
        mtf_analysis = None
        if candles_4h and candles_15m:
            mtf_analysis = self.mtf_engine.analyze_multi_timeframe(
                symbol=symbol,
                timeframe_candles={
                    "4h": candles_4h,
                    "1h": candles_primary if timeframe == "1h" else candles_4h,
                    "15m": candles_15m,
                },
            )


        # 4. Scoring Engine
        direction, total_score, breakdown, reasons = self.scoring_engine.evaluate_setup(
            symbol=symbol,
            timeframe=timeframe,
            structure=structure_analysis,
            indicators=indicator_analysis,
            mtf=mtf_analysis,
            news_check=news_check,
        )

        current_price = indicator_analysis.current_price
        latest_ts = indicator_analysis.timestamp

        # 5. Risk Management & Levels
        risk_params: Optional[RiskParameters] = None
        entry_p: Optional[float] = None
        sl_p: Optional[float] = None
        tp1_p: Optional[float] = None
        tp2_p: Optional[float] = None
        rr_p: Optional[float] = None

        if direction in (SignalDirection.BUY, SignalDirection.SELL):
            # Extract key levels from structure
            supp_low = structure_analysis.base_structure.key_support
            res_high = structure_analysis.base_structure.key_resistance


            risk_params = self.risk_manager.calculate_trade_risk(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                atr_value=indicator_analysis.atr.atr_value,
                key_support_low=supp_low,
                key_resistance_high=res_high,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )
            entry_p = risk_params.entry_price
            sl_p = risk_params.stop_loss
            tp1_p = risk_params.take_profit_1
            tp2_p = risk_params.take_profit_2
            rr_p = risk_params.risk_reward_tp1
        else:
            entry_p = current_price
            sl_p = current_price
            tp1_p = current_price
            tp2_p = current_price
            rr_p = 0.0

        fingerprint = self.generate_fingerprint(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_p,
            stop_loss=sl_p,
            timestamp=latest_ts,
        )

        return SignalResponse(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            setup_score=total_score,
            entry_price=entry_p,
            stop_loss=sl_p,
            take_profit_1=tp1_p,
            take_profit_2=tp2_p,
            risk_reward=rr_p,
            fingerprint=fingerprint,
            reasons=reasons,
            status=SignalStatus.ACTIVE,
            timestamp=latest_ts,
            score_breakdown=breakdown,
            risk_parameters=risk_params,
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
            timestamp=signal_resp.timestamp,
        )
        db.add(db_signal)
        db.commit()
        db.refresh(db_signal)
        logger.info(
            f"PERSISTED QUALIFIED SIGNAL: [{db_signal.direction}] {db_signal.symbol} "
            f"(Score: {db_signal.setup_score:.1f}, SL: {db_signal.stop_loss}, TP1: {db_signal.take_profit_1})"
        )
        return db_signal

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
