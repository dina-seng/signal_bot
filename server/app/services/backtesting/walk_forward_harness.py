"""Walk-Forward Historical Backtest Harness for XAU/USD.

Enforces:
1. Pure walk-forward bar-by-bar execution: at each closed 15m bar, only candles with
   timestamp + delta <= current bar close are visible. Zero future lookahead.
2. Single consistent data provider source per run: refuses to mix sources.
3. Realistic execution friction: configurable spread (default $0.30) and slippage (default $0.10) for XAU/USD.
4. Conservative exit simulation: if SL and TP hit in the same bar, assume SL first.
5. Signal Candidate Logging: records EVERY setup candidate (qualified and unqualified)
   with all pillar scores, key features, and simulated outcome labels.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import random
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models.signal_candidate import SignalCandidate
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection, SignalResponse
from app.services.signals import RiskManager, SignalGenerator


def get_utc_session(dt: datetime) -> str:
    """Return trading session based on UTC hour: Asia, London, NY."""
    hour = dt.hour
    if 0 <= hour < 8 or hour >= 21:
        return "Asia"
    elif 8 <= hour < 13:
        return "London"
    else:
        return "NY"


def get_timeframe_delta(tf: str) -> timedelta:
    """Return timedelta duration for a given timeframe string."""
    t = tf.lower().strip()
    if t == "15m":
        return timedelta(minutes=15)
    elif t == "30m":
        return timedelta(minutes=30)
    elif t == "1h":
        return timedelta(hours=1)
    elif t == "4h":
        return timedelta(hours=4)
    elif t == "1d":
        return timedelta(days=1)
    return timedelta(minutes=15)


@dataclass
class CandidateOutcome:
    """Forward outcome simulation result for a signal candidate."""
    reached_1r: bool = False
    reached_2r: bool = False
    hit_sl: bool = False
    mfe: float = 0.0  # Max Favorable Excursion in R
    mae: float = 0.0  # Max Adverse Excursion in R
    bars_to_resolution: int = 0
    r_multiple: float = 0.0
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = "PENDING"


@dataclass
class TradeMetrics:
    """Aggregated trade performance metrics."""
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_r: float = 0.0
    total_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0


@dataclass
class WalkForwardResult:
    """Result container for full walk-forward backtest."""
    symbol: str
    source: str
    total_candidates_logged: int
    qualified_candidates_count: int
    executed_trades_count: int
    train_metrics: TradeMetrics
    test_metrics: TradeMetrics
    train_baseline_metrics: TradeMetrics
    test_baseline_metrics: TradeMetrics
    session_breakdown: Dict[str, Dict[str, Any]]
    candidates: List[Dict[str, Any]] = field(default_factory=list)


class WalkForwardHarness:
    """Walk-forward institutional backtesting harness for XAU/USD."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.risk_manager = risk_manager or RiskManager()

    @staticmethod
    def _extract_candle_ts(candle: Any) -> datetime:
        ts = getattr(candle, "timestamp", None) or (candle.get("timestamp") if isinstance(candle, dict) else None)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @staticmethod
    def _extract_candle_attr(candle: Any, attr: str, default: float = 0.0) -> float:
        if isinstance(candle, dict):
            return float(candle.get(attr, default))
        return float(getattr(candle, attr, default))

    @staticmethod
    def _extract_candle_source(candle: Any) -> Optional[str]:
        if isinstance(candle, dict):
            return candle.get("source")
        return getattr(candle, "source", None)

    def validate_data_sources(
        self,
        candles_15m: Sequence[Any],
        candles_1h: Optional[Sequence[Any]] = None,
        candles_4h: Optional[Sequence[Any]] = None,
        requested_source: Optional[str] = None,
    ) -> str:
        """Enforce strict single consistent data source per run. Refuses mixed sources."""
        all_candles = list(candles_15m) + list(candles_1h or []) + list(candles_4h or [])
        sources_found: Set[str] = set()

        for c in all_candles:
            src = self._extract_candle_source(c)
            if src:
                sources_found.add(src.strip().lower())

        if len(sources_found) > 1:
            raise ValueError(
                f"Mixed data sources detected: {sorted(sources_found)}. "
                "Backtest harness strictly refuses to mix sources inside one backtest run. "
                "All candles must originate from a single consistent provider."
            )

        inferred_source = sources_found.pop() if sources_found else "twelvedata"
        if requested_source and requested_source.strip().lower() != inferred_source:
            raise ValueError(
                f"Requested data source '{requested_source}' does not match candle source '{inferred_source}'."
            )

        return requested_source.strip().lower() if requested_source else inferred_source

    def simulate_outcome(
        self,
        entry_bar_idx: int,
        direction: SignalDirection,
        entry_price: float,
        stop_loss: float,
        take_profit_1: float,
        candles_15m: Sequence[Any],
        spread_usd: float = 0.30,
        slippage_usd: float = 0.10,
        max_horizon_bars: int = 150,
    ) -> CandidateOutcome:
        """Simulate SL/TP1 outcome on subsequent bars.
        
        Rule: if SL and TP hit in the same bar, assume SL first.
        """
        outcome = CandidateOutcome()
        risk = abs(entry_price - stop_loss)
        if risk < 1e-5:
            risk = 1.0  # Safety fallback for zero-risk anomaly

        one_r_target = (entry_price + risk) if direction == SignalDirection.BUY else (entry_price - risk)
        two_r_target = (entry_price + 2.0 * risk) if direction == SignalDirection.BUY else (entry_price - 2.0 * risk)

        total_bars = len(candles_15m)
        max_idx = min(total_bars, entry_bar_idx + 1 + max_horizon_bars)

        max_fav = 0.0
        max_adv = 0.0

        for j in range(entry_bar_idx + 1, max_idx):
            bar = candles_15m[j]
            bar_high = self._extract_candle_attr(bar, "high")
            bar_low = self._extract_candle_attr(bar, "low")
            bar_close = self._extract_candle_attr(bar, "close")
            bar_ts = self._extract_candle_ts(bar)
            bars_elapsed = j - entry_bar_idx

            if direction == SignalDirection.BUY:
                fav = max(0.0, (bar_high - entry_price) / risk)
                adv = max(0.0, (entry_price - bar_low) / risk)
                max_fav = max(max_fav, fav)
                max_adv = max(max_adv, adv)

                if bar_high >= one_r_target:
                    outcome.reached_1r = True
                if bar_high >= two_r_target:
                    outcome.reached_2r = True

                sl_hit = bar_low <= stop_loss
                tp_hit = bar_high >= take_profit_1

                # If SL and TP hit in the same bar, assume SL first!
                if sl_hit and tp_hit:
                    outcome.hit_sl = True
                    outcome.exit_price = round(stop_loss - slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "SL_HIT"
                    outcome.r_multiple = -1.0
                    outcome.bars_to_resolution = bars_elapsed
                    break
                elif sl_hit:
                    outcome.hit_sl = True
                    outcome.exit_price = round(stop_loss - slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "SL_HIT"
                    outcome.r_multiple = -1.0
                    outcome.bars_to_resolution = bars_elapsed
                    break
                elif tp_hit:
                    outcome.exit_price = round(take_profit_1 - slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "TP1_HIT"
                    outcome.r_multiple = round((take_profit_1 - entry_price) / risk, 2)
                    outcome.bars_to_resolution = bars_elapsed
                    break

            elif direction == SignalDirection.SELL:
                fav = max(0.0, (entry_price - bar_low) / risk)
                adv = max(0.0, (bar_high - entry_price) / risk)
                max_fav = max(max_fav, fav)
                max_adv = max(max_adv, adv)

                if bar_low <= one_r_target:
                    outcome.reached_1r = True
                if bar_low <= two_r_target:
                    outcome.reached_2r = True

                sl_hit = bar_high >= stop_loss
                tp_hit = bar_low <= take_profit_1

                # If SL and TP hit in the same bar, assume SL first!
                if sl_hit and tp_hit:
                    outcome.hit_sl = True
                    outcome.exit_price = round(stop_loss + slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "SL_HIT"
                    outcome.r_multiple = -1.0
                    outcome.bars_to_resolution = bars_elapsed
                    break
                elif sl_hit:
                    outcome.hit_sl = True
                    outcome.exit_price = round(stop_loss + slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "SL_HIT"
                    outcome.r_multiple = -1.0
                    outcome.bars_to_resolution = bars_elapsed
                    break
                elif tp_hit:
                    outcome.exit_price = round(take_profit_1 + slippage_usd, 5)
                    outcome.exit_time = bar_ts
                    outcome.exit_reason = "TP1_HIT"
                    outcome.r_multiple = round((entry_price - take_profit_1) / risk, 2)
                    outcome.bars_to_resolution = bars_elapsed
                    break

        # If unresolved within horizon
        if outcome.bars_to_resolution == 0:
            last_bar = candles_15m[min(total_bars - 1, max_idx - 1)]
            last_close = self._extract_candle_attr(last_bar, "close")
            outcome.bars_to_resolution = min(total_bars - 1, max_idx - 1) - entry_bar_idx
            outcome.exit_time = self._extract_candle_ts(last_bar)
            outcome.exit_reason = "END_OF_DATA"
            if direction == SignalDirection.BUY:
                outcome.exit_price = round(last_close - slippage_usd, 5)
                outcome.r_multiple = round((outcome.exit_price - entry_price) / risk, 2)
            else:
                outcome.exit_price = round(last_close + slippage_usd, 5)
                outcome.r_multiple = round((entry_price - outcome.exit_price) / risk, 2)

        outcome.mfe = round(max_fav, 2)
        outcome.mae = round(max_adv, 2)
        return outcome

    @staticmethod
    def calculate_metrics(r_multiples: List[float]) -> TradeMetrics:
        """Calculate comprehensive R-distribution metrics."""
        m = TradeMetrics()
        m.trade_count = len(r_multiples)
        if not r_multiples:
            return m

        wins = [r for r in r_multiples if r > 0]
        losses = [r for r in r_multiples if r <= 0]

        m.win_count = len(wins)
        m.loss_count = len(losses)
        m.win_rate = round((m.win_count / m.trade_count) * 100.0, 2)

        m.total_r = round(sum(r_multiples), 2)
        m.avg_win_r = round(sum(wins) / len(wins), 2) if wins else 0.0
        m.avg_loss_r = round(abs(sum(losses)) / len(losses), 2) if losses else 0.0

        # Expectancy in R: (Win% * AvgWin) - (Loss% * AvgLoss)
        win_prob = m.win_count / m.trade_count
        loss_prob = m.loss_count / m.trade_count
        m.expectancy_r = round((win_prob * m.avg_win_r) - (loss_prob * m.avg_loss_r), 2)

        # Profit Factor: gross wins in R / gross losses in R
        gross_win_r = sum(wins)
        gross_loss_r = abs(sum(losses))
        m.profit_factor = round(gross_win_r / max(1e-4, gross_loss_r), 2)

        # Max Drawdown calculation in R
        cum_r = 0.0
        peak_r = 0.0
        max_dd_r = 0.0
        for r in r_multiples:
            cum_r += r
            if cum_r > peak_r:
                peak_r = cum_r
            dd = peak_r - cum_r
            if dd > max_dd_r:
                max_dd_r = dd

        m.max_drawdown_r = round(max_dd_r, 2)
        m.max_drawdown_pct = round((max_dd_r / max(1.0, peak_r)) * 100.0 if peak_r > 0 else 0.0, 2)
        return m

    def run_walk_forward(
        self,
        candles_15m: Sequence[Any],
        candles_1h: Optional[Sequence[Any]] = None,
        candles_4h: Optional[Sequence[Any]] = None,
        symbol: str = "XAU/USD",
        source: Optional[str] = None,
        spread_usd: Optional[float] = None,
        slippage_usd: Optional[float] = None,
        min_score_threshold: Optional[float] = None,
        min_rr: Optional[float] = None,
        warmup_bars: int = 50,
        db: Optional[Session] = None,
        random_seed: int = 42,
    ) -> WalkForwardResult:
        """Execute walk-forward bar-by-bar backtest simulation and log every candidate."""
        # 1. Enforce single consistent data source
        active_source = self.validate_data_sources(
            candles_15m=candles_15m,
            candles_1h=candles_1h,
            candles_4h=candles_4h,
            requested_source=source,
        )

        spread = spread_usd if spread_usd is not None else getattr(settings, "XAUUSD_SPREAD", 0.30)
        slippage = slippage_usd if slippage_usd is not None else getattr(settings, "XAUUSD_SLIPPAGE", 0.10)
        min_score = min_score_threshold if min_score_threshold is not None else settings.MIN_SETUP_SCORE
        threshold_rr = min_rr if min_rr is not None else settings.MIN_RR

        # Pre-parse timestamps
        ts_15m = [self._extract_candle_ts(c) for c in candles_15m]
        delta_15m = get_timeframe_delta("15m")
        delta_1h = get_timeframe_delta("1h")
        delta_4h = get_timeframe_delta("4h")

        total_15m = len(candles_15m)
        if total_15m < warmup_bars + 10:
            raise ValueError(f"Insufficient 15m candle data: got {total_15m}, need at least {warmup_bars + 10}")

        candidates_logged: List[Dict[str, Any]] = []
        db_candidate_objects: List[SignalCandidate] = []

        # Rolling ATR window for percentile calculation
        atr_history: List[float] = []

        # Realistic trade simulation state: one open position per symbol at a time + cooldown
        cooldown_hours = getattr(settings, "SIGNAL_COOLDOWN_HOURS", 2)
        active_trade_exit_bar_idx: int = -1
        last_trade_exit_time: Optional[datetime] = None

        # 2. Walk forward bar-by-bar
        for i in range(warmup_bars, total_15m):
            c15 = candles_15m[i]
            bar_ts = ts_15m[i]
            # Current 15m bar close timestamp:
            current_bar_close = bar_ts + delta_15m
            current_close_price = self._extract_candle_attr(c15, "close")
            session = get_utc_session(bar_ts)

            # Strict no-lookahead slices: timestamp + delta <= current_bar_close
            visible_15m = candles_15m[: i + 1]

            visible_1h = []
            if candles_1h:
                visible_1h = [c for c in candles_1h if self._extract_candle_ts(c) + delta_1h <= current_bar_close]

            visible_4h = []
            if candles_4h:
                visible_4h = [c for c in candles_4h if self._extract_candle_ts(c) + delta_4h <= current_bar_close]

            # Primary window for evaluation (last 150 bars)
            eval_15m = visible_15m[-150:]
            eval_4h = visible_4h[-100:] if visible_4h else None

            # Run signal pipeline with explicit as_of and backtest_mode
            signals: List[SignalResponse] = self.signal_generator.evaluate_market_signals_multi(
                candles_primary=eval_15m,
                symbol=symbol,
                timeframe="15m",
                candles_4h=eval_4h,
                candles_15m=eval_15m,
                account_balance=10000.0,
                risk_percent=settings.RESEARCH_RISK_PERCENT,
                as_of=current_bar_close,
                backtest_mode=True,
            )

            # Compute current ATR for feature logging
            current_atr = 2.0  # sensible fallback
            if len(eval_15m) >= 14:
                highs = [self._extract_candle_attr(c, "high") for c in eval_15m[-14:]]
                lows = [self._extract_candle_attr(c, "low") for c in eval_15m[-14:]]
                tr_list = [h - l for h, l in zip(highs, lows)]
                current_atr = sum(tr_list) / len(tr_list)

            atr_history.append(current_atr)
            if len(atr_history) > 200:
                atr_history.pop(0)

            sorted_atrs = sorted(atr_history)
            atr_pct = round(
                (sorted_atrs.index(current_atr) / max(1, len(sorted_atrs) - 1)) * 100.0, 1
            )

            # 3. Process EVERY candidate generated at this bar
            for sig in signals:
                dir_val = sig.direction.value.upper()
                score = sig.setup_score
                breakdown = sig.score_breakdown
                risk_p = sig.risk_parameters

                # Determine if qualified
                is_actionable = dir_val in ("BUY", "SELL")
                sig_rr = sig.risk_reward or (risk_p.risk_reward_tp1 if risk_p else 0.0)
                is_qualified = bool(
                    is_actionable
                    and score >= min_score
                    and sig_rr >= threshold_rr
                    and (breakdown.is_qualified if breakdown else True)
                )

                # Feature extraction
                reasons_text = " ".join(sig.reasons).upper()
                sweep_yes_no = "SWEEP" in reasons_text or "TURTLE SOUP" in reasons_text
                
                bos_choch = None
                if "BULLISH BOS" in reasons_text:
                    bos_choch = "BULLISH_BOS"
                elif "BEARISH BOS" in reasons_text:
                    bos_choch = "BEARISH_BOS"
                elif "BULLISH CHOCH" in reasons_text or "MSS" in reasons_text:
                    bos_choch = "BULLISH_CHOCH"
                elif "BEARISH CHOCH" in reasons_text:
                    bos_choch = "BEARISH_CHOCH"

                fvg_ob_present = "FVG" in reasons_text or "FAIR VALUE GAP" in reasons_text or "ORDER BLOCK" in reasons_text
                
                prem_disc = "EQUILIBRIUM"
                if "DISCOUNT" in reasons_text:
                    prem_disc = "DISCOUNT"
                elif "PREMIUM" in reasons_text:
                    prem_disc = "PREMIUM"

                # Candidate entry and SL pricing
                if is_actionable:
                    if dir_val == "BUY":
                        exec_entry = round(current_close_price + (spread / 2.0) + slippage, 5)
                        sl_price = risk_p.stop_loss if risk_p else round(exec_entry - (current_atr * 1.5), 5)
                        if sl_price >= exec_entry:
                            sl_price = round(exec_entry - (current_atr * 1.5), 5)
                        tp1_price = risk_p.take_profit_1 if risk_p else round(exec_entry + abs(exec_entry - sl_price) * 2.0, 5)
                    else:
                        exec_entry = round(current_close_price - (spread / 2.0) - slippage, 5)
                        sl_price = risk_p.stop_loss if risk_p else round(exec_entry + (current_atr * 1.5), 5)
                        if sl_price <= exec_entry:
                            sl_price = round(exec_entry + (current_atr * 1.5), 5)
                        tp1_price = risk_p.take_profit_1 if risk_p else round(exec_entry - abs(exec_entry - sl_price) * 2.0, 5)

                    dist_sl_atr = round(abs(exec_entry - sl_price) / max(1e-4, current_atr), 2)
                    sim_rr = round(abs(tp1_price - exec_entry) / max(1e-4, abs(exec_entry - sl_price)), 2)

                    # Simulate forward outcome
                    outcome = self.simulate_outcome(
                        entry_bar_idx=i,
                        direction=sig.direction,
                        entry_price=exec_entry,
                        stop_loss=sl_price,
                        take_profit_1=tp1_price,
                        candles_15m=candles_15m,
                        spread_usd=spread,
                        slippage_usd=slippage,
                    )
                else:
                    exec_entry = current_close_price
                    sl_price = None
                    tp1_price = None
                    dist_sl_atr = None
                    sim_rr = 0.0
                    outcome = CandidateOutcome()

                # Determine execution eligibility under single-position and cooldown rules
                skipped_reason: Optional[str] = None
                if is_qualified:
                    if i < active_trade_exit_bar_idx:
                        skipped_reason = "POSITION_ACTIVE"
                    elif last_trade_exit_time is not None and bar_ts < last_trade_exit_time + timedelta(hours=cooldown_hours):
                        skipped_reason = "COOLDOWN_ACTIVE"
                    else:
                        # Trade entered! Lock active position until resolution bar
                        skipped_reason = None
                        res_bars = outcome.bars_to_resolution if outcome.bars_to_resolution > 0 else 1
                        active_trade_exit_bar_idx = i + res_bars
                        last_trade_exit_time = outcome.exit_time or (bar_ts + (delta_15m * res_bars))

                cand_dict = {
                    "symbol": symbol,
                    "timestamp": bar_ts,
                    "timeframe": "15m",
                    "direction": dir_val,
                    "structure_score": breakdown.structure_score if breakdown else 0.0,
                    "liquidity_score": breakdown.liquidity_score if breakdown else 0.0,
                    "indicators_score": breakdown.indicators_score if breakdown else 0.0,
                    "price_action_score": breakdown.price_action_score if breakdown else 0.0,
                    "total_score": breakdown.total_score if breakdown else score,
                    "htf_trend": sig.htf_trend or "RANGING",
                    "session": session,
                    "atr_percentile": atr_pct,
                    "sweep_yes_no": sweep_yes_no,
                    "bos_choch_type": bos_choch,
                    "fvg_ob_present": fvg_ob_present,
                    "premium_discount": prem_disc,
                    "rr": sim_rr or sig_rr,
                    "distance_to_sl_atr": dist_sl_atr,
                    "final_score": score,
                    "qualified": is_qualified,
                    "skipped_reason": skipped_reason,
                    "reached_1r": outcome.reached_1r if is_actionable else None,
                    "reached_2r": outcome.reached_2r if is_actionable else None,
                    "hit_sl": outcome.hit_sl if is_actionable else None,
                    "mfe": outcome.mfe if is_actionable else None,
                    "mae": outcome.mae if is_actionable else None,
                    "bars_to_resolution": outcome.bars_to_resolution if is_actionable else None,
                    "r_multiple": outcome.r_multiple if is_actionable else None,
                    "entry_price": exec_entry if is_actionable else None,
                    "stop_loss": sl_price,
                    "take_profit_1": tp1_price,
                    "strategy_name": sig.strategy_name,
                    "source": active_source,
                }
                candidates_logged.append(cand_dict)

                if db is not None:
                    db_cand = SignalCandidate(
                        symbol=symbol,
                        timestamp=bar_ts,
                        timeframe="15m",
                        direction=dir_val,
                        structure_score=cand_dict["structure_score"],
                        liquidity_score=cand_dict["liquidity_score"],
                        indicators_score=cand_dict["indicators_score"],
                        price_action_score=cand_dict["price_action_score"],
                        total_score=cand_dict["total_score"],
                        htf_trend=cand_dict["htf_trend"],
                        session=session,
                        atr_percentile=atr_pct,
                        sweep_yes_no=sweep_yes_no,
                        bos_choch_type=bos_choch,
                        fvg_ob_present=fvg_ob_present,
                        premium_discount=prem_disc,
                        rr=cand_dict["rr"],
                        distance_to_sl_atr=dist_sl_atr,
                        final_score=score,
                        qualified=is_qualified,
                        skipped_reason=skipped_reason,
                        reached_1r=outcome.reached_1r if is_actionable else None,
                        reached_2r=outcome.reached_2r if is_actionable else None,
                        hit_sl=outcome.hit_sl if is_actionable else None,
                        mfe=outcome.mfe if is_actionable else None,
                        mae=outcome.mae if is_actionable else None,
                        bars_to_resolution=outcome.bars_to_resolution if is_actionable else None,
                        r_multiple=outcome.r_multiple if is_actionable else None,
                        entry_price=exec_entry if is_actionable else None,
                        stop_loss=sl_price,
                        take_profit_1=tp1_price,
                        strategy_name=sig.strategy_name,
                        source=active_source,
                    )
                    db_candidate_objects.append(db_cand)

        # Batch insert candidates if db provided
        if db is not None and db_candidate_objects:
            try:
                db.add_all(db_candidate_objects)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.warning(f"Failed to persist signal candidates: {e}")

        # 4. Realistic execution metrics: filter to executed trades (one position at a time + cooldown)
        all_qualified = [c for c in candidates_logged if c["qualified"]]
        executed_trades = [c for c in all_qualified if c["skipped_reason"] is None]

        # Generate Random Entry Baseline at the same bar times with identical SL/TP rules
        rng = random.Random(random_seed)
        baseline_r_multiples: List[float] = []
        for q in executed_trades:
            # Coin-flip BUY or SELL
            rand_dir = SignalDirection.BUY if rng.random() >= 0.5 else SignalDirection.SELL
            q_idx = next((idx for idx, c in enumerate(candles_15m) if self._extract_candle_ts(c) == q["timestamp"]), None)
            if q_idx is None:
                continue

            q_close = self._extract_candle_attr(candles_15m[q_idx], "close")
            risk_dist = abs(q["entry_price"] - q["stop_loss"]) if q["entry_price"] and q["stop_loss"] else 2.0
            if rand_dir == SignalDirection.BUY:
                rand_entry = round(q_close + (spread / 2.0) + slippage, 5)
                rand_sl = round(rand_entry - risk_dist, 5)
                rand_tp = round(rand_entry + (risk_dist * (q["rr"] or 2.0)), 5)
            else:
                rand_entry = round(q_close - (spread / 2.0) - slippage, 5)
                rand_sl = round(rand_entry + risk_dist, 5)
                rand_tp = round(rand_entry - (risk_dist * (q["rr"] or 2.0)), 5)

            rand_outcome = self.simulate_outcome(
                entry_bar_idx=q_idx,
                direction=rand_dir,
                entry_price=rand_entry,
                stop_loss=rand_sl,
                take_profit_1=rand_tp,
                candles_15m=candles_15m,
                spread_usd=spread,
                slippage_usd=slippage,
            )
            baseline_r_multiples.append(rand_outcome.r_multiple)

        # 5. Time-based 70% / 30% Train/Test Split on executed trades
        n_exec = len(executed_trades)
        split_idx = int(n_exec * 0.70)

        train_cands = executed_trades[:split_idx]
        test_cands = executed_trades[split_idx:]

        train_baseline = baseline_r_multiples[:split_idx]
        test_baseline = baseline_r_multiples[split_idx:]

        train_r = [c["r_multiple"] for c in train_cands if c["r_multiple"] is not None]
        test_r = [c["r_multiple"] for c in test_cands if c["r_multiple"] is not None]

        train_metrics = self.calculate_metrics(train_r)
        test_metrics = self.calculate_metrics(test_r)
        train_baseline_metrics = self.calculate_metrics(train_baseline)
        test_baseline_metrics = self.calculate_metrics(test_baseline)

        # Per-session breakdown on executed trades (Asia, London, NY)
        session_breakdown: Dict[str, Dict[str, Any]] = {}
        for sess in ("Asia", "London", "NY"):
            sess_cands = [c for c in executed_trades if c["session"] == sess]
            sess_r = [c["r_multiple"] for c in sess_cands if c["r_multiple"] is not None]
            sm = self.calculate_metrics(sess_r)
            session_breakdown[sess] = {
                "trade_count": sm.trade_count,
                "win_rate": sm.win_rate,
                "expectancy_r": sm.expectancy_r,
                "profit_factor": sm.profit_factor,
                "total_r": sm.total_r,
            }

        return WalkForwardResult(
            symbol=symbol,
            source=active_source,
            total_candidates_logged=len(candidates_logged),
            qualified_candidates_count=len(all_qualified),
            executed_trades_count=n_exec,
            train_metrics=train_metrics,
            test_metrics=test_metrics,
            train_baseline_metrics=train_baseline_metrics,
            test_baseline_metrics=test_baseline_metrics,
            session_breakdown=session_breakdown,
            candidates=candidates_logged,
        )
