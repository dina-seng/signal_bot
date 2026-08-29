"""Market Structure Classification and Trend Analysis Engine."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.logging import logger
from app.models.structure import StructureEvent
from app.schemas.candle import CandleBase
from app.schemas.structure import (
    StructureAnalysisResponse,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)
from app.services.structure.swing_detector import SwingDetector


class StructureEngine:
    """Classifies swing points into HH/HL/LH/LL and determines market trend direction and strength."""

    def __init__(
        self,
        swing_detector: Optional[SwingDetector] = None,
        default_lookback: int = 2,
        default_tolerance_percent: float = 0.05,
    ):
        self.swing_detector = swing_detector or SwingDetector(default_lookback=default_lookback)
        self.default_lookback = default_lookback
        self.default_tolerance_percent = default_tolerance_percent

    def classify_swings(
        self,
        swings: List[SwingPoint],
        tolerance_percent: Optional[float] = None,
    ) -> List[SwingPoint]:
        """Label swing points as HH, HL, LH, LL, EH, EL.

        Args:
            swings: List of detected SwingPoint objects sorted chronologically.
            tolerance_percent: Percentage threshold to classify equal highs/lows (e.g. 0.05%).

        Returns:
            List of labeled SwingPoint objects.
        """
        tol = (
            tolerance_percent
            if tolerance_percent is not None
            else self.default_tolerance_percent
        ) / 100.0

        prev_swing_high: Optional[SwingPoint] = None
        prev_swing_low: Optional[SwingPoint] = None

        labeled_swings: List[SwingPoint] = []

        for swing in swings:
            # Create a shallow copy with mutable fields updated
            labeled_swing = swing.model_copy()

            if labeled_swing.swing_type == SwingType.SWING_HIGH:
                if prev_swing_high is None:
                    labeled_swing.structure_label = StructureLabel.UNCERTAIN
                    labeled_swing.prev_swing_price = None
                    labeled_swing.prev_swing_timestamp = None
                else:
                    prev_p = prev_swing_high.price
                    labeled_swing.prev_swing_price = prev_p
                    labeled_swing.prev_swing_timestamp = prev_swing_high.timestamp
                    rel_diff = (labeled_swing.price - prev_p) / prev_p

                    if rel_diff > tol:
                        labeled_swing.structure_label = StructureLabel.HH
                    elif rel_diff < -tol:
                        labeled_swing.structure_label = StructureLabel.LH
                    else:
                        labeled_swing.structure_label = StructureLabel.EH

                prev_swing_high = labeled_swing

            elif labeled_swing.swing_type == SwingType.SWING_LOW:
                if prev_swing_low is None:
                    labeled_swing.structure_label = StructureLabel.UNCERTAIN
                    labeled_swing.prev_swing_price = None
                    labeled_swing.prev_swing_timestamp = None
                else:
                    prev_p = prev_swing_low.price
                    labeled_swing.prev_swing_price = prev_p
                    labeled_swing.prev_swing_timestamp = prev_swing_low.timestamp
                    rel_diff = (labeled_swing.price - prev_p) / prev_p

                    if rel_diff > tol:
                        labeled_swing.structure_label = StructureLabel.HL
                    elif rel_diff < -tol:
                        labeled_swing.structure_label = StructureLabel.LL
                    else:
                        labeled_swing.structure_label = StructureLabel.EL

                prev_swing_low = labeled_swing

            labeled_swings.append(labeled_swing)

        return labeled_swings

    def determine_trend(
        self,
        labeled_swings: List[SwingPoint],
    ) -> tuple[TrendDirection, float]:
        """Determine trend direction and strength score from labeled swings.

        Rules:
        - BULLISH: Latest High is HH and latest Low is HL (or dominantly bullish progression).
        - BEARISH: Latest High is LH and latest Low is LL (or dominantly bearish progression).
        - RANGING: Conflicting signals (HH + LL or LH + HL), double tops/bottoms (EH / EL), or insufficient data.

        Returns:
            Tuple of (TrendDirection, trend_strength_score [0.0 - 1.0])
        """
        if not labeled_swings:
            return TrendDirection.RANGING, 0.0

        swing_highs = [s for s in labeled_swings if s.swing_type == SwingType.SWING_HIGH]
        swing_lows = [s for s in labeled_swings if s.swing_type == SwingType.SWING_LOW]

        if not swing_highs or not swing_lows:
            return TrendDirection.RANGING, 0.0

        last_sh = swing_highs[-1]
        last_sl = swing_lows[-1]

        # Recent labeled swings pool (up to last 6 swings)
        recent_labeled = [
            s for s in labeled_swings[-6:]
            if s.structure_label not in (None, StructureLabel.UNCERTAIN)
        ]

        if not recent_labeled:
            return TrendDirection.RANGING, 0.0

        bullish_count = sum(1 for s in recent_labeled if s.structure_label in (StructureLabel.HH, StructureLabel.HL))
        bearish_count = sum(1 for s in recent_labeled if s.structure_label in (StructureLabel.LH, StructureLabel.LL))
        ranging_count = sum(1 for s in recent_labeled if s.structure_label in (StructureLabel.EH, StructureLabel.EL))
        total_recent = len(recent_labeled)

        # Primary classification based on latest swing pair
        sh_label = last_sh.structure_label
        sl_label = last_sl.structure_label

        is_latest_bullish = (sh_label == StructureLabel.HH and sl_label == StructureLabel.HL)
        is_latest_bearish = (sh_label == StructureLabel.LH and sl_label == StructureLabel.LL)

        # Check for partial initialization (e.g. only 1 previous swing available)
        if sh_label == StructureLabel.HH and sl_label == StructureLabel.UNCERTAIN:
            is_latest_bullish = True
        elif sh_label == StructureLabel.UNCERTAIN and sl_label == StructureLabel.HL:
            is_latest_bullish = True
        elif sh_label == StructureLabel.LH and sl_label == StructureLabel.UNCERTAIN:
            is_latest_bearish = True
        elif sh_label == StructureLabel.UNCERTAIN and sl_label == StructureLabel.LL:
            is_latest_bearish = True

        if is_latest_bullish and not is_latest_bearish:
            trend = TrendDirection.BULLISH
            # Calculate strength based on consistency of recent swings
            consistency = bullish_count / total_recent if total_recent > 0 else 0.5
            # Consecutive bullish swings boost
            streak = 0
            for s in reversed(recent_labeled):
                if s.structure_label in (StructureLabel.HH, StructureLabel.HL):
                    streak += 1
                else:
                    break
            streak_factor = min(1.0, streak / 3.0)
            strength = round(min(1.0, max(0.1, (consistency * 0.6) + (streak_factor * 0.4))), 2)
            return trend, strength

        elif is_latest_bearish and not is_latest_bullish:
            trend = TrendDirection.BEARISH
            consistency = bearish_count / total_recent if total_recent > 0 else 0.5
            streak = 0
            for s in reversed(recent_labeled):
                if s.structure_label in (StructureLabel.LH, StructureLabel.LL):
                    streak += 1
                else:
                    break
            streak_factor = min(1.0, streak / 3.0)
            strength = round(min(1.0, max(0.1, (consistency * 0.6) + (streak_factor * 0.4))), 2)
            return trend, strength

        else:
            # Conflicting structure (e.g. HH with LL, or LH with HL, or EH/EL)
            trend = TrendDirection.RANGING
            # Ranging strength indicates how flat/choppy the market is (0.0 = completely chaotic, 0.5 = clearly bound range)
            range_clarity = ranging_count / total_recent if total_recent > 0 else 0.0
            strength = round(min(0.5, range_clarity * 0.5), 2)
            return trend, strength

    def analyze_structure(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "CUSTOM",
        timeframe: str = "1h",
        lookback: Optional[int] = None,
        tolerance_percent: Optional[float] = None,
    ) -> StructureAnalysisResponse:
        """Run complete market structure analysis on a sequence of candles.

        Args:
            candles: Sequence of candles chronologically sorted.
            symbol: Instrument symbol (e.g. 'EUR/USD').
            timeframe: Timeframe identifier (e.g. '1h').
            lookback: N-bar lookback for swing detection.
            tolerance_percent: Percentage tolerance for equal highs/lows.

        Returns:
            StructureAnalysisResponse with all swings, labels, trend, and support/resistance.
        """
        lb = lookback or self.default_lookback
        tol = tolerance_percent if tolerance_percent is not None else self.default_tolerance_percent

        # 1. Detect raw swings
        raw_swings = self.swing_detector.detect_swings(candles, lookback=lb)

        # 2. Classify swings into HH/HL/LH/LL
        labeled_swings = self.classify_swings(raw_swings, tolerance_percent=tol)

        # 3. Determine Trend & Strength
        trend, trend_strength = self.determine_trend(labeled_swings)

        # 4. Extract Key Metrics & Levels
        swing_highs = [s for s in labeled_swings if s.swing_type == SwingType.SWING_HIGH]
        swing_lows = [s for s in labeled_swings if s.swing_type == SwingType.SWING_LOW]

        last_sh = swing_highs[-1] if swing_highs else None
        prev_sh = swing_highs[-2] if len(swing_highs) >= 2 else None

        last_sl = swing_lows[-1] if swing_lows else None
        prev_sl = swing_lows[-2] if len(swing_lows) >= 2 else None

        hh_count = sum(1 for s in swing_highs if s.structure_label == StructureLabel.HH)
        lh_count = sum(1 for s in swing_highs if s.structure_label == StructureLabel.LH)
        eh_count = sum(1 for s in swing_highs if s.structure_label == StructureLabel.EH)

        hl_count = sum(1 for s in swing_lows if s.structure_label == StructureLabel.HL)
        ll_count = sum(1 for s in swing_lows if s.structure_label == StructureLabel.LL)
        el_count = sum(1 for s in swing_lows if s.structure_label == StructureLabel.EL)

        # Key resistance: highest price among recent swing highs (up to last 5)
        recent_sh_prices = [s.price for s in swing_highs[-5:]] if swing_highs else []
        key_resistance = max(recent_sh_prices) if recent_sh_prices else (last_sh.price if last_sh else None)

        # Key support: lowest price among recent swing lows (up to last 5)
        recent_sl_prices = [s.price for s in swing_lows[-5:]] if swing_lows else []
        key_support = min(recent_sl_prices) if recent_sl_prices else (last_sl.price if last_sl else None)

        return StructureAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            trend=trend,
            trend_strength=trend_strength,
            total_candles=len(candles),
            total_swings=len(labeled_swings),
            swing_points=labeled_swings,
            last_swing_high=last_sh,
            last_swing_low=last_sl,
            previous_swing_high=prev_sh,
            previous_swing_low=prev_sl,
            higher_highs_count=hh_count,
            higher_lows_count=hl_count,
            lower_highs_count=lh_count,
            lower_lows_count=ll_count,
            equal_highs_count=eh_count,
            equal_lows_count=el_count,
            key_resistance=key_resistance,
            key_support=key_support,
        )

    def persist_structure_events(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        swings: List[SwingPoint],
    ) -> int:
        """Persist newly identified structure events to the database.

        Args:
            db: Active SQLAlchemy database session.
            symbol: Forex instrument symbol.
            timeframe: Timeframe identifier.
            swings: Labeled swing points.

        Returns:
            Number of newly inserted structure events.
        """
        if not swings:
            return 0

        # Query existing events for this symbol and timeframe in the timestamp range
        min_ts = swings[0].timestamp
        max_ts = swings[-1].timestamp

        stmt = select(StructureEvent.timestamp, StructureEvent.event_type).where(
            StructureEvent.symbol == symbol,
            StructureEvent.timeframe == timeframe,
            StructureEvent.timestamp >= min_ts,
            StructureEvent.timestamp <= max_ts,
        )
        existing_rows = db.execute(stmt).all()
        existing = set()
        for row in existing_rows:
            row_ts = row[0]
            if row_ts.tzinfo is None:
                row_ts = row_ts.replace(tzinfo=timezone.utc)
            else:
                row_ts = row_ts.astimezone(timezone.utc)
            existing.add((row_ts, row[1]))

        new_events: List[StructureEvent] = []
        for swing in swings:
            # Map swing type and label to event_type
            label_str = swing.structure_label.value if swing.structure_label else "SWING"
            event_type = f"{swing.swing_type.value}_{label_str}"

            # Check if event already stored
            ts = swing.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            event_key = (ts, event_type)
            if event_key in existing:
                continue

            model = StructureEvent(
                symbol=symbol,
                timeframe=timeframe,
                event_type=event_type,
                price=swing.price,
                timestamp=ts,
                reference_price=swing.prev_swing_price,
                reference_timestamp=swing.prev_swing_timestamp,
            )
            new_events.append(model)

        if new_events:
            try:
                db.add_all(new_events)
                db.commit()
                logger.info(
                    f"Persisted {len(new_events)} structure events for {symbol} [{timeframe}]."
                )
            except Exception as e:
                db.rollback()
                logger.warning(
                    f"Structure events insertion conflict for {symbol} [{timeframe}]: {e}. Rolled back safely."
                )
                return 0

        return len(new_events)
