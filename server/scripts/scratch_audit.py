"""Quantitative Debugging Script for Market Pipeline Audit."""

import os
import sys
import json
from datetime import datetime, timezone

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.models.candle import Candle
from app.schemas.signal import SignalDirection
from app.schemas.structure import TrendDirection, SwingType
from app.schemas.liquidity import ZoneType, LiquidityEventType, BOSCHOCHType
from app.schemas.indicators import FVGType, PatternType
from app.services.market_data.freshness import (
    filter_closed_candles,
    check_data_staleness,
    is_forex_weekend,
)
from app.services.structure.structure_engine import StructureEngine
from app.services.structure.bos_choch_detector import BOSCHOCHDetector
from app.services.structure.crt_analyzer import CRTAnalyzer
from app.services.structure.multi_timeframe import MultiTimeframeStructureEngine
from app.services.liquidity.liquidity_service import LiquidityService
from app.services.liquidity.sweep_detector import LiquiditySweepDetector
from app.services.liquidity.sr_detector import SupportResistanceDetector
from app.services.indicators.indicator_service import IndicatorService
from app.services.signals.evaluators import (
    StructureConsensusEvaluator,
    LiquiditySMCConsensusEvaluator,
    PriceActionConsensusEvaluator,
    ConsensusFilter,
)
from app.services.signals.path_validator import PathValidator
from app.services.signals.risk_manager import RiskManager
from app.services.strategies.crt_strategy import CRTStrategy
from app.services.strategies.smc_strategy import SMCStrategy

def run_audit(symbol="USD/JPY", tf="15m"):
    db = SessionLocal()
    now_utc = datetime.now(timezone.utc)
    
    # 1. Fetch candles from DB
    raw_15m = db.query(Candle).filter(Candle.symbol == symbol, Candle.timeframe == "15m").order_by(Candle.timestamp.asc()).all()
    raw_1h = db.query(Candle).filter(Candle.symbol == symbol, Candle.timeframe == "1h").order_by(Candle.timestamp.asc()).all()
    raw_4h = db.query(Candle).filter(Candle.symbol == symbol, Candle.timeframe == "4h").order_by(Candle.timestamp.asc()).all()
    
    c_15m = raw_15m[-100:] if len(raw_15m) > 100 else raw_15m
    c_1h = raw_1h[-100:] if len(raw_1h) > 100 else raw_1h
    c_4h = raw_4h[-100:] if len(raw_4h) > 100 else raw_4h

    # SECTION 1: Data Feed & Timestamp Audit
    c_last = c_15m[-1]
    c_prev1 = c_15m[-2]
    c_prev2 = c_15m[-3]
    
    staleness = check_data_staleness(c_15m, symbol=symbol, timeframe=tf, as_of=now_utc)
    delay_minutes = (now_utc - c_last.timestamp.replace(tzinfo=timezone.utc if c_last.timestamp.tzinfo is None else c_last.timestamp.tzinfo)).total_seconds() / 60.0
    
    sec1 = {
        "now_utc": now_utc.isoformat(),
        "c_last": {"ts": c_last.timestamp.isoformat(), "open": float(c_last.open), "high": float(c_last.high), "low": float(c_last.low), "close": float(c_last.close)},
        "c_prev1": {"ts": c_prev1.timestamp.isoformat(), "open": float(c_prev1.open), "high": float(c_prev1.high), "low": float(c_prev1.low), "close": float(c_prev1.close)},
        "c_prev2": {"ts": c_prev2.timestamp.isoformat(), "open": float(c_prev2.open), "high": float(c_prev2.high), "low": float(c_prev2.low), "close": float(c_prev2.close)},
        "delay_minutes": delay_minutes,
        "is_stale": staleness.is_stale,
        "age_hours": staleness.age_hours,
        "max_allowed_hours": staleness.max_allowed_hours,
        "is_weekend": staleness.is_weekend,
    }

    # SECTION 2: Market Structure Extraction
    struct_engine = StructureEngine(default_lookback=2)
    base_structure = struct_engine.analyze_structure(c_15m, symbol=symbol, timeframe=tf)
    swings = base_structure.swing_points
    
    total_candles = len(c_15m)
    swing_highs = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
    swing_lows = [s for s in swings if s.swing_type == SwingType.SWING_LOW]
    
    last_sh = swing_highs[-1] if swing_highs else None
    last_sl = swing_lows[-1] if swing_lows else None
    
    sh_bars_ago = (total_candles - 1) - last_sh.index if last_sh else None
    sl_bars_ago = (total_candles - 1) - last_sl.index if last_sl else None
    
    current_close = float(c_last.close)
    current_high = float(c_last.high)
    current_low = float(c_last.low)
    
    sh_closed_beyond = (current_close > last_sh.price) if last_sh else False
    sh_wicked_beyond = (current_high > last_sh.price) if last_sh else False
    sl_closed_beyond = (current_close < last_sl.price) if last_sl else False
    sl_wicked_beyond = (current_low < last_sl.price) if last_sl else False
    
    bos_detector = BOSCHOCHDetector()
    bos_events, choch_events = bos_detector.detect_bos_and_choch(c_15m, swings, base_structure.trend)
    
    latest_bos = bos_events[-1] if bos_events else None
    latest_choch = choch_events[-1] if choch_events else None
    
    # Check if latest closed candle triggered BOS or CHoCH
    latest_candle_idx = total_candles - 1
    bos_triggered_latest = (latest_bos.index == latest_candle_idx) if latest_bos else False
    choch_triggered_latest = (latest_choch.index == latest_candle_idx) if latest_choch else False
    
    sec2 = {
        "last_swing_high": {"price": last_sh.price, "bar_index": last_sh.index, "bars_ago": sh_bars_ago, "passed_15_bars": (sh_bars_ago <= 15) if sh_bars_ago is not None else False, "closed_beyond": sh_closed_beyond, "wicked_beyond": sh_wicked_beyond} if last_sh else None,
        "last_swing_low": {"price": last_sl.price, "bar_index": last_sl.index, "bars_ago": sl_bars_ago, "passed_15_bars": (sl_bars_ago <= 15) if sl_bars_ago is not None else False, "closed_beyond": sl_closed_beyond, "wicked_beyond": sl_wicked_beyond} if last_sl else None,
        "trend_state": base_structure.trend.value,
        "trend_strength": base_structure.trend_strength,
        "latest_bos": {"type": latest_bos.event_type.value, "breakout_price": latest_bos.breakout_price, "broken_swing_price": latest_bos.broken_swing_price, "bars_ago": (total_candles - 1 - latest_bos.index), "triggered_on_latest": bos_triggered_latest} if latest_bos else None,
        "latest_choch": {"type": latest_choch.event_type.value, "breakout_price": latest_choch.breakout_price, "broken_swing_price": latest_choch.broken_swing_price, "bars_ago": (total_candles - 1 - latest_choch.index), "triggered_on_latest": choch_triggered_latest} if latest_choch else None,
    }

    # SECTION 3: Liquidity & POI Detection
    sr_detector = SupportResistanceDetector(default_tolerance_percent=0.10)
    sr_zones, liquidity_pools = sr_detector.detect_sr_zones_and_pools(c_15m, swings)
    
    equal_highs = [p for p in liquidity_pools if p.pool_type == LiquidityEventType.EQUAL_HIGHS]
    equal_lows = [p for p in liquidity_pools if p.pool_type == LiquidityEventType.EQUAL_LOWS]
    
    sweep_detector = LiquiditySweepDetector()
    sweeps = sweep_detector.detect_sweeps(c_15m, swings, symbol=symbol)
    latest_sweep = sweeps[-1] if sweeps else None
    latest_bar_swept = (latest_sweep.index == latest_candle_idx) if latest_sweep else False
    
    # Calculate sweep depth / manip depth if sweep on latest
    sweep_details = None
    if latest_sweep:
        sw_bars_ago = (total_candles - 1) - latest_sweep.index
        # range size of swept candle
        sw_candle = c_15m[latest_sweep.index]
        sw_range = max(1e-6, float(sw_candle.high) - float(sw_candle.low))
        manip_depth = (abs(latest_sweep.sweep_extreme - latest_sweep.swept_level) / sw_range) * 100.0
        sweep_details = {
            "type": latest_sweep.sweep_type.value,
            "swept_level": latest_sweep.swept_level,
            "sweep_extreme": latest_sweep.sweep_extreme,
            "pips_swept": latest_sweep.pips_swept,
            "wick_ratio": latest_sweep.wick_ratio,
            "manip_depth_pct": round(manip_depth, 2),
            "bars_ago": sw_bars_ago,
            "triggered_on_latest_bar": latest_bar_swept,
        }
        
    indicator_svc = IndicatorService()
    indicators = indicator_svc.analyze_indicators(c_15m, symbol=symbol, timeframe=tf)
    
    active_fvgs = [f for f in indicators.active_fvgs if not f.is_mitigated]
    unmitigated_obs = [z for z in sr_zones if z.is_fresh]
    
    current_price = indicators.current_price
    inside_fvg = None
    fvg_list = []
    for f in active_fvgs:
        low_b = min(f.top_price, f.bottom_price)
        high_b = max(f.top_price, f.bottom_price)
        is_inside = (low_b <= current_price <= high_b)
        f_info = {
            "type": f.fvg_type.value,
            "top": f.top_price,
            "bottom": f.bottom_price,
            "gap_pips": f.gap_pips,
            "is_bullish": (f.fvg_type == FVGType.BULLISH_FVG),
            "is_mitigated": f.is_mitigated,
            "is_price_inside": is_inside,
        }
        fvg_list.append(f_info)
        if is_inside:
            inside_fvg = f_info
            
    ob_list = []
    for z in unmitigated_obs:
        ob_list.append({
            "type": z.zone_type.value,
            "top": z.price_high,
            "bottom": z.price_low,
            "center": z.center_price,
            "strength": z.strength,
            "touches": z.touch_count,
            "is_fresh": z.is_fresh,
            "is_bullish": (z.zone_type == ZoneType.SUPPORT),
        })

    sec3 = {
        "equal_highs_count": len(equal_highs),
        "equal_lows_count": len(equal_lows),
        "equal_highs": [{"price": p.price_level, "touches": p.touch_points, "is_swept": p.is_swept} for p in equal_highs],
        "equal_lows": [{"price": p.price_level, "touches": p.touch_points, "is_swept": p.is_swept} for p in equal_lows],
        "latest_sweep": sweep_details,
        "active_fvgs": fvg_list,
        "unmitigated_obs": ob_list,
        "current_price": current_price,
        "is_price_inside_fvg": inside_fvg is not None,
        "inside_fvg_details": inside_fvg,
    }

    # SECTION 4: CRT / AMD Lifecycle Check (Strategy D)
    crt_analyzer = CRTAnalyzer(default_min_manip_pct=5.0, default_confirm_bars=1)
    crt_analysis = crt_analyzer.analyze(range_candles=c_1h, confirm_candles=c_15m, min_manip_pct=5.0, confirm_bars=1)
    
    bench_candle = c_1h[-1]
    pip_size = 0.01 if "JPY" in symbol else 0.0001
    bench_high = float(bench_candle.high)
    bench_low = float(bench_candle.low)
    bench_open = float(bench_candle.open)
    bench_close = float(bench_candle.close)
    bench_range_price = bench_high - bench_low
    bench_range_pips = round(bench_range_price / pip_size, 1)
    
    # 1H ATR
    ind_1h = indicator_svc.analyze_indicators(c_1h, symbol=symbol, timeframe="1h")
    atr_1h = ind_1h.atr.atr_value if ind_1h.atr else None
    atr_1h_pips = ind_1h.atr.atr_pips if ind_1h.atr else None
    
    range_ge_atr = (bench_range_price >= atr_1h) if atr_1h else None
    manip_in_bounds = (5.0 <= crt_analysis.manip_depth_pct <= 100.0)
    
    crt_strategy = CRTStrategy()
    crt_res = crt_strategy.analyze(symbol=symbol, timeframe="15m", candles=c_15m, indicators=indicators, range_candles=c_1h, confirm_candles=c_15m)
    
    sec4 = {
        "benchmark_candle": {
            "timeframe": "1h",
            "ts": bench_candle.timestamp.isoformat(),
            "open": bench_open,
            "high": bench_high,
            "low": bench_low,
            "close": bench_close,
            "range_price": bench_range_price,
            "range_pips": bench_range_pips,
        },
        "atr_1h_value": atr_1h,
        "atr_1h_pips": atr_1h_pips,
        "range_ge_min_atr": range_ge_atr,
        "is_breached": crt_analysis.is_breached,
        "breach_point": crt_analysis.breach_point,
        "manip_depth_pct": crt_analysis.manip_depth_pct,
        "manip_in_bounds": manip_in_bounds,
        "is_confirmed": crt_analysis.is_confirmed,
        "strategy_d_direction": crt_res.direction.value,
        "strategy_d_score": crt_res.score,
        "strategy_d_reasons": crt_res.reasons,
    }

    # SECTION 5: Pillar Scoring & Gatekeeper Math
    mtf_engine = MultiTimeframeStructureEngine()
    mtf_analysis = mtf_engine.analyze_multi_timeframe(
        symbol=symbol,
        timeframe_candles={"4h": c_4h, "1h": c_1h, "15m": c_15m}
    )
    
    liq_svc = LiquidityService()
    adv_structure = liq_svc.analyze_liquidity_and_structure(c_15m, symbol=symbol, timeframe=tf)
    
    struct_eval = StructureConsensusEvaluator()
    liq_eval = LiquiditySMCConsensusEvaluator()
    pa_eval = PriceActionConsensusEvaluator()
    c_filter = ConsensusFilter(min_score_threshold=75.0)
    
    # Evaluate for BUY
    buy_struct = struct_eval.evaluate(SignalDirection.BUY, adv_structure, mtf_analysis)
    buy_liq = liq_eval.evaluate(SignalDirection.BUY, adv_structure, current_price, active_fvgs=indicators.active_fvgs)
    buy_pa = pa_eval.evaluate(SignalDirection.BUY, indicators)
    buy_evals = {"structure": buy_struct, "liquidity": buy_liq, "price_action": buy_pa}
    buy_score, buy_breakdown, buy_catalysts, buy_fatal = c_filter.synthesize(buy_evals, SignalDirection.BUY)
    
    # Evaluate for SELL
    sell_struct = struct_eval.evaluate(SignalDirection.SELL, adv_structure, mtf_analysis)
    sell_liq = liq_eval.evaluate(SignalDirection.SELL, adv_structure, current_price, active_fvgs=indicators.active_fvgs)
    sell_pa = pa_eval.evaluate(SignalDirection.SELL, indicators)
    sell_evals = {"structure": sell_struct, "liquidity": sell_liq, "price_action": sell_pa}
    sell_score, sell_breakdown, sell_catalysts, sell_fatal = c_filter.synthesize(sell_evals, SignalDirection.SELL)
    
    # Path Validator check
    path_val = PathValidator()
    # Hypothetical BUY and SELL targets
    risk_mgr = RiskManager()
    atr_val = indicators.atr.atr_value if indicators.atr else 0.20
    buy_tp1 = current_price + (atr_val * 2.0)
    sell_tp1 = current_price - (atr_val * 2.0)
    
    buy_path = path_val.validate_trade_path(SignalDirection.BUY, current_price, buy_tp1, adv_structure.sr_zones, indicators.active_fvgs, adv_structure.liquidity_pools)
    sell_path = path_val.validate_trade_path(SignalDirection.SELL, current_price, sell_tp1, adv_structure.sr_zones, indicators.active_fvgs, adv_structure.liquidity_pools)

    sec5 = {
        "BUY": {
            "structure_score": buy_struct.score,
            "structure_catalysts": buy_struct.catalysts,
            "structure_opposing": buy_struct.opposing_signals,
            "liquidity_score": buy_liq.score,
            "liquidity_catalysts": buy_liq.catalysts,
            "liquidity_opposing": buy_liq.opposing_signals,
            "price_action_score": buy_pa.score,
            "price_action_catalysts": buy_pa.catalysts,
            "price_action_opposing": buy_pa.opposing_signals,
            "total_score": buy_score,
            "is_qualified": buy_breakdown.is_qualified,
            "fatal_conflict": buy_fatal,
            "catalysts_all": buy_catalysts,
            "path_clear": buy_path.is_clear,
            "nearest_obstacle": buy_path.obstacle_type,
            "nearest_obstacle_price": buy_path.nearest_obstacle_price,
            "obstacle_count": buy_path.obstacle_count,
        },
        "SELL": {
            "structure_score": sell_struct.score,
            "structure_catalysts": sell_struct.catalysts,
            "structure_opposing": sell_struct.opposing_signals,
            "liquidity_score": sell_liq.score,
            "liquidity_catalysts": sell_liq.catalysts,
            "liquidity_opposing": sell_liq.opposing_signals,
            "price_action_score": sell_pa.score,
            "price_action_catalysts": sell_pa.catalysts,
            "price_action_opposing": sell_pa.opposing_signals,
            "total_score": sell_score,
            "is_qualified": sell_breakdown.is_qualified,
            "fatal_conflict": sell_fatal,
            "catalysts_all": sell_catalysts,
            "path_clear": sell_path.is_clear,
            "nearest_obstacle": sell_path.obstacle_type,
            "nearest_obstacle_price": sell_path.nearest_obstacle_price,
            "obstacle_count": sell_path.obstacle_count,
        },
        "mtf_alignment": mtf_analysis.alignment.value if mtf_analysis else "NONE",
        "market_state": adv_structure.market_state,
    }

    full_audit = {
        "symbol": symbol,
        "timeframe": tf,
        "section1_data_feed": sec1,
        "section2_market_structure": sec2,
        "section3_liquidity_poi": sec3,
        "section4_crt_amd": sec4,
        "section5_scoring_gatekeepers": sec5,
    }
    
    print(json.dumps(full_audit, indent=2))
    return full_audit

if __name__ == "__main__":
    run_audit("USD/JPY", "15m")
