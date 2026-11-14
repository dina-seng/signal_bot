"""Signal Candidate entity for logging all evaluated trade setups and tracking outcome labels."""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Index,
)
from app.core.database import Base
from app.models.base import utc_now


class SignalCandidate(Base):
    """Logs EVERY signal candidate (qualified and unqualified) with full feature attribution and forward outcome labels."""
    __tablename__ = "signal_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(20), nullable=False, default="XAU/USD", index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, default="15m", index=True)
    direction = Column(String(10), nullable=False, index=True)  # BUY, SELL, WAIT

    # Pillar Scores
    structure_score = Column(Float, nullable=False, default=0.0)
    liquidity_score = Column(Float, nullable=False, default=0.0)
    indicators_score = Column(Float, nullable=False, default=0.0)
    price_action_score = Column(Float, nullable=False, default=0.0)
    total_score = Column(Float, nullable=False, default=0.0)

    # Key Features
    htf_trend = Column(String(20), nullable=True)  # BULLISH, BEARISH, RANGING
    session = Column(String(20), nullable=True, index=True)  # Asia, London, NY
    atr_percentile = Column(Float, nullable=True)  # 0.0 - 100.0 percentile
    sweep_yes_no = Column(Boolean, nullable=False, default=False)
    bos_choch_type = Column(String(30), nullable=True)  # BULLISH_BOS, BEARISH_CHOCH, etc.
    fvg_ob_present = Column(Boolean, nullable=False, default=False)
    premium_discount = Column(String(20), nullable=True)  # PREMIUM, DISCOUNT, EQUILIBRIUM
    rr = Column(Float, nullable=True)  # Planned Risk:Reward ratio
    distance_to_sl_atr = Column(Float, nullable=True)  # Distance to SL in ATR units

    # Final Score & Qualification
    final_score = Column(Float, nullable=False, default=0.0)
    qualified = Column(Boolean, nullable=False, default=False, index=True)

    # Outcome Labels (simulated on following bars)
    reached_1r = Column(Boolean, nullable=True)
    reached_2r = Column(Boolean, nullable=True)
    hit_sl = Column(Boolean, nullable=True)
    mfe = Column(Float, nullable=True)  # Maximum Favorable Excursion in R
    mae = Column(Float, nullable=True)  # Maximum Adverse Excursion in R
    bars_to_resolution = Column(Integer, nullable=True)
    r_multiple = Column(Float, nullable=True)  # Realized R-multiple

    # Pricing details for auditability
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    strategy_name = Column(String(50), nullable=True)
    source = Column(String(50), nullable=True, default="twelvedata")
    skipped_reason = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_signal_candidate_query", "symbol", "timeframe", "timestamp"),
        Index("ix_signal_candidate_session", "session", "qualified"),
    )

    def __repr__(self) -> str:
        return (
            f"<SignalCandidate(id={self.id}, sym='{self.symbol}', tf='{self.timeframe}', "
            f"time='{self.timestamp}', dir='{self.direction}', score={self.final_score:.1f}, "
            f"qual={self.qualified}, R={self.r_multiple})>"
        )
