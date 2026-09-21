"""Path Validation Service — Obstacle Detection between Entry and Take Profit.

Scans for structural barriers (Support/Resistance zones, Fair Value Gaps,
Liquidity Pools) that sit between the trade entry and target price.
If an obstacle is found, the nearest blocking price is returned so
the caller can adjust the TP or reject the trade.
"""

from dataclasses import dataclass
from typing import List, Optional

from app.core.logging import logger
from app.schemas.indicators import FairValueGap, FVGType
from app.schemas.liquidity import (
    LiquidityEventType,
    LiquidityPool,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.signal import SignalDirection


@dataclass
class PathValidationResult:
    """Result of obstacle detection between entry and target price."""

    is_clear: bool
    """True if no structural obstacles found on the path to the target."""

    nearest_obstacle_price: Optional[float] = None
    """Price of the closest obstacle blocking the path (None if clear)."""

    obstacle_type: Optional[str] = None
    """Human-readable label of the nearest obstacle, e.g. 'Resistance Zone', 'Bearish FVG'."""

    obstacle_count: int = 0
    """Total number of structural obstacles found on the path to target."""


class PathValidator:
    """Detects structural obstacles between a trade's entry and take-profit target.

    For BUY trades, looks for bearish obstacles (Resistance zones, Bearish FVGs,
    Buy-Side Liquidity / Equal Highs) sitting between entry and TP.
    For SELL trades, looks for bullish obstacles (Support zones, Bullish FVGs,
    Sell-Side Liquidity / Equal Lows) sitting between entry and TP.
    """

    def validate_trade_path(
        self,
        direction: SignalDirection,
        entry_price: float,
        target_price: float,
        sr_zones: List[SupportResistanceZone],
        active_fvgs: List[FairValueGap],
        liquidity_pools: List[LiquidityPool],
    ) -> PathValidationResult:
        """Check if the price path from entry to target is free of structural obstacles.

        Args:
            direction: Trade direction (BUY or SELL).
            entry_price: Trade entry price.
            target_price: Take-profit target price.
            sr_zones: Active Support/Resistance zones from structure analysis.
            active_fvgs: Active (unmitigated) Fair Value Gaps from indicator analysis.
            liquidity_pools: Equal Highs/Lows liquidity pools from structure analysis.

        Returns:
            PathValidationResult with obstacle details if the path is blocked.
        """
        if direction == SignalDirection.WAIT:
            return PathValidationResult(is_clear=True)

        obstacles: List[tuple[float, str]] = []

        if direction == SignalDirection.BUY:
            obstacles.extend(self._find_bearish_sr_obstacles(entry_price, target_price, sr_zones))
            obstacles.extend(self._find_bearish_fvg_obstacles(entry_price, target_price, active_fvgs))
            obstacles.extend(self._find_buyside_liquidity_obstacles(entry_price, target_price, liquidity_pools))
        else:  # SELL
            obstacles.extend(self._find_bullish_sr_obstacles(entry_price, target_price, sr_zones))
            obstacles.extend(self._find_bullish_fvg_obstacles(entry_price, target_price, active_fvgs))
            obstacles.extend(self._find_sellside_liquidity_obstacles(entry_price, target_price, liquidity_pools))

        if not obstacles:
            logger.debug(
                f"PATH CLEAR: No obstacles detected between entry={entry_price:.5f} "
                f"and target={target_price:.5f} for {direction.value}."
            )
            return PathValidationResult(is_clear=True)

        # Find the nearest obstacle to entry (first one price would encounter)
        if direction == SignalDirection.BUY:
            # For BUY, nearest = lowest price above entry
            obstacles.sort(key=lambda x: x[0])
        else:
            # For SELL, nearest = highest price below entry
            obstacles.sort(key=lambda x: x[0], reverse=True)

        nearest_price, nearest_type = obstacles[0]

        logger.info(
            f"⚠️ PATH BLOCKED: {nearest_type} at {nearest_price:.5f} "
            f"between entry={entry_price:.5f} and target={target_price:.5f} ({direction.value}). "
            f"Total obstacles found: {len(obstacles)}."
        )

        return PathValidationResult(
            is_clear=False,
            nearest_obstacle_price=nearest_price,
            obstacle_type=nearest_type,
            obstacle_count=len(obstacles),
        )

    # ─── Bearish Obstacles (block BUY trades) ────────────────────────

    @staticmethod
    def _find_bearish_sr_obstacles(
        entry: float, target: float, zones: List[SupportResistanceZone]
    ) -> List[tuple[float, str]]:
        """Find RESISTANCE zones sitting between entry and target (above entry, below target)."""
        results = []
        for z in zones:
            if z.zone_type != ZoneType.RESISTANCE:
                continue
            if not z.is_fresh:
                continue
            # Zone center must be above entry and below (or at) target
            if entry < z.center_price <= target:
                results.append((z.center_price, f"Resistance Zone ({z.strength:.0%} strength)"))
        return results

    @staticmethod
    def _find_bearish_fvg_obstacles(
        entry: float, target: float, fvgs: List[FairValueGap]
    ) -> List[tuple[float, str]]:
        """Find unmitigated BEARISH FVGs between entry and target."""
        results = []
        for fvg in fvgs:
            if fvg.fvg_type != FVGType.BEARISH_FVG:
                continue
            if fvg.is_mitigated:
                continue
            # Bearish FVG sits above — its bottom_price is the key level price reacts to
            if entry < fvg.bottom_price <= target:
                results.append((fvg.bottom_price, f"Bearish FVG ({fvg.gap_pips:.1f} pips)"))
        return results

    @staticmethod
    def _find_buyside_liquidity_obstacles(
        entry: float, target: float, pools: List[LiquidityPool]
    ) -> List[tuple[float, str]]:
        """Find unswept Equal Highs (buy-side liquidity) between entry and target."""
        results = []
        for pool in pools:
            if pool.pool_type != LiquidityEventType.EQUAL_HIGHS:
                continue
            if pool.is_swept:
                continue
            if entry < pool.price_level <= target:
                results.append((pool.price_level, f"Equal Highs Liquidity ({pool.touch_points} touches)"))
        return results

    # ─── Bullish Obstacles (block SELL trades) ────────────────────────

    @staticmethod
    def _find_bullish_sr_obstacles(
        entry: float, target: float, zones: List[SupportResistanceZone]
    ) -> List[tuple[float, str]]:
        """Find SUPPORT zones sitting between entry and target (below entry, above target)."""
        results = []
        for z in zones:
            if z.zone_type != ZoneType.SUPPORT:
                continue
            if not z.is_fresh:
                continue
            # Zone center must be below entry and above (or at) target
            if target <= z.center_price < entry:
                results.append((z.center_price, f"Support Zone ({z.strength:.0%} strength)"))
        return results

    @staticmethod
    def _find_bullish_fvg_obstacles(
        entry: float, target: float, fvgs: List[FairValueGap]
    ) -> List[tuple[float, str]]:
        """Find unmitigated BULLISH FVGs between entry and target."""
        results = []
        for fvg in fvgs:
            if fvg.fvg_type != FVGType.BULLISH_FVG:
                continue
            if fvg.is_mitigated:
                continue
            # Bullish FVG sits below — its top_price is the key level
            if target <= fvg.top_price < entry:
                results.append((fvg.top_price, f"Bullish FVG ({fvg.gap_pips:.1f} pips)"))
        return results

    @staticmethod
    def _find_sellside_liquidity_obstacles(
        entry: float, target: float, pools: List[LiquidityPool]
    ) -> List[tuple[float, str]]:
        """Find unswept Equal Lows (sell-side liquidity) between entry and target."""
        results = []
        for pool in pools:
            if pool.pool_type != LiquidityEventType.EQUAL_LOWS:
                continue
            if pool.is_swept:
                continue
            if target <= pool.price_level < entry:
                results.append((pool.price_level, f"Equal Lows Liquidity ({pool.touch_points} touches)"))
        return results
