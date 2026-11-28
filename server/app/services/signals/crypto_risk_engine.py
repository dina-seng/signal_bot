"""Crypto-specific volatility risk engine for BTC/USD.

Extends the single ``RiskEngine`` SL/TP actor with an ATR-based stop for
BTC/USD. All other symbols (notably XAU/USD) are delegated to the base
implementation unchanged, so the existing SMC pipeline keeps its 15m
structural stops, bounds and sizing behaviour.
"""

from decimal import Decimal
from typing import Any, Optional, Sequence

from app.core.config import settings
from app.services.signals.risk_engine import RiskEngine, RiskLevels

BTC_SYMBOL: str = "BTC/USD"
# Validated sweep config (FINAL_ATR_MULTIPLIER in scripts/backtest_btc_momentum.py).
BTC_ATR_MULTIPLIER: float = 3.5
BTC_MIN_SL_DISTANCE: float = 100.0
BTC_MAX_SL_DISTANCE: float = 1500.0


class CryptoVolatilityRiskEngine(RiskEngine):
    """ATR(14)-driven SL/TP for BTC/USD; base RiskEngine for everything else."""

    def __init__(
        self,
        atr_multiplier: Optional[float] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Production default stays BTC_ATR_MULTIPLIER; research sweeps can pass
        # an explicit multiplier without mutating the module-level constant.
        self.atr_multiplier = (
            float(atr_multiplier)
            if atr_multiplier is not None
            else float(BTC_ATR_MULTIPLIER)
        )

    @classmethod
    def _sl_distance_bounds(cls, symbol: str) -> tuple[float, float]:
        """BTC stop distance bounds in USD price units; delegate other symbols."""
        if symbol == BTC_SYMBOL:
            return BTC_MIN_SL_DISTANCE, BTC_MAX_SL_DISTANCE
        return super()._sl_distance_bounds(symbol)

    def resolve_levels(
        self,
        *,
        symbol: str,
        direction: Any,
        entry_price: float,
        timeframe: str = "15m",
        candles: Optional[Sequence[Any]] = None,
        swings: Optional[Sequence[Any]] = None,
        balance: Optional[float] = None,
        risk_percent: Optional[float] = None,
    ) -> RiskLevels:
        """Place an ATR-based BTC stop/target; pass all other symbols through."""
        if symbol != BTC_SYMBOL:
            return super().resolve_levels(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                timeframe=timeframe,
                candles=candles,
                swings=swings,
                balance=balance,
                risk_percent=risk_percent,
            )

        side = self._direction_value(direction)
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Risk Engine requires BUY or SELL, got {side!r}.")

        entry = round(float(entry_price), 5)
        if entry <= 0:
            raise ValueError("Risk Engine requires a positive entry price.")

        tf = str(timeframe or "1h").lower().strip()
        atr = float(self._atr(candles, entry))
        min_dist, max_dist = self._sl_distance_bounds(symbol)

        # ATR-multiple stop, clamped into the per-instrument price-unit bounds.
        atr_distance = self.atr_multiplier * atr
        sl_distance = round(min(max(atr_distance, min_dist), max_dist), 5)
        if sl_distance <= 0:
            sl_distance = round(min_dist, 5)

        stop_loss = round(
            entry - sl_distance if side == "BUY" else entry + sl_distance, 5
        )
        # TP is derived from the FINAL (clamped) stop distance so the R:R stays exact.
        tp_distance = round(sl_distance * self.rr_multiple, 5)
        take_profit = round(
            entry + tp_distance if side == "BUY" else entry - tp_distance, 5
        )

        rpct = (
            risk_percent if risk_percent is not None else float(settings.MAX_RISK_PERCENT)
        )
        budget = (
            round(float(balance) * (float(rpct) / 100.0), 2)
            if balance is not None
            else 0.0
        )
        contract = self._contract_size(symbol)
        raw_lots = (
            budget / (sl_distance * contract) if sl_distance > 0 and contract > 0 else 0.0
        )
        floored_lots = float(self._spec.floor_lots(Decimal(str(raw_lots))))
        executable_lots = max(float(self._spec.min_lot), floored_lots)
        lot_size = self.lot_size if self._explicit_lot else executable_lots
        min_lot_risk = round(float(self._spec.min_lot) * contract * sl_distance, 2)

        return RiskLevels(
            symbol=symbol,
            direction=side,
            timeframe=tf,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=None,
            sl_distance=sl_distance,
            tp_distance=tp_distance,
            rr_multiple=self.rr_multiple,
            lot_size=lot_size,
            source=f"{tf}_atr_{self.atr_multiplier:g}x_btc",
            swing_count=0,  # BTC deliberately bypasses the 15m structural swing check
            risk_percent=float(rpct),
            risk_amount_usd=budget,
            min_lot_risk_usd=min_lot_risk,
            raw_lot_size=raw_lots,
        )
