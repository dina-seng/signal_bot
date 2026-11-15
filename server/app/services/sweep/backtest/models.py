"""Data models for Liquidity-Sweep Backtest Harness."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import json


@dataclass
class TradePosition:
    """Executed trade position during historical simulation."""
    position_id: int
    setup_id: str
    symbol: str
    direction: str  # "LONG" or "SHORT"
    grade: Optional[str]
    pool_type: str
    session: str  # "Asia", "London", "NY", "Other"
    htf_aligned: bool
    day_of_week: str  # "Monday" .. "Friday"
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    initial_risk_usd: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = "OPEN"  # "TP1", "TP2", "SL", "END_OF_DATA"
    r_multiple: float = 0.0
    pnl_usd: float = 0.0
    friction_usd: float = 0.0
    friction_r: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    bars_held: int = 0


@dataclass
class CandidateSetupRecord:
    """Record of every candidate setup evaluated (both executed and skipped/unqualified)."""
    setup_id: str
    symbol: str
    direction: str
    timestamp: datetime
    state: str
    grade: Optional[str]
    pool_id: str
    pool_type: str
    pool_price: float
    sweep_extreme: float
    skip_reason: Optional[str] = None
    was_executed: bool = False
    reached_1r: bool = False
    reached_2r: bool = False
    hit_sl: bool = False
    mfe: float = 0.0
    mae: float = 0.0
    bars_to_resolution: int = 0
    r_multiple: float = 0.0


@dataclass
class SliceMetrics:
    """Statistical performance metrics for a specific slice/subset of trades."""
    slice_name: str
    n_signals: int = 0
    n_executed: int = 0
    n_deduped: int = 0
    win_rate: Optional[float] = None
    expectancy_r: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    avg_friction_r: Optional[float] = None
    has_edge: bool = False
    verdict: str = "n/a (n<30)"


@dataclass
class BacktestReport:
    """Comprehensive backtest report container."""
    split_name: str
    start_date: datetime
    end_date: datetime
    total_bars: int
    overall_metrics: SliceMetrics
    grade_breakdown: Dict[str, SliceMetrics] = field(default_factory=dict)
    session_breakdown: Dict[str, SliceMetrics] = field(default_factory=dict)
    htf_alignment_breakdown: Dict[str, SliceMetrics] = field(default_factory=dict)
    pool_type_breakdown: Dict[str, SliceMetrics] = field(default_factory=dict)
    day_of_week_breakdown: Dict[str, SliceMetrics] = field(default_factory=dict)
    monthly_equity: Dict[str, float] = field(default_factory=dict)
    random_baseline_metrics: Optional[SliceMetrics] = None
    executed_trades: List[TradePosition] = field(default_factory=list)
    candidates: List[CandidateSetupRecord] = field(default_factory=list)
    raw_config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
