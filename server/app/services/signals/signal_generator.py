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
from app.services.market_data import (
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    log_latest_candle,
)
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
        symbol: str = "XAU/USD",
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

    def evaluate_market_signals_multi(
        self,
        candles_primary: Sequence[Union[CandleBase, Any]],
        symbol: str = "XAU/USD",
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
    ) -> List[SignalResponse]:
        """Run all strategies and return independent SignalResponse per qualifying strategy."""
        return self.confluence_engine.evaluate_multi(
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

        # Supersede previous active signals for the same symbol to prevent conflicting active setups
        try:
            db.query(Signal).filter(
                Signal.symbol == signal_resp.symbol,
                Signal.status == "ACTIVE",
            ).update({"status": "SUPERSEDED"})
            db.commit()
        except Exception as e:
            db.rollback()
            logger.debug(f"Could not supersede previous signals for {signal_resp.symbol}: {e}")

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
            trend_alignment=signal_resp.trend_alignment,
            htf_trend=signal_resp.htf_trend,
            strategy_name=signal_resp.strategy_name,
            is_broadcasted=signal_resp.is_broadcasted,
            timestamp=signal_resp.timestamp,
        )
        try:
            db.add(db_signal)
            db.commit()
            db.refresh(db_signal)
            logger.info(
                f"PERSISTED QUALIFIED SIGNAL: [{db_signal.direction}] {db_signal.symbol} [{db_signal.timeframe}] "
                f"(Score: {db_signal.setup_score:.1f}, Alignment: {db_signal.trend_alignment}, SL: {db_signal.stop_loss}, TP1: {db_signal.take_profit_1})"
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
            # Query 1h, 4h, 15m candles from DB and filter to closed verified candles
            c1h_raw = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == timeframe)
                    .order_by(desc(Candle.timestamp))
                    .limit(200)
                ).all()
            )
            c1h_raw.reverse()
            c1h = filter_closed_candles(c1h_raw, timeframe=timeframe)

            c4h_raw = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "4h")
                    .order_by(desc(Candle.timestamp))
                    .limit(100)
                ).all()
            )
            c4h_raw.reverse()
            c4h = filter_closed_candles(c4h_raw, timeframe="4h")

            c15m_raw = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "15m")
                    .order_by(desc(Candle.timestamp))
                    .limit(100)
                ).all()
            )
            c15m_raw.reverse()
            c15m = filter_closed_candles(c15m_raw, timeframe="15m")

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

            # Check Data Staleness & Explicit Latest Candle Logging for scanned symbol
            staleness = check_data_staleness(c1h, symbol=sym, timeframe=timeframe)
            latest_c1h = c1h[-1]
            log_latest_candle(
                latest_c1h,
                symbol=sym,
                timeframe=timeframe,
                context="MARKET SCAN",
                is_fresh=not staleness.is_stale,
            )
            if staleness.is_stale:
                logger.warning(staleness.message)

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
                    blackout_blocked=news_res.is_blackout or not news_res.trading_allowed or news_res.is_news_unavailable,
                    reasons=sig.reasons,
                )
            )

        return MarketScanResponse(
            timestamp=now_utc,
            scanned_count=len(target_symbols),
            actionable_count=actionable_count,
            results=results,
        )

    def scan_unified(
        self,
        db: Session,
        symbol: str,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
        persist_qualified: bool = True,
    ) -> MarketScanSymbolResult:
        """Unified Multi-Timeframe Scanner evaluating 15m, 30m, and 1H for a single symbol.

        Logic:
          - Analyzes 1H trend (BULLISH / BEARISH / RANGING).
          - Evaluates 15m and 30m setups.
          - If 1H trend is BULLISH:
              * BUY signals (score >= 75) are returned as TREND FOLLOWING.
              * SELL signals (score > 80) are returned as COUNTER-TREND SCALP.
          - If 1H trend is BEARISH:
              * SELL signals (score >= 75) are returned as TREND FOLLOWING.
              * BUY signals (score > 80) are returned as COUNTER-TREND SCALP.
          - If 1H trend is RANGING:
              * Any qualified signal (score >= 75) is returned as TREND FOLLOWING.
          - If no high-confluence setup (>75 score) is found on 15m/30m, falls back to 1H.
          - Returns the single "Best" signal for that symbol, clearly labeling the timeframe.
        """
        clean_sym = symbol.replace("%2F", "/").strip().upper()
        for s in settings.SUPPORTED_SYMBOLS:
            if s.replace("/", "") == clean_sym.replace("/", ""):
                clean_sym = s
                break

        now_utc = datetime.now(timezone.utc)

        # 1. Fetch candles for 1h, 30m, 15m, and 4h
        c1h_raw = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == clean_sym, Candle.timeframe == "1h")
                .order_by(desc(Candle.timestamp))
                .limit(200)
            ).all()
        )
        c1h_raw.reverse()
        c1h = filter_closed_candles(c1h_raw, timeframe="1h")

        c30m_raw = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == clean_sym, Candle.timeframe == "30m")
                .order_by(desc(Candle.timestamp))
                .limit(200)
            ).all()
        )
        c30m_raw.reverse()
        c30m = filter_closed_candles(c30m_raw, timeframe="30m")

        c15m_raw = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == clean_sym, Candle.timeframe == "15m")
                .order_by(desc(Candle.timestamp))
                .limit(200)
            ).all()
        )
        c15m_raw.reverse()
        c15m = filter_closed_candles(c15m_raw, timeframe="15m")

        c4h_raw = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == clean_sym, Candle.timeframe == "4h")
                .order_by(desc(Candle.timestamp))
                .limit(100)
            ).all()
        )
        c4h_raw.reverse()
        c4h = filter_closed_candles(c4h_raw, timeframe="4h")

        if not c1h:
            return MarketScanSymbolResult(
                symbol=clean_sym,
                timeframe="1h",
                direction=SignalDirection.WAIT,
                setup_score=0.0,
                is_actionable=False,
                signal=None,
                blackout_blocked=False,
                trend_alignment=None,
                htf_trend="NEUTRAL",
                reasons=["No candle data available in database for this symbol."],
            )

        # 2. Check News Blackout
        news_res = self.news_filter.check_from_db(
            db=db,
            symbol=clean_sym,
            target_time=now_utc,
        )
        is_blackout = (
            news_res.is_blackout
            or not news_res.trading_allowed
            or news_res.is_news_unavailable
        )

        # 3. Determine 1H Trend
        struct_1h = self.liquidity_service.analyze_liquidity_and_structure(
            candles=c1h, symbol=clean_sym, timeframe="1h"
        )
        ind_1h = self.indicator_service.analyze_indicators(
            candles=c1h, symbol=clean_sym, timeframe="1h"
        )

        s_trend = (
            struct_1h.trend.value
            if hasattr(struct_1h.trend, "value")
            else str(struct_1h.trend)
        )
        ema_trend = ind_1h.ema.ema_trend.upper()
        bias = ind_1h.confluence_bias.upper()

        if s_trend == "BULLISH" or (s_trend != "BEARISH" and (ema_trend == "BULLISH" or "BULLISH" in bias)):
            htf_trend = "BULLISH"
        elif s_trend == "BEARISH" or (s_trend != "BULLISH" and (ema_trend == "BEARISH" or "BEARISH" in bias)):
            htf_trend = "BEARISH"
        elif "BULLISH" in bias:
            htf_trend = "BULLISH"
        elif "BEARISH" in bias:
            htf_trend = "BEARISH"
        else:
            htf_trend = "RANGING"

        # 4. Evaluate candidate setups across 15m, 30m, and 1H
        sig_15m = (
            self.evaluate_market_signal(
                candles_primary=c15m,
                symbol=clean_sym,
                timeframe="15m",
                candles_4h=c4h or None,
                candles_15m=c15m or None,
                news_check=news_res,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )
            if c15m and len(c15m) >= 20
            else None
        )

        sig_30m = (
            self.evaluate_market_signal(
                candles_primary=c30m,
                symbol=clean_sym,
                timeframe="30m",
                candles_4h=c4h or None,
                candles_15m=c15m or None,
                news_check=news_res,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )
            if c30m and len(c30m) >= 20
            else None
        )

        sig_1h = self.evaluate_market_signal(
            candles_primary=c1h,
            symbol=clean_sym,
            timeframe="1h",
            candles_4h=c4h or None,
            candles_15m=c15m or None,
            news_check=news_res,
            account_balance=account_balance,
            risk_percent=risk_percent,
        )

        # 5. Filter Lower Timeframe (15m/30m) Candidates by Trend Alignment
        ltf_candidates = []
        for cand in [sig_15m, sig_30m]:
            if not cand or cand.direction not in (SignalDirection.BUY, SignalDirection.SELL):
                continue

            score = cand.setup_score
            dir_val = cand.direction
            align = None

            if htf_trend == "BULLISH":
                if dir_val == SignalDirection.BUY and score >= 75.0:
                    align = "TREND FOLLOWING"
                elif dir_val == SignalDirection.SELL and score > 80.0:
                    align = "COUNTER-TREND SCALP"
            elif htf_trend == "BEARISH":
                if dir_val == SignalDirection.SELL and score >= 75.0:
                    align = "TREND FOLLOWING"
                elif dir_val == SignalDirection.BUY and score > 80.0:
                    align = "COUNTER-TREND SCALP"
            else:  # RANGING
                if score >= 75.0:
                    align = "TREND FOLLOWING"

            if align:
                cand.trend_alignment = align
                cand.htf_trend = htf_trend
                ltf_candidates.append((cand, align))

        # 6. Select Best Signal or Fall Back to 1H
        best_sig: SignalResponse
        trend_alignment: Optional[str] = None

        if ltf_candidates:
            # Sort by score desc, prioritizing TREND FOLLOWING if tied
            ltf_candidates.sort(
                key=lambda x: (x[0].setup_score, 1 if x[1] == "TREND FOLLOWING" else 0),
                reverse=True,
            )
            best_sig, trend_alignment = ltf_candidates[0]

            if trend_alignment == "TREND FOLLOWING":
                label_prefix = f"[TREND FOLLOWING] 1H Trend: {htf_trend} • {best_sig.timeframe} Momentum Alignment"
            else:
                label_prefix = f"[COUNTER-TREND SCALP] 1H Trend: {htf_trend} • {best_sig.timeframe} Counter-Trend Scalp (>80 Score)"

            if not any(label_prefix in r for r in best_sig.reasons):
                best_sig.reasons.insert(0, label_prefix)
        else:
            # Fall back to 1H timeframe
            best_sig = sig_1h
            best_sig.htf_trend = htf_trend

            if best_sig.direction in (SignalDirection.BUY, SignalDirection.SELL) and best_sig.setup_score >= 75.0:
                trend_alignment = "TREND FOLLOWING"
                best_sig.trend_alignment = trend_alignment
                label_prefix = f"[TREND FOLLOWING] 1H Primary Trend Setup • Score: {best_sig.setup_score:.1f}/100"
                if not any(label_prefix in r for r in best_sig.reasons):
                    best_sig.reasons.insert(0, label_prefix)
            else:
                trend_alignment = None
                best_sig.trend_alignment = None
                wait_reason = (
                    f"1H Trend: {htf_trend} • No high-confluence setup (>75 score) on 15m/30m/1H. "
                    "Awaiting structural confirmation."
                )
                if not any("1H Trend:" in r for r in best_sig.reasons):
                    best_sig.reasons.insert(0, wait_reason)

        is_act = best_sig.direction in (SignalDirection.BUY, SignalDirection.SELL) and not is_blackout

        if is_act and persist_qualified:
            db_sig = self.persist_signal_if_qualified(db, best_sig)
            if db_sig:
                best_sig.id = db_sig.id

        return MarketScanSymbolResult(
            symbol=clean_sym,
            timeframe=best_sig.timeframe,
            direction=best_sig.direction,
            setup_score=best_sig.setup_score,
            is_actionable=is_act,
            signal=best_sig,
            blackout_blocked=is_blackout,
            trend_alignment=trend_alignment,
            htf_trend=htf_trend,
            reasons=best_sig.reasons,
        )

    def scan_unified_all(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
        persist_qualified: bool = True,
    ) -> MarketScanResponse:
        """Execute unified multi-timeframe scan across all target symbols."""
        target_symbols = symbols or settings.SUPPORTED_SYMBOLS
        results: List[MarketScanSymbolResult] = []
        actionable_count = 0
        now_utc = datetime.now(timezone.utc)

        for sym in target_symbols:
            res = self.scan_unified(
                db=db,
                symbol=sym,
                account_balance=account_balance,
                risk_percent=risk_percent,
                persist_qualified=persist_qualified,
            )
            if res.is_actionable:
                actionable_count += 1
            results.append(res)

        return MarketScanResponse(
            timestamp=now_utc,
            scanned_count=len(target_symbols),
            actionable_count=actionable_count,
            results=results,
        )
