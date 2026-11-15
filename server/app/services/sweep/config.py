"""SweepConfig dataclass holding all parameters for liquidity-sweep SMC engine."""

from dataclasses import dataclass, asdict
import json


@dataclass(frozen=True)
class SweepConfig:
    """All configuration parameters for liquidity sweep detection, confirmation, and trade generation."""

    symbol: str = "XAU/USD"
    lookback_bars_15m: int = 1000            # Explicit algorithm lookback window (open-market bars)
    atr_period: int = 14
    pivot_n_15m: int = 3
    pivot_n_htf: int = 2
    equal_level_threshold_atr: float = 0.10  # Max distance in ATR for equal highs/lows
    min_sweep_penetration_atr: float = 0.05  # Minimum wick penetration beyond pool in ATR
    max_rejection_bars: int = 3              # Must close back inside level within N bars
    sweep_cooldown_bars: int = 8             # Cooldown bars after a pool is swept
    max_mss_bars: int = 12                   # MSS must occur within N bars after sweep
    displacement_body_atr: float = 0.8       # Displacement candle body >= N * ATR
    displacement_body_ratio: float = 0.60    # Displacement body >= N% of total candle range
    zone_expiry_bars: int = 16               # Entry zone expires if not filled within N bars
    stop_buffer_atr: float = 0.15            # Stop buffer beyond sweep extreme in ATR
    spread_usd: float = 0.30                 # Configured spread in USD (default 0.30 for gold)
    slippage_usd: float = 0.10               # Configured slippage in USD (default 0.10 for gold)
    min_rr_tp1: float = 1.5                  # Minimum required Risk:Reward to TP1
    strong_displacement_atr: float = 1.2     # Strong displacement threshold for Grade A
    high_rr_threshold: float = 2.0           # High RR threshold for Grade A

    # Kill-zone session windows in America/New_York (DST-aware)
    asia_start_hour_ny: int = 18
    asia_end_hour_ny: int = 0
    london_start_hour_ny: int = 3
    london_end_hour_ny: int = 7
    ny_prep_start_hour_ny: int = 9
    ny_prep_start_min_ny: int = 0
    ny_prep_end_hour_ny: int = 9
    ny_prep_end_min_ny: int = 30
    ny_window_start_hour_ny: int = 9
    ny_window_start_min_ny: int = 30
    ny_window_end_hour_ny: int = 10
    ny_window_end_min_ny: int = 30

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
