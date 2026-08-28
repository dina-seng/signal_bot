"""Dynamic Support/Resistance Zones and Resting Liquidity Pools (Equal Highs/Lows) Detector."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.liquidity import (
    LiquidityEventType,
    LiquidityPool,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.structure import SwingPoint, SwingType


class SupportResistanceDetector:
    """Detects dynamic S/R Zones and Resting Liquidity Pools (Equal Highs / Equal Lows) from swing clusters."""

    def __init__(self, default_tolerance_percent: float = 0.10):
        self.default_tolerance_percent = default_tolerance_percent

    @staticmethod
    def _extract_candle_data(candle: Any) -> tuple[datetime, float, float, float, float]:
        """Extract timestamp, open, high, low, close from candle."""
        if isinstance(candle, dict):
            ts = candle.get("timestamp")
            o = float(candle.get("open", 0.0))
            h = float(candle.get("high", 0.0))
            l = float(candle.get("low", 0.0))
            c = float(candle.get("close", 0.0))
        else:
            ts = getattr(candle, "timestamp")
            o = float(getattr(candle, "open"))
            h = float(getattr(candle, "high"))
            l = float(getattr(candle, "low"))
            c = float(getattr(candle, "close"))

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        return ts, o, h, l, c

    def _cluster_swings(
        self,
        swings: List[SwingPoint],
        tolerance_percent: float,
    ) -> List[List[SwingPoint]]:
        """Cluster swing points that fall within tolerance percentage of each other."""
        if not swings:
            return []

        # Sort swings by price
        sorted_by_price = sorted(swings, key=lambda s: s.price)
        clusters: List[List[SwingPoint]] = []
        current_cluster: List[SwingPoint] = [sorted_by_price[0]]

        for i in range(1, len(sorted_by_price)):
            s = sorted_by_price[i]
            ref_price = current_cluster[0].price
            rel_diff = abs(s.price - ref_price) / ref_price

            if rel_diff <= (tolerance_percent / 100.0):
                current_cluster.append(s)
            else:
                clusters.append(current_cluster)
                current_cluster = [s]

        if current_cluster:
            clusters.append(current_cluster)

        return clusters

    def detect_sr_zones_and_pools(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        swings: List[SwingPoint],
        tolerance_percent: Optional[float] = None,
    ) -> tuple[List[SupportResistanceZone], List[LiquidityPool]]:
        """Detect Support/Resistance Zones and Equal High/Low Liquidity Pools.

        Args:
            candles: Sequence of historical candles.
            swings: Labeled SwingPoints.
            tolerance_percent: Grouping tolerance percentage (e.g. 0.10%).

        Returns:
            Tuple of (sr_zones_list, liquidity_pools_list)
        """
        tol = tolerance_percent if tolerance_percent is not None else self.default_tolerance_percent
        parsed_candles = [self._extract_candle_data(c) for c in candles] if candles else []

        swing_highs = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
        swing_lows = [s for s in swings if s.swing_type == SwingType.SWING_LOW]

        high_clusters = self._cluster_swings(swing_highs, tolerance_percent=tol)
        low_clusters = self._cluster_swings(swing_lows, tolerance_percent=tol)

        sr_zones: List[SupportResistanceZone] = []
        liquidity_pools: List[LiquidityPool] = []

        # 1. Process Resistance Clusters & Equal Highs
        for cluster in high_clusters:
            prices = [s.price for s in cluster]
            timestamps = [s.timestamp for s in cluster]
            touch_count = len(cluster)
            avg_price = sum(prices) / touch_count
            min_p = min(prices)
            max_p = max(prices)
            first_ts = min(timestamps)
            last_ts = max(timestamps)

            # Zone boundary with a tiny buffer
            buffer = avg_price * 0.0003
            zone_low = min_p - buffer
            zone_high = max_p + buffer

            # Check if breached / fresh
            is_fresh = True
            is_swept = False
            if parsed_candles:
                # Find candles after the first touch
                for ts, o, h, l, c in parsed_candles:
                    if ts > last_ts:
                        # Breached if candle closed cleanly above zone high
                        if c > zone_high:
                            is_fresh = False
                        # Swept if wicked above max price
                        if h > max_p:
                            is_swept = True

            strength = round(min(1.0, 0.4 + (touch_count * 0.15)), 2)

            sr_zones.append(
                SupportResistanceZone(
                    zone_type=ZoneType.RESISTANCE,
                    price_low=round(zone_low, 5),
                    price_high=round(zone_high, 5),
                    center_price=round(avg_price, 5),
                    touch_count=touch_count,
                    strength=strength,
                    is_fresh=is_fresh,
                    last_touch_timestamp=last_ts,
                )
            )

            if touch_count >= 2:
                liquidity_pools.append(
                    LiquidityPool(
                        pool_type=LiquidityEventType.EQUAL_HIGHS,
                        price_level=round(avg_price, 5),
                        touch_points=touch_count,
                        first_timestamp=first_ts,
                        last_timestamp=last_ts,
                        is_swept=is_swept,
                    )
                )

        # 2. Process Support Clusters & Equal Lows
        for cluster in low_clusters:
            prices = [s.price for s in cluster]
            timestamps = [s.timestamp for s in cluster]
            touch_count = len(cluster)
            avg_price = sum(prices) / touch_count
            min_p = min(prices)
            max_p = max(prices)
            first_ts = min(timestamps)
            last_ts = max(timestamps)

            buffer = avg_price * 0.0003
            zone_low = min_p - buffer
            zone_high = max_p + buffer

            is_fresh = True
            is_swept = False
            if parsed_candles:
                for ts, o, h, l, c in parsed_candles:
                    if ts > last_ts:
                        # Breached if candle closed cleanly below zone low
                        if c < zone_low:
                            is_fresh = False
                        # Swept if wicked below min price
                        if l < min_p:
                            is_swept = True

            strength = round(min(1.0, 0.4 + (touch_count * 0.15)), 2)

            sr_zones.append(
                SupportResistanceZone(
                    zone_type=ZoneType.SUPPORT,
                    price_low=round(zone_low, 5),
                    price_high=round(zone_high, 5),
                    center_price=round(avg_price, 5),
                    touch_count=touch_count,
                    strength=strength,
                    is_fresh=is_fresh,
                    last_touch_timestamp=last_ts,
                )
            )

            if touch_count >= 2:
                liquidity_pools.append(
                    LiquidityPool(
                        pool_type=LiquidityEventType.EQUAL_LOWS,
                        price_level=round(avg_price, 5),
                        touch_points=touch_count,
                        first_timestamp=first_ts,
                        last_timestamp=last_ts,
                        is_swept=is_swept,
                    )
                )

        # Sort zones by price
        sr_zones.sort(key=lambda z: z.center_price, reverse=True)
        return sr_zones, liquidity_pools
