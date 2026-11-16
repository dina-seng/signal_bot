"""Centralized Symbol Mapping and Instrument Specifications.

Provides canonical symbol resolution, per-provider symbol mapping,
and data-driven instrument specifications (pip size, point value, contract size, digits).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import html


class UnknownSymbolError(ValueError):
    """Raised when an internal or external symbol is not registered in canonical specs."""
    pass


@dataclass(frozen=True)
class InstrumentSpec:
    canonical: str
    base_currency: str
    quote_currency: str
    pip_size: float
    point_value_per_lot: float
    contract_size: float
    digits: int
    description: str


# Centralized, data-driven instrument specifications table
INSTRUMENT_SPECS: Dict[str, InstrumentSpec] = {
    "XAU/USD": InstrumentSpec(
        canonical="XAU/USD",
        base_currency="XAU",
        quote_currency="USD",
        pip_size=0.10,  # 1 pip = $0.10 for XAU/USD (standard retail broker convention; $0.01 is 1 point)
        point_value_per_lot=10.0,  # 100 oz * $0.10 = $10.00 per pip per standard lot
        contract_size=100.0,
        digits=2,
        description="Gold Spot / US Dollar",
    ),
    "EUR/USD": InstrumentSpec(
        canonical="EUR/USD",
        base_currency="EUR",
        quote_currency="USD",
        pip_size=0.0001,
        point_value_per_lot=10.0,  # 100,000 * 0.0001 = $10.00 per pip per standard lot
        contract_size=100000.0,
        digits=5,
        description="Euro / US Dollar",
    ),
    "USD/JPY": InstrumentSpec(
        canonical="USD/JPY",
        base_currency="USD",
        quote_currency="JPY",
        pip_size=0.01,
        point_value_per_lot=10.0,  # approximate $10/pip per standard lot
        contract_size=100000.0,
        digits=3,
        description="US Dollar / Japanese Yen",
    ),
    "GBP/USD": InstrumentSpec(
        canonical="GBP/USD",
        base_currency="GBP",
        quote_currency="USD",
        pip_size=0.0001,
        point_value_per_lot=10.0,
        contract_size=100000.0,
        digits=5,
        description="British Pound / US Dollar",
    ),
    "US100": InstrumentSpec(
        canonical="US100",
        base_currency="USD",
        quote_currency="USD",
        pip_size=0.25,
        point_value_per_lot=20.0,  # $20 per point per contract
        contract_size=20.0,
        digits=2,
        description="Nasdaq 100 Index",
    ),
}


def normalize_symbol(symbol: str) -> str:
    """Resolve a raw symbol string into its canonical internal symbol.
    
    Raises UnknownSymbolError if symbol cannot be resolved.
    NEVER guesses or fuzzy-matches unknown symbols.
    """
    if not symbol:
        raise UnknownSymbolError("Symbol cannot be empty.")
    
    clean = symbol.strip().upper().replace("%2F", "/")
    
    # 1. Direct exact canonical match
    if clean in INSTRUMENT_SPECS:
        return clean
        
    # 2. Match standard alias without slash (e.g. XAUUSD -> XAU/USD)
    for canonical in INSTRUMENT_SPECS:
        if canonical.replace("/", "") == clean.replace("/", ""):
            return canonical
            
    raise UnknownSymbolError(f"Unknown symbol: '{symbol}'. Configured: {list(INSTRUMENT_SPECS.keys())}")


def get_instrument_spec(symbol: str) -> InstrumentSpec:
    """Retrieve the instrument specification for a symbol."""
    canonical = normalize_symbol(symbol)
    return INSTRUMENT_SPECS[canonical]


def get_provider_symbol(symbol: str, provider: str, yahoo_gold_symbol: Optional[str] = None) -> str:
    """Map canonical internal symbol to the provider's upstream ticker.
    
    Raises UnknownSymbolError if unmapped. NEVER passes canonical symbols with '/' into yfinance.
    """
    canonical = normalize_symbol(symbol)
    provider_key = provider.lower().strip()
    
    if provider_key in ("twelvedata", "twelve_data"):
        twelve_map = {
            "XAU/USD": "XAU/USD",
            "EUR/USD": "EUR/USD",
            "USD/JPY": "USD/JPY",
            "GBP/USD": "GBP/USD",
            "US100": "US100",
        }
        if canonical not in twelve_map:
            raise UnknownSymbolError(f"TwelveData mapping not found for symbol '{canonical}'")
        return twelve_map[canonical]
        
    elif provider_key == "mock":
        mock_map = {
            "XAU/USD": "MOCK_XAUUSD",
            "EUR/USD": "MOCK_EURUSD",
            "USD/JPY": "MOCK_USDJPY",
            "GBP/USD": "MOCK_GBPUSD",
            "US100": "MOCK_US100",
        }
        if canonical not in mock_map:
            raise UnknownSymbolError(f"Mock mapping not found for symbol '{canonical}'")
        return mock_map[canonical]
        
    else:
        raise UnknownSymbolError(f"Unknown provider '{provider}'")


def format_price(price: Optional[float], symbol: str) -> str:
    """Format price with instrument-specific decimal digits."""
    if price is None:
        return "N/A"
    try:
        spec = get_instrument_spec(symbol)
        return f"{price:.{spec.digits}f}"
    except UnknownSymbolError:
        return f"{price:.2f}"


def calculate_pips(entry: float, target: float, symbol: str) -> float:
    """Calculate pip distance using the instrument's configured pip_size."""
    diff = abs(entry - target)
    try:
        spec = get_instrument_spec(symbol)
        if spec.pip_size > 0:
            return round(diff / spec.pip_size, 1)
    except UnknownSymbolError:
        pass
    return round(diff / 0.01, 1)
