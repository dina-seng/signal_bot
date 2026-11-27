"""Unit tests for centralized symbol mapping, provider resolution, pip distances, and lot sizing."""

import pytest
from app.services.market_data.symbols import (
    INSTRUMENT_SPECS,
    UnknownSymbolError,
    get_instrument_spec,
    get_provider_symbol,
    normalize_symbol,
    calculate_pips,
    format_price,
)
from app.services.signals.risk_engine import RiskEngine


def test_every_configured_instrument_resolves_for_every_provider():
    """Verify every configured canonical instrument in INSTRUMENT_SPECS resolves for supported providers."""
    providers = ["twelvedata", "mock"]
    for canonical, spec in INSTRUMENT_SPECS.items():
        assert normalize_symbol(canonical) == canonical
        for prov in providers:
            prov_sym = get_provider_symbol(canonical, prov)
            assert prov_sym is not None
            assert len(prov_sym) > 0


def test_unknown_symbol_raises_unknown_symbol_error():
    """Verify UnknownSymbolError is raised for unmapped symbols and no fuzzy guessing is allowed."""
    invalid_symbols = ["INVALID", "BTC/USD", "XAG/USD", "AAPL", ""]
    for sym in invalid_symbols:
        with pytest.raises(UnknownSymbolError):
            get_instrument_spec(sym)
        with pytest.raises(UnknownSymbolError):
            normalize_symbol(sym)
        with pytest.raises(UnknownSymbolError):
            get_provider_symbol(sym, "twelvedata")


def test_pip_distance_and_price_formatting():
    """Verify pip calculations and formatting across instruments (gold, forex, JPY, index)."""
    # Gold: pip = 0.10 ($0.10) -> $5.00 move is 50 pips
    assert calculate_pips(2650.00, 2655.00, "XAU/USD") == 50.0
    assert format_price(2650.50, "XAU/USD") == "2650.50"

    # EUR/USD: pip = 0.0001
    assert calculate_pips(1.1000, 1.1050, "EUR/USD") == 50.0
    assert format_price(1.10555, "EUR/USD") == "1.10555"

    # USD/JPY: pip = 0.01 (display_decimals=3 for pipette precision)
    assert calculate_pips(150.00, 150.50, "USD/JPY") == 50.0
    assert format_price(150.25, "USD/JPY") == "150.250"

    # US100: pip/tick = 0.25 index points -> 50 points move is 200 ticks
    assert calculate_pips(20000.0, 20050.0, "US100") == 200.0
    assert format_price(20000.25, "US100") == "20000.25"


def test_risk_manager_lot_sizing_by_instrument():
    """Verify RiskEngine dynamically sizes positions based on instrument specs."""
    from app.schemas.signal import SignalDirection
    rm = RiskEngine()

    # Gold: balance $10,000, risk 0.5% = $50. SL distance ~500 pips ($5.00 distance)
    # Sizing uses centralized instrument pip specs
    res_gold = rm.calculate_trade_risk(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2650.00,
        key_support_low=2645.00,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert res_gold.suggested_lot_size is not None
    assert res_gold.suggested_lot_size > 0

    # EUR/USD: balance $10,000, risk 0.5% = $50.
    res_eur = rm.calculate_trade_risk(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        entry_price=1.1000,
        key_support_low=1.0960,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert res_eur.suggested_lot_size is not None
    assert res_eur.suggested_lot_size > 0
