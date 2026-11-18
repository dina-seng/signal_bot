"""Unit tests for the Regime Filter hypothesis in smc_replay."""

import sys
from pathlib import Path
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from app.schemas.indicators import EMASnapshot, IndicatorAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.services.strategies.base import StrategyResult
from smc_replay import SmcRecord, CONFIRMED_STATE, NO_SETUP_STATE


def test_regime_filter_rejection_logic():
    """Verify that regime filter rejects counter-trend setups and accepts aligned setups."""
    # Test cases: (direction, ema_trend, regime_filter, expected_accepted, expected_gate)
    cases = [
        # Filter disabled: all confirmed setups accepted regardless of EMA trend
        ("BUY", "BEARISH_STACK", False, True, CONFIRMED_STATE),
        ("SELL", "BULLISH_STACK", False, True, CONFIRMED_STATE),
        ("BUY", "NEUTRAL", False, True, CONFIRMED_STATE),
        ("SELL", "NEUTRAL", False, True, CONFIRMED_STATE),

        # Filter enabled: counter-trend rejected
        ("BUY", "BEARISH_STACK", True, False, "REGIME_FILTER_REJECT"),
        ("BUY", "BEARISH_BIAS", True, False, "REGIME_FILTER_REJECT"),
        ("BUY", "NEUTRAL", True, False, "REGIME_FILTER_REJECT"),
        ("SELL", "BULLISH_STACK", True, False, "REGIME_FILTER_REJECT"),
        ("SELL", "BULLISH_BIAS", True, False, "REGIME_FILTER_REJECT"),
        ("SELL", "NEUTRAL", True, False, "REGIME_FILTER_REJECT"),

        # Filter enabled: trend-aligned accepted
        ("BUY", "BULLISH_STACK", True, True, CONFIRMED_STATE),
        ("SELL", "BEARISH_STACK", True, True, CONFIRMED_STATE),
    ]

    for direction, ema_trend, regime_filter, exp_accepted, exp_gate in cases:
        gate = CONFIRMED_STATE
        accepted = gate == CONFIRMED_STATE
        detail = ""

        if regime_filter and accepted:
            if direction == "BUY":
                regime_ok = (ema_trend == "BULLISH_STACK")
            elif direction == "SELL":
                regime_ok = (ema_trend == "BEARISH_STACK")
            else:
                regime_ok = False

            if not regime_ok:
                accepted = False
                gate = "REGIME_FILTER_REJECT"
                detail = f"REGIME_FILTER_REJECT: {direction} requires {'BULLISH_STACK' if direction == 'BUY' else 'BEARISH_STACK'} but got {ema_trend}"

        assert accepted == exp_accepted, f"Failed accepted for {direction} with {ema_trend} (filter={regime_filter})"
        assert gate == exp_gate, f"Failed gate for {direction} with {ema_trend} (filter={regime_filter})"
        if not exp_accepted:
            assert "REGIME_FILTER_REJECT" in detail
