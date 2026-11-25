"""Two-layer candle model: cached CLOSED history + live forming quote.

Regression cover for the chart/left-panel price gap: the dashboard snapshot
must never hand the chart a forming close derived from the 30s candle cache.
"""

from datetime import datetime, timedelta, timezone

import pytest

import app.api.v1.market as market_mod
from app.models.candle import Candle
from app.schemas.market import QuoteResponse
from app.services.market_data.cache import derived_cache, provider_cache


SNAPSHOT_URL = "/api/v1/dashboard/snapshot?symbol=XAU%2FUSD&timeframe=15m"


@pytest.fixture(autouse=True)
def _clean_caches():
    derived_cache.clear()
    provider_cache.clear()
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0
    yield
    derived_cache.clear()
    provider_cache.clear()
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0


def _seed_closed_candles(db, stale_close: float = 3447.94) -> None:
    """Two unambiguously closed 15m bars with a deliberately stale last close."""
    first = (datetime.now(timezone.utc) - timedelta(minutes=45)).replace(
        second=0, microsecond=0
    )
    for offset, close in enumerate((stale_close - 8.0, stale_close)):
        ts = first + timedelta(minutes=15 * offset)
        db.add(
            Candle(
                symbol="XAU/USD",
                timeframe="15m",
                timestamp=ts,
                open=close - 1.0,
                high=close + 2.0,
                low=close - 3.0,
                close=close,
                volume=100.0,
            )
        )
    db.commit()


def test_forming_candle_matches_quote(client, test_db_session, monkeypatch):
    """A quote P must win over the stale cached close for the newest bar."""
    _seed_closed_candles(test_db_session)
    stale_close = 3447.94
    quote_price = 3461.92

    async def fake_resolve(symbol, provider, db=None):
        return QuoteResponse(
            symbol="XAU/USD",
            price=quote_price,
            timestamp=datetime.now(timezone.utc),
            source="twelvedata",
        )

    monkeypatch.setattr(market_mod, "_resolve_quote", fake_resolve)

    resp = client.get(SNAPSHOT_URL)
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # One response, two layers: the fast tick is exposed on its own field.
    assert payload["quote"]["price"] == pytest.approx(quote_price, abs=0.01)
    assert payload["live_quote"]["price"] == pytest.approx(quote_price, abs=0.01)

    last = payload["candles"][-1]
    assert last["close"] == pytest.approx(quote_price, abs=0.01)
    assert last["close"] != pytest.approx(stale_close, abs=0.01)
    assert last["high"] >= quote_price - 1e-9
    assert last["low"] <= quote_price + 1e-9

    # The cached history objects must not be mutated by the overlay: a later
    # snapshot with a newer quote re-bases only its own copy of the last bar.
    newer_price = 3470.10

    async def newer_resolve(symbol, provider, db=None):
        return QuoteResponse(
            symbol="XAU/USD",
            price=newer_price,
            timestamp=datetime.now(timezone.utc),
            source="twelvedata",
        )

    monkeypatch.setattr(market_mod, "_resolve_quote", newer_resolve)
    second = client.get(SNAPSHOT_URL)
    assert second.status_code == 200, second.text
    assert second.json()["candles"][-1]["close"] == pytest.approx(
        newer_price, abs=0.01
    )
    # Older closed bars are untouched by either quote.
    assert second.json()["candles"][0]["close"] == pytest.approx(
        stale_close - 8.0, abs=0.01
    )


def test_historical_still_cached(client, test_db_session, monkeypatch):
    """Closed candles stay on the 30s derived cache across two snapshots."""
    _seed_closed_candles(test_db_session)

    calls = {"n": 0}
    original_get_candles = market_mod.get_candles

    def counting_get_candles(*args, **kwargs):
        calls["n"] += 1
        return original_get_candles(*args, **kwargs)

    monkeypatch.setattr(market_mod, "get_candles", counting_get_candles)

    first = client.get(SNAPSHOT_URL)
    second = client.get(SNAPSHOT_URL)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert calls["n"] == 1
    assert len(first.json()["candles"]) == len(second.json()["candles"]) > 0
