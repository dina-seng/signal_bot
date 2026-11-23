"""Risk Management and Position Sizing Calculator."""

from decimal import Decimal
from typing import Optional
from app.core.config import settings
from app.core.logging import logger
from app.schemas.signal import RiskParameters, SignalDirection
from app.services.market_data.symbols import (
    UnknownSymbolError,
    get_instrument_spec,
    normalize_symbol,
)



class RiskManager:
    """Calculates Stop Loss, Take Profit targets (TP1 & TP2), R:R ratios, and exact Lot Size."""

    @staticmethod
    def get_pip_size(symbol: str) -> float:
        """Get currency pip multiplier from centralized instrument specifications."""
        try:
            return get_instrument_spec(symbol).pip_size
        except UnknownSymbolError:
            s = symbol.upper().replace("%2F", "/").strip()
            if "JPY" in s:
                return 0.01
            return 0.0001

    @staticmethod
    def get_pip_value_per_lot(symbol: str, current_price: float = 1.0) -> float:
        """Returns USD value per pip for 1 standard lot from centralized specifications."""
        try:
            return get_instrument_spec(symbol).point_value_per_lot
        except UnknownSymbolError:
            return 10.0

    def calculate_trade_risk(
        self,
        symbol: str,
        direction: SignalDirection,
        entry_price: float,
        atr_value: Optional[float] = None,
        key_support_low: Optional[float] = None,
        key_resistance_high: Optional[float] = None,
        account_balance: Optional[float] = None,
        risk_percent: Optional[float] = None,
        min_rr: Optional[float] = None,
    ) -> RiskParameters:
        """Compute Stop Loss, Take Profits (TP1 & TP2), R:R, and suggested lot size."""
        balance = account_balance or 10000.0
        risk_pct = risk_percent or settings.MAX_RISK_PERCENT
        req_rr_tp1 = min_rr or settings.MIN_RR_TP1
        req_rr_tp2 = settings.MIN_RR_TP2
        pip_size = self.get_pip_size(symbol)

        # Base ATR buffer fallback if ATR is missing
        default_atr = entry_price * 0.0015
        effective_atr = atr_value if (atr_value is not None and atr_value > 0) else default_atr
        
        # Cap maximum structural distance to prevent macro-level SLs
        try:
            canonical = normalize_symbol(symbol)
        except UnknownSymbolError:
            canonical = symbol.upper()

        if canonical == "XAU/USD":
            max_sl_pips = 2500.0
        elif canonical == "USD/JPY":
            max_sl_pips = 120.0
        else:
            max_sl_pips = 100.0

        max_structural_distance = max_sl_pips * pip_size

        if direction == SignalDirection.BUY:
            if key_support_low is not None and key_support_low < entry_price:
                if (entry_price - key_support_low) > max_structural_distance:
                    logger.warning(
                        f"Structural support {key_support_low} is too far from entry {entry_price} "
                        f"(>{max_sl_pips:.0f} pips). Falling back to ATR-based SL."
                    )
                    stop_loss = entry_price - (effective_atr * 1.5)
                else:
                    stop_loss = key_support_low - (effective_atr * 0.5)
            else:
                stop_loss = entry_price - (effective_atr * 1.5)

            if stop_loss >= entry_price:
                stop_loss = entry_price - (effective_atr * 1.5)

            risk_price = entry_price - stop_loss
            tp1 = entry_price + (risk_price * req_rr_tp1)
            tp2 = entry_price + (risk_price * req_rr_tp2)

        else:  # SELL
            if key_resistance_high is not None and key_resistance_high > entry_price:
                if (key_resistance_high - entry_price) > max_structural_distance:
                    logger.warning(
                        f"Structural resistance {key_resistance_high} is too far from entry {entry_price} "
                        f"(>{max_sl_pips:.0f} pips). Falling back to ATR-based SL."
                    )
                    stop_loss = entry_price + (effective_atr * 1.5)
                else:
                    stop_loss = key_resistance_high + (effective_atr * 0.5)
            else:
                stop_loss = entry_price + (effective_atr * 1.5)

            if stop_loss <= entry_price:
                stop_loss = entry_price + (effective_atr * 1.5)

            risk_price = stop_loss - entry_price
            tp1 = entry_price - (risk_price * req_rr_tp1)
            tp2 = entry_price - (risk_price * req_rr_tp2)

        risk_pips = round(risk_price / pip_size, 1)
        reward_pips_tp1 = round(abs(tp1 - entry_price) / pip_size, 1)
        reward_pips_tp2 = round(abs(tp2 - entry_price) / pip_size, 1)

        rr_tp1 = round(reward_pips_tp1 / max(1e-6, risk_pips), 2)
        rr_tp2 = round(reward_pips_tp2 / max(1e-6, risk_pips), 2)

        # Local import avoids a signals <-> paper_trading package import cycle.
        from app.services.paper_trading.broker_spec import get_broker_spec

        # Position Sizing: raw volume is separate from executable volume.
        risk_amount_usd = round(balance * (risk_pct / 100.0), 2)
        pip_val = self.get_pip_value_per_lot(symbol)
        spec = get_broker_spec(settings.BROKER_SPEC)
        contract = (
            Decimal(str(spec.contract_size))
            if canonical == "XAU/USD"
            else Decimal(str(pip_val / pip_size))
        )
        raw_lots = (
            Decimal(str(risk_amount_usd))
            / (Decimal(str(risk_price)) * contract)
            if risk_price > 0
            else Decimal("0")
        )
        executable = spec.floor_lots(raw_lots)
        is_executable = executable >= spec.min_lot
        suggested_lots = float(executable) if is_executable else 0.0
        min_lot_risk_usd = float(spec.min_lot * contract * Decimal(str(risk_price)))

        return RiskParameters(
            entry_price=round(entry_price, 5),
            stop_loss=round(stop_loss, 5),
            take_profit_1=round(tp1, 5),
            take_profit_2=round(tp2, 5),
            risk_pips=risk_pips,
            reward_pips_tp1=reward_pips_tp1,
            reward_pips_tp2=reward_pips_tp2,
            risk_reward_tp1=rr_tp1,
            risk_reward_tp2=rr_tp2,
            account_balance=balance,
            risk_percent=risk_pct,
            risk_amount_usd=risk_amount_usd,
            suggested_lot_size=suggested_lots,
            raw_lot_size=float(raw_lots),
            is_executable=is_executable,
            min_lot_risk_usd=min_lot_risk_usd,
            volume_step=float(spec.lot_step),
        )
