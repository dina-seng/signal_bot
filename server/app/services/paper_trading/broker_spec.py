"""Broker-specific lot specifications for paper-trading position sizing."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Dict, Optional


@dataclass(frozen=True)
class BrokerSpec:
    """Contract/lot conventions used to convert a risk budget into lots."""

    name: str
    contract_size: Decimal
    min_lot: Decimal
    lot_step: Decimal
    currency: str = "USD"

    def floor_lots(self, raw_lots: Decimal) -> Decimal:
        """Floor raw lots onto the broker lot grid — never round up."""
        steps = (raw_lots / self.lot_step).to_integral_value(rounding=ROUND_FLOOR)
        return steps * self.lot_step


# Default profile preserves the current paper-venue behaviour exactly.
BROKER_SPECS: Dict[str, BrokerSpec] = {
    "exness_standard_xauusd": BrokerSpec(
        name="exness_standard_xauusd",
        contract_size=Decimal("100"),
        min_lot=Decimal("0.01"),
        lot_step=Decimal("0.01"),
        currency="USD",
    ),
    "theoretical_fractional": BrokerSpec(
        name="theoretical_fractional",
        contract_size=Decimal("100"),
        min_lot=Decimal("0.0001"),
        lot_step=Decimal("0.0001"),
        currency="USD",
    ),
}

DEFAULT_BROKER_SPEC_NAME = "exness_standard_xauusd"


def get_broker_spec(name: Optional[str] = None) -> BrokerSpec:
    """Resolve a profile by name; unknown names fail fast."""
    key = (name or DEFAULT_BROKER_SPEC_NAME).strip()
    if key not in BROKER_SPECS:
        raise ValueError(
            f"Unknown broker spec '{key}'. Available: {sorted(BROKER_SPECS)}"
        )
    return BROKER_SPECS[key]
