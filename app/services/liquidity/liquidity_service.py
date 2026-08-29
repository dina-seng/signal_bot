"""Liquidity and Advanced Market Structure Orchestration Service."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.logging import logger
from app.models.liquidity import LiquidityEvent
from app.models.structure import StructureEvent
from app.schemas.candle import CandleBase
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BreakoutEvent,
    LiquidityPool,
    LiquiditySweep,
    SupportResistanceZone,
)
from app.schemas.structure import StructureAnalysisResponse, TrendDirection
from app.services.structure.structure_engine import StructureEngine
from app.services.structure.bos_choch_detector import BOSCHOCHDetector
from app.services.liquidity.sweep_detector import LiquiditySweepDetector
from app.services.liquidity.sr_detector import SupportResistanceDetector


class LiquidityService:
    """Orchestrates BOS, CHOCH/MSS, Liquidity Sweeps, and Dynamic S/R Zone analysis."""

    def __init__(
        self,
        structure_engine: Optional[StructureEngine] = None,
        bos_choch_detector: Optional[BOSCHOCHDetector] = None,
        sweep_detector: Optional[LiquiditySweepDetector] = None,
        sr_detector: Optional[SupportResistanceDetector] = None,
    ):
        self.structure_engine = structure_engine or StructureEngine(
            default_lookback=settings.SWING_LOOKBACK,
            default_tolerance_percent=settings.SR_TOLERANCE_PERCENT,
        )
        self.bos_choch_detector = bos_choch_detector or BOSCHOCHDetector()
        self.sweep_detector = sweep_detector or LiquiditySweepDetector()
        self.sr_detector = sr_detector or SupportResistanceDetector(
            default_tolerance_percent=settings.SR_TOLERANCE_PERCENT
        )

    def _determine_market_state(
        self,
        trend: TrendDirection,
        latest_bos: Optional[BreakoutEvent],
        latest_choch: Optional[BreakoutEvent],
        latest_sweep: Optional[LiquiditySweep],
    ) -> str:
        """Classify current institutional market state based on most recent event."""
        # Find the most recent event by timestamp
        events = []
        if latest_choch:
            events.append(("CHOCH", latest_choch.timestamp, latest_choch.event_type.value))
        if latest_bos:
            events.append(("BOS", latest_bos.timestamp, latest_bos.event_type.value))
        if latest_sweep:
            events.append(("SWEEP", latest_sweep.timestamp, latest_sweep.sweep_type.value))

        if not events:
            if trend == TrendDirection.BULLISH:
                return "BULLISH_TREND_EXPANSION"
            elif trend == TrendDirection.BEARISH:
                return "BEARISH_TREND_EXPANSION"
            return "RANGING_CONSOLIDATION"

        # Sort by timestamp descending
        events.sort(key=lambda x: x[1], reverse=True)
        most_recent_kind, _, event_val = events[0]

        if event_val == "BULLISH_CHOCH":
            return "BULLISH_REVERSAL_CONFIRMED"
        elif event_val == "BEARISH_CHOCH":
            return "BEARISH_REVERSAL_CONFIRMED"
        elif event_val == "BULLISH_BOS":
            return "BULLISH_TREND_CONTINUATION"
        elif event_val == "BEARISH_BOS":
            return "BEARISH_TREND_CONTINUATION"
        elif event_val == "BUY_SIDE_SWEEP":
            return "BUY_SIDE_LIQUIDITY_SWEPT"
        elif event_val == "SELL_SIDE_SWEEP":
            return "SELL_SIDE_LIQUIDITY_SWEPT"

        return f"{trend.value}_MARKET_STATE"

    def analyze_liquidity_and_structure(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "EUR/USD",
        timeframe: str = "1h",
        lookback: Optional[int] = None,
        tolerance_percent: Optional[float] = None,
    ) -> AdvancedStructureAnalysisResponse:
        """Perform full SMC liquidity, BOS, CHOCH, and S/R Zone analysis on a candle series.

        Args:
            candles: Chronological candle sequence.
            symbol: Instrument symbol (e.g. 'EUR/USD').
            timeframe: Timeframe identifier.
            lookback: N-bar swing lookback.
            tolerance_percent: Percentage tolerance for equal highs/lows and S/R clustering.

        Returns:
            AdvancedStructureAnalysisResponse.
        """
        # 1. Base Structure Analysis (Swings, HH/HL/LH/LL, Trend)
        base_structure = self.structure_engine.analyze_structure(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
            lookback=lookback,
            tolerance_percent=tolerance_percent,
        )

        swings = base_structure.swing_points
        trend = base_structure.trend

        # 2. Break of Structure (BOS) & Change of Character (CHOCH) Detection
        bos_events, choch_events = self.bos_choch_detector.detect_bos_and_choch(
            candles=candles,
            swings=swings,
            current_trend=trend,
        )

        # 3. Liquidity Sweeps Detection
        sweeps = self.sweep_detector.detect_sweeps(
            candles=candles,
            swings=swings,
            symbol=symbol,
        )

        # 4. Support/Resistance Zones & Liquidity Pools
        sr_zones, pools = self.sr_detector.detect_sr_zones_and_pools(
            candles=candles,
            swings=swings,
            tolerance_percent=tolerance_percent,
        )

        # 5. Extract latest indicators
        latest_bos = bos_events[-1] if bos_events else None
        latest_choch = choch_events[-1] if choch_events else None
        latest_sweep = sweeps[-1] if sweeps else None

        # 6. Institutional Market State
        market_state = self._determine_market_state(
            trend=trend,
            latest_bos=latest_bos,
            latest_choch=latest_choch,
            latest_sweep=latest_sweep,
        )

        return AdvancedStructureAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            trend=trend,
            trend_strength=base_structure.trend_strength,
            market_state=market_state,
            bos_events=bos_events,
            choch_events=choch_events,
            latest_bos=latest_bos,
            latest_choch=latest_choch,
            liquidity_sweeps=sweeps,
            latest_sweep=latest_sweep,
            liquidity_pools=pools,
            sr_zones=sr_zones,
            base_structure=base_structure,
        )

    def persist_events(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        analysis: AdvancedStructureAnalysisResponse,
    ) -> tuple[int, int]:
        """Persist breakout events to StructureEvent and sweeps/pools to LiquidityEvent.

        Returns:
            Tuple of (structure_events_inserted, liquidity_events_inserted).
        """
        # 1. Persist base swings first
        swings_inserted = self.structure_engine.persist_structure_events(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            swings=analysis.base_structure.swing_points,
        )

        # 2. Persist BOS and CHOCH events to StructureEvent table
        breakouts = analysis.bos_events + analysis.choch_events
        new_structure_events: List[StructureEvent] = []

        if breakouts:
            min_ts = min(b.timestamp for b in breakouts)
            max_ts = max(b.timestamp for b in breakouts)

            stmt = select(StructureEvent.timestamp, StructureEvent.event_type).where(
                StructureEvent.symbol == symbol,
                StructureEvent.timeframe == timeframe,
                StructureEvent.timestamp >= min_ts,
                StructureEvent.timestamp <= max_ts,
            )
            existing_rows = db.execute(stmt).all()
            existing_struct = set()
            for r in existing_rows:
                ts_val = r[0].replace(tzinfo=timezone.utc) if r[0].tzinfo is None else r[0].astimezone(timezone.utc)
                existing_struct.add((ts_val, r[1]))

            for b in breakouts:
                ts = b.timestamp.replace(tzinfo=timezone.utc) if b.timestamp.tzinfo is None else b.timestamp.astimezone(timezone.utc)
                key = (ts, b.event_type.value)
                if key in existing_struct:
                    continue

                new_structure_events.append(
                    StructureEvent(
                        symbol=symbol,
                        timeframe=timeframe,
                        event_type=b.event_type.value,
                        price=b.breakout_price,
                        timestamp=ts,
                        reference_price=b.broken_swing_price,
                        reference_timestamp=b.broken_swing_timestamp,
                    )
                )

            if new_structure_events:
                db.add_all(new_structure_events)

        # 3. Persist Liquidity Sweeps and Pools to LiquidityEvent table
        new_liquidity_events: List[LiquidityEvent] = []
        sweeps_and_pools = analysis.liquidity_sweeps

        if sweeps_and_pools:
            min_ts = min(s.timestamp for s in sweeps_and_pools)
            max_ts = max(s.timestamp for s in sweeps_and_pools)

            stmt_liq = select(LiquidityEvent.timestamp, LiquidityEvent.event_type).where(
                LiquidityEvent.symbol == symbol,
                LiquidityEvent.timeframe == timeframe,
                LiquidityEvent.timestamp >= min_ts,
                LiquidityEvent.timestamp <= max_ts,
            )
            existing_liq_rows = db.execute(stmt_liq).all()
            existing_liq = set()
            for r in existing_liq_rows:
                ts_val = r[0].replace(tzinfo=timezone.utc) if r[0].tzinfo is None else r[0].astimezone(timezone.utc)
                existing_liq.add((ts_val, r[1]))

            for s in analysis.liquidity_sweeps:
                ts = s.timestamp.replace(tzinfo=timezone.utc) if s.timestamp.tzinfo is None else s.timestamp.astimezone(timezone.utc)
                key = (ts, s.sweep_type.value)
                if key in existing_liq:
                    continue

                new_liquidity_events.append(
                    LiquidityEvent(
                        symbol=symbol,
                        timeframe=timeframe,
                        event_type=s.sweep_type.value,
                        price_level=s.swept_level,
                        sweep_high=s.sweep_extreme if s.sweep_type.value == "BUY_SIDE_SWEEP" else None,
                        sweep_low=s.sweep_extreme if s.sweep_type.value == "SELL_SIDE_SWEEP" else None,
                        timestamp=ts,
                    )
                )

            if new_liquidity_events:
                db.add_all(new_liquidity_events)

        if new_structure_events or new_liquidity_events:
            try:
                db.commit()
                logger.info(
                    f"Persisted {len(new_structure_events)} breakout events and {len(new_liquidity_events)} liquidity events for {symbol} [{timeframe}]."
                )
            except Exception as e:
                db.rollback()
                logger.warning(
                    f"Liquidity events insertion conflict for {symbol} [{timeframe}]: {e}. Rolled back safely."
                )
                return 0, 0

        return len(new_structure_events), len(new_liquidity_events)
