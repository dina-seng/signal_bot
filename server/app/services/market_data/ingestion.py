"""Market data ingestion service with validation, deduplication, gap detection, and freshness verification."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.core.logging import logger
from app.models.candle import Candle
from app.schemas.candle import CandleCreate, GapInfo, IngestionReport
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import (
    TIMEFRAME_DELTAS,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    get_latest_closed_candle,
    get_timeframe_delta,
    is_forex_weekend,
    log_latest_candle,
)


class IngestionService:
    """Service for validating, cleaning, deduplicating, and persisting OHLCV candle streams."""

    TIMEFRAME_DELTAS: Dict[str, timedelta] = TIMEFRAME_DELTAS

    def __init__(self, provider: BaseMarketDataProvider, db: Session):
        self.provider = provider
        self.db = db

    def get_timeframe_delta(self, timeframe: str) -> timedelta:
        return get_timeframe_delta(timeframe)

    def clean_and_sort_candles(
        self, candles: List[CandleCreate]
    ) -> Tuple[List[CandleCreate], int]:
        """Validate, remove intra-batch duplicates, and sort chronologically.

        Returns:
            Tuple of (cleaned_sorted_candles, duplicate_count)
        """
        seen_timestamps: Set[datetime] = set()
        cleaned: List[CandleCreate] = []
        intra_duplicates = 0

        for candle in candles:
            # Ensure timestamp is UTC aware
            ts = ensure_utc_datetime(candle.timestamp)
            candle.timestamp = ts

            if ts in seen_timestamps:
                intra_duplicates += 1
                continue

            seen_timestamps.add(ts)
            cleaned.append(candle)

        # Sort ascending chronologically (handling out-of-order data)
        cleaned.sort(key=lambda c: c.timestamp)
        return cleaned, intra_duplicates

    def detect_gaps(
        self, candles: List[CandleCreate], symbol: str, timeframe: str
    ) -> List[GapInfo]:
        """Detect missing candle intervals between consecutive candles.

        Accounts for weekend market closures in Forex (Friday 21:00 UTC to Sunday 21:00 UTC).
        """
        if len(candles) < 2:
            return []

        delta = self.get_timeframe_delta(timeframe)
        gaps: List[GapInfo] = []

        for i in range(len(candles) - 1):
            curr_ts = ensure_utc_datetime(candles[i].timestamp)
            next_ts = ensure_utc_datetime(candles[i + 1].timestamp)
            diff = next_ts - curr_ts

            # If difference is larger than 1.5x expected interval
            if diff > delta * 1.5:
                # Check if it spans a weekend closure (approx 48 hours between Fri night and Sun night)
                is_weekend = (
                    curr_ts.weekday() == 4 and next_ts.weekday() in (6, 0)
                ) or (diff >= timedelta(hours=44) and diff <= timedelta(hours=54))

                if not is_weekend:
                    missing_count = int(diff / delta) - 1
                    if missing_count > 0:
                        gaps.append(
                            GapInfo(
                                symbol=symbol,
                                timeframe=timeframe,
                                gap_start=curr_ts,
                                gap_end=next_ts,
                                missing_candles_estimated=missing_count,
                            )
                        )

        return gaps

    def ingest_candles(
        self, candles: List[CandleCreate], symbol: str, timeframe: str
    ) -> IngestionReport:
        """Process and persist a list of candles into the database."""
        fetched_count = len(candles)
        if not candles:
            return IngestionReport(
                symbol=symbol,
                timeframe=timeframe,
                fetched_count=0,
                inserted_count=0,
                skipped_duplicates_count=0,
                invalid_candles_count=0,
                gaps_detected=[],
            )

        # 1. Clean intra-batch duplicates and sort out-of-order candles
        cleaned_candles, intra_duplicates = self.clean_and_sort_candles(candles)

        # 2. Detect missing data gaps
        gaps = self.detect_gaps(cleaned_candles, symbol, timeframe)
        if gaps:
            logger.warning(
                f"Detected {len(gaps)} data gap(s) for {symbol} ({timeframe}). First gap at: {gaps[0].gap_start}"
            )

        # 3. Query existing timestamps from database in the current range
        min_time = cleaned_candles[0].timestamp
        max_time = cleaned_candles[-1].timestamp

        stmt = (
            select(Candle.timestamp)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.timestamp >= min_time,
                Candle.timestamp <= max_time,
            )
        )
        existing_ts_set = set(self.db.scalars(stmt).all())

        # Normalize existing timestamps to UTC for comparison
        existing_ts_utc: Set[datetime] = {
            ensure_utc_datetime(ts) for ts in existing_ts_set if ts is not None
        }

        # 4. Filter out DB duplicates and prepare new candle models
        to_insert: List[Candle] = []
        db_duplicates = 0

        for c in cleaned_candles:
            if c.timestamp in existing_ts_utc:
                db_duplicates += 1
                continue

            candle_model = Candle(
                symbol=c.symbol,
                timeframe=c.timeframe,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            to_insert.append(candle_model)

        # 5. Bulk insert new records
        inserted_count = 0
        if to_insert:
            try:
                self.db.add_all(to_insert)
                self.db.commit()
                inserted_count = len(to_insert)
                logger.info(
                    f"Successfully inserted {inserted_count} new candles for {symbol} [{timeframe}]. "
                    f"Skipped {intra_duplicates + db_duplicates} duplicates."
                )
            except Exception as e:
                self.db.rollback()
                logger.warning(
                    f"Concurrent candle insertion conflict for {symbol} [{timeframe}]: {e}. Rolled back safely."
                )
        else:
            logger.info(
                f"No new candles to insert for {symbol} [{timeframe}]. All {fetched_count} candles already exist."
            )

        # 6. Explicitly log latest candle and verify staleness
        if cleaned_candles:
            latest_c = cleaned_candles[-1]
            staleness = check_data_staleness(cleaned_candles, symbol=symbol, timeframe=timeframe)
            log_latest_candle(
                latest_c,
                symbol=symbol,
                timeframe=timeframe,
                context="INGESTION",
                is_fresh=not staleness.is_stale,
            )
            if staleness.is_stale:
                logger.warning(staleness.message)

        return IngestionReport(
            symbol=symbol,
            timeframe=timeframe,
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            skipped_duplicates_count=intra_duplicates + db_duplicates,
            invalid_candles_count=0,
            gaps_detected=gaps,
            start_time=cleaned_candles[0].timestamp if cleaned_candles else None,
            end_time=cleaned_candles[-1].timestamp if cleaned_candles else None,
        )

    async def sync_symbol_timeframe(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        force_refresh: bool = False,
    ) -> IngestionReport:
        """Fetch candles from provider and ingest into database with smart freshness cache and defensive 0-candle handling."""
        # ── Smart Freshness Cache Gate ────────────────────────────────────────────
        # When no explicit historical window is specified and not forcing refresh, check if DB already has the latest closed candle.
        if start_time is None and end_time is None and not force_refresh:
            try:
                latest_candle = self.db.scalars(
                    select(Candle)
                    .where(Candle.symbol == symbol, Candle.timeframe == timeframe.lower())
                    .order_by(desc(Candle.timestamp))
                    .limit(1)
                ).first()

                if latest_candle is not None:
                    tf_delta: timedelta = self.get_timeframe_delta(timeframe)
                    latest_ts: datetime = ensure_utc_datetime(latest_candle.timestamp)
                    next_candle_close: datetime = latest_ts + tf_delta
                    now_utc: datetime = datetime.now(timezone.utc)

                    if now_utc < next_candle_close:
                        logger.info(f"Skipping API fetch for {symbol} {timeframe} - Data is fresh.")
                        return IngestionReport(
                            symbol=symbol,
                            timeframe=timeframe,
                            fetched_count=0,
                            inserted_count=0,
                            skipped_duplicates_count=0,
                            invalid_candles_count=0,
                            gaps_detected=[],
                            start_time=latest_ts,
                            end_time=latest_ts,
                        )
            except Exception as cache_err:
                logger.warning(
                    f"Cache freshness check failed for {symbol} [{timeframe}] — "
                    f"falling back to API fetch: {cache_err}"
                )

        # ── Provider API Fetch Path ───────────────────────────────────────────────
        try:
            candles = await self.provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            if not candles:
                logger.warning(
                    f"Market data provider returned 0 candles for {symbol} [{timeframe}]. "
                    f"Attempting fallback to YahooFinanceProvider..."
                )
                from app.services.market_data.yfinance_provider import YahooFinanceProvider
                fallback_provider = YahooFinanceProvider()
                candles = await fallback_provider.fetch_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )

            if not candles:
                logger.warning(
                    f"All market data providers returned 0 candles for {symbol} [{timeframe}]. "
                    f"Ingestion cycle skipped defensively."
                )
            return self.ingest_candles(candles, symbol, timeframe)
        except Exception as e:
            logger.error(f"Ingestion sync failed for {symbol} [{timeframe}]: {e}", exc_info=True)
            try:
                from app.services.market_data.yfinance_provider import YahooFinanceProvider
                fallback_provider = YahooFinanceProvider()
                candles = await fallback_provider.fetch_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )
                if candles:
                    return self.ingest_candles(candles, symbol, timeframe)
            except Exception as fb_e:
                logger.error(f"Fallback ingestion failed for {symbol} [{timeframe}]: {fb_e}")

            return IngestionReport(
                symbol=symbol,
                timeframe=timeframe,
                fetched_count=0,
                inserted_count=0,
                skipped_duplicates_count=0,
                invalid_candles_count=0,
                gaps_detected=[],
            )

    def get_fresh_candles_from_db(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        only_closed: bool = True,
        as_of: Optional[datetime] = None,
    ) -> List[Candle]:
        """Query fresh candles from the database, selecting verified closed bars and validating staleness."""
        ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe.lower())
            .order_by(desc(Candle.timestamp))
            .limit(limit + 5)
        )
        records = list(self.db.scalars(stmt).all())
        records.reverse()

        if only_closed and records:
            records = filter_closed_candles(records, timeframe=timeframe, as_of=ref_time)

        if len(records) > limit:
            records = records[-limit:]

        if records:
            latest = records[-1]
            staleness = check_data_staleness(records, symbol=symbol, timeframe=timeframe, as_of=ref_time)
            log_latest_candle(
                latest,
                symbol=symbol,
                timeframe=timeframe,
                context="DB CANDLE RETRIEVAL",
                is_fresh=not staleness.is_stale,
            )
            if staleness.is_stale:
                logger.warning(staleness.message)

        return records
