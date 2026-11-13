"""Risk Management and Position Sizing Calculator."""

from typing import Optional
from app.core.config import ACTIVE_SYMBOLS, settings
from app.core.logging import logger
from app.schemas.signal import RiskParameters, SignalDirection


class RiskManager:
    """Calculates Stop Loss, Take Profit targets (TP1 & TP2), R:R ratios, and exact Lot Size."""

    @staticmethod
    def get_pip_size(symbol: str) -> float:
        """Get currency pip multiplier."""
        s = symbol.upper().replace("%2F", "/").strip()
        if "XAU" in s or "GOLD" in s or s in ACTIVE_SYMBOLS:
            return 0.01  # Gold: minimum tick is 0.01 (1 pip = $1 on 100 oz lot)
        if "JPY" in s:
            return 0.01
        return 0.0001

    @staticmethod
    def get_pip_value_per_lot(symbol: str, current_price: float = 1.0) -> float:
        """
        Returns USD value per pip for 1 standard lot.

        XAU/USD : 100 oz contract, pip=0.01  → $1.00 per pip per lot
                  (100 oz × $0.01 = $1.00)
        FX USD-quote: $10.00 per pip per standard lot
        """
        s = symbol.upper().replace("%2F", "/").strip()
        if "XAU" in s or "GOLD" in s or s in ACTIVE_SYMBOLS:
            return 1.0   # 100 oz × 0.01 pip = $1.00
        # FX pairs
        if "/" in s:
            base, quote = s.split("/", 1)
        else:
            base, quote = s[:3], s[3:]
        if quote == "USD":
            return 10.0
        elif base == "USD":
            return 10.0 / current_price if current_price > 0 else 10.0
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
        req_rr = min_rr or settings.MIN_RR
        pip_size = self.get_pip_size(symbol)

        # Base ATR buffer fallback if ATR is missing
        default_atr = entry_price * 0.0015
        effective_atr = atr_value if (atr_value is not None and atr_value > 0) else default_atr
        
        # 🛡️ SANITY CHECK: Cap maximum structural distance to prevent macro-level SLs
        # XAU/USD: 2500 pips ($25.00), US100: 500 index points ($500), JPY: 120 pips, standard FX: 100 pips
        s_upper = symbol.upper().replace("%2F", "/").strip()
        if "XAU" in s_upper or "GOLD" in s_upper or s_upper in ACTIVE_SYMBOLS:
            max_sl_pips = 2500.0
        elif "JPY" in s_upper:
            max_sl_pips = 120.0
        else:
            max_sl_pips = 100.0

        max_structural_distance = max_sl_pips * pip_size

        if direction == SignalDirection.BUY:
            if key_support_low is not None and key_support_low < entry_price:
                # Check if the structural support is unreasonably far away
                if (entry_price - key_support_low) > max_structural_distance:
                    logger.warning(f"Structural support {key_support_low} is too far from entry {entry_price} (>{max_sl_pips:.0f} pips). Falling back to ATR-based SL.")
                    stop_loss = entry_price - (effective_atr * 1.5)
                else:
                    stop_loss = key_support_low - (effective_atr * 0.5) # atr_buffer
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
                # Check if the structural resistance is unreasonably far away
                if (key_resistance_high - entry_price) > max_structural_distance:
                    logger.warning(f"Structural resistance {key_resistance_high} is too far from entry {entry_price} (>{max_sl_pips:.0f} pips). Falling back to ATR-based SL.")
                    stop_loss = entry_price + (effective_atr * 1.5)
                else:
                    stop_loss = key_resistance_high + (effective_atr * 0.5) # atr_buffer
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
