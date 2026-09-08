"""Risk Management and Position Sizing Calculator."""

from typing import Optional
from app.core.config import settings
from app.schemas.signal import RiskParameters, SignalDirection


class RiskManager:
    """Calculates Stop Loss, Take Profit targets (TP1 & TP2), R:R ratios, and exact Lot Size."""

    @staticmethod
    def get_pip_size(symbol: str) -> float:
        """Get currency pip multiplier."""
        s = symbol.upper().replace("%2F", "/").strip()
        if "JPY" in s or "XAU" in s or "GOLD" in s:
            return 0.01
        return 0.0001

    @staticmethod
    def get_pip_value_per_lot(symbol: str) -> float:
        """Approximate USD value per pip for 1 standard lot (100,000 units)."""
        s = symbol.upper().replace("%2F", "/").strip()
        if "XAU" in s or "GOLD" in s:
            return 1.0  # 1 lot of gold (100 oz): 0.01 price move = $1.00
        return 10.0  # Standard FX pairs: 1 pip = $10.00 per standard lot

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
        """Compute Stop Loss, Take Profits (TP1 & TP2), R:R, and suggested lot size.

        Args:
            symbol: Forex instrument (e.g. 'EUR/USD').
            direction: BUY or SELL.
            entry_price: Current market price.
            atr_value: Current ATR in price units.
            key_support_low: Nearest structural swing/sweep support low.
            key_resistance_high: Nearest structural swing/sweep resistance high.
            account_balance: Account equity USD (default: 10,000).
            risk_percent: Risk percentage per trade (default: 0.5%).
            min_rr: Minimum Risk-Reward ratio (default: 2.0).

        Returns:
            RiskParameters object.
        """
        balance = account_balance or 10000.0
        risk_pct = risk_percent or settings.MAX_RISK_PERCENT
        req_rr = min_rr or settings.MIN_RR
        pip_size = self.get_pip_size(symbol)

        # Base ATR buffer fallback if ATR is missing
        default_atr = entry_price * 0.0015
        effective_atr = atr_value if (atr_value is not None and atr_value > 0) else default_atr
        atr_buffer = effective_atr * 0.5

        if direction == SignalDirection.BUY:
            if key_support_low is not None and key_support_low < entry_price:
                stop_loss = key_support_low - atr_buffer
            else:
                stop_loss = entry_price - (effective_atr * 1.5)

            # Ensure SL is strictly below Entry
            if stop_loss >= entry_price:
                stop_loss = entry_price - (effective_atr * 1.5)

            risk_price = entry_price - stop_loss
            tp1 = entry_price + (risk_price * req_rr)
            tp2 = entry_price + (risk_price * (req_rr + 1.0))

        else:  # SELL
            if key_resistance_high is not None and key_resistance_high > entry_price:
                stop_loss = key_resistance_high + atr_buffer
            else:
                stop_loss = entry_price + (effective_atr * 1.5)

            # Ensure SL is strictly above Entry
            if stop_loss <= entry_price:
                stop_loss = entry_price + (effective_atr * 1.5)

            risk_price = stop_loss - entry_price
            tp1 = entry_price - (risk_price * req_rr)
            tp2 = entry_price - (risk_price * (req_rr + 1.0))

        risk_pips = round(risk_price / pip_size, 1)
        reward_pips_tp1 = round(abs(tp1 - entry_price) / pip_size, 1)
        reward_pips_tp2 = round(abs(tp2 - entry_price) / pip_size, 1)

        rr_tp1 = round(reward_pips_tp1 / max(1e-6, risk_pips), 2)
        rr_tp2 = round(reward_pips_tp2 / max(1e-6, risk_pips), 2)

        # Position Sizing
        risk_amount_usd = round(balance * (risk_pct / 100.0), 2)
        pip_val = self.get_pip_value_per_lot(symbol)
        raw_lots = risk_amount_usd / max(1e-6, risk_pips * pip_val)
        suggested_lots = round(max(0.01, min(100.0, raw_lots)), 2)

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
        )
