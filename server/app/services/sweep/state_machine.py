"""Setup State Machine, Stable Setup ID Generation, Structured Checklist, and Quality Grading."""

from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib
from typing import Any, Dict, Optional

from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.detector import EntryZone, SetupPlan, SweepEvent


class SetupState:
    POTENTIAL = "POTENTIAL"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    NO_SETUP = "NO_SETUP"


@dataclass
class SetupChecklist:
    """Structured checklist storing verifiable criteria instead of free text."""
    valid_sweep_penetration: bool
    rejected_within_max_bars: bool
    mss_displacement_confirmed: bool
    fvg_or_ob_zone_formed: bool
    premium_discount_satisfied: bool
    risk_reward_ge_minimum: bool
    htf_aligned: bool
    is_major_pool: bool
    strong_displacement: bool
    in_kill_zone: bool
    has_clean_fvg: bool
    risk_reward_ge_2: bool


@dataclass
class SweepSetup:
    """Complete representation of a liquidity sweep setup."""
    setup_id: str
    symbol: str
    direction: str                     # 'SHORT' or 'LONG'
    state: str                         # POTENTIAL, WAITING_CONFIRMATION, CONFIRMED, INVALIDATED, NO_SETUP
    grade: Optional[str]               # 'A', 'B', 'C' (when CONFIRMED)
    quality_score: int                 # 0 to 6 count of quality features
    pool_id: str
    pool_type: str
    pool_price: float
    sweep_bar_time: datetime
    sweep_extreme: float
    as_of: datetime
    plan: Optional[SetupPlan]
    zone: Optional[EntryZone]
    checklist: SetupChecklist
    invalidation_reason: Optional[str] = None
    no_setup_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["sweep_bar_time"] = self.sweep_bar_time.isoformat()
        d["as_of"] = self.as_of.isoformat()
        return d


def build_setup_id(symbol: str, direction: str, pool_id: str, sweep_bar_time: datetime) -> str:
    """Deterministic, collision-resistant setup fingerprint hash."""
    ts_str = sweep_bar_time.isoformat()
    raw = f"{symbol.upper()}_{direction.upper()}_{pool_id}_{ts_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def assign_grade(checklist: SetupChecklist) -> str:
    """Grade A/B/C assignment based strictly on count of passing quality features.

    Quality Features:
    1. HTF aligned
    2. Swept pool is major (session / PDH-PDL / equal-level)
    3. Strong displacement (>= 1.2 * ATR)
    4. Sweep during kill-zone window
    5. FVG fully formed
    6. RR >= 2.0
    """
    quality_count = (
        int(checklist.htf_aligned)
        + int(checklist.is_major_pool)
        + int(checklist.strong_displacement)
        + int(checklist.in_kill_zone)
        + int(checklist.has_clean_fvg)
        + int(checklist.risk_reward_ge_2)
    )

    if quality_count >= 4:
        return "A"
    elif quality_count >= 2:
        return "B"
    else:
        return "C"
