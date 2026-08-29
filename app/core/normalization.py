"""Canonical Normalization Utilities for Symbols, Timeframes, and Datetimes.

Provides single-source-of-truth normalization across API endpoints, data ingestion,
scanners, evaluators, and paper trading services.
"""

from datetime import datetime, timezone
from typing import Optional

# Canonical supported symbols map
SYMBOL_MAP = {
    # Euro
    "EURUSD": "EUR/USD",
    "EUR/USD": "EUR/USD",
    "EUR_USD": "EUR/USD",
    "EURUSD=X": "EUR/USD",
    # British Pound
    "GBPUSD": "GBP/USD",
    "GBP/USD": "GBP/USD",
    "GBP_USD": "GBP/USD",
    "GBPUSD=X": "GBP/USD",
    # Japanese Yen
    "USDJPY": "USD/JPY",
    "USD/JPY": "USD/JPY",
    "USD_JPY": "USD/JPY",
    "USDJPY=X": "USD/JPY",
    "JPY=X": "USD/JPY",
    # Gold (Commodity)
    "XAUUSD": "XAU/USD",
    "XAU/USD": "XAU/USD",
    "XAU_USD": "XAU/USD",
    "GC=F": "XAU/USD",
    "GOLD": "XAU/USD",
}

TIMEFRAME_MAP = {
    "1M": "1m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
    "D1": "1d",
    "1W": "1w",
    "W1": "1w",
}


def normalize_symbol(raw_symbol: str) -> str:
    """Normalize any symbol variation into canonical slash format (e.g. 'EUR/USD').

    Handles url-encoded slashes (%2F), uppercase/lowercase, underscores, Yahoo ticker suffixes.
    """
    if not raw_symbol:
        return ""

    sym = raw_symbol.replace("%2F", "/").replace("%2f", "/").strip().upper()

    # Direct map lookup
    if sym in SYMBOL_MAP:
        return SYMBOL_MAP[sym]

    # Clean punctuation
    cleaned = sym.replace("/", "").replace("_", "").replace("-", "")
    if cleaned in SYMBOL_MAP:
        return SYMBOL_MAP[cleaned]

    # Standard 6-character forex pairs fallback (e.g. AUDUSD -> AUD/USD)
    if len(cleaned) == 6 and cleaned.isalpha():
        return f"{cleaned[:3]}/{cleaned[3:]}"

    return sym


def normalize_timeframe(raw_timeframe: str) -> str:
    """Normalize timeframe string to standard lowercase format (e.g. '15m', '1h', '4h')."""
    if not raw_timeframe:
        return "1h"

    tf = raw_timeframe.strip().upper()
    return TIMEFRAME_MAP.get(tf, tf.lower())


def normalize_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is UTC timezone-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
