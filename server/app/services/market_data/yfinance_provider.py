"""Yahoo Finance Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf

from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.schemas.market import QuoteResponse
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import (
    ensure_utc_datetime,
    get_timeframe_delta,
    is_candle_closed,
)


class YahooFinanceProvider(BaseMarketDataProvider):
    """Fetches real-time and historical forex/commodity OHLCV candles from Yahoo Finance."""

    # Ticker mappings: Primary ticker with list of fallback tickers
    TICKER_CANDIDATES: Dict[str, List[str]] = {
        "XAU/USD": ["GC=F", "XAUUSD=X"],
        "XAUUSD": ["GC=F", "XAUUSD=X"],
        "USD/JPY": ["JPY=X", "USDJPY=X"],
        "USDJPY": ["JPY=X", "USDJPY=X"],
        "EUR/USD": ["EURUSD=X"],
        "EURUSD": ["EURUSD=X"],
        "GBP/USD": ["GBPUSD=X"],
        "GBPUSD": ["GBPUSD=X"],
    }

    # Timeframe mapping to yfinance intervals
    INTERVAL_MAP: Dict[str, str] = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",  # Resampled from 1h
        "1d": "1d",
    }

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol has a ticker mapping."""
        clean = (symbol or "").replace(" ", "").upper()
        return clean in self.TICKER_CANDIDATES

    def _get_ticker_candidates(self, symbol: str) -> List[str]:
        """Return candidate Yahoo Finance tickers for a symbol."""
        clean = (symbol or "").replace(" ", "").upper()
        if clean in self.TICKER_CANDIDATES:
            return self.TICKER_CANDIDATES[clean]
        # Generic heuristic: if 6 alpha chars, append =X
        if len(clean) == 6 and clean.isalpha():
            return [f"{clean}=X"]
        return [clean]

    def _normalize_timeframe(self, timeframe: str) -> str:
        tf = timeframe.lower().strip()
        if tf not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(self.INTERVAL_MAP.keys())}")
        return tf

    def _parse_df_to_candles(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Convert a yfinance DataFrame into validated CandleCreate models."""
        if df.empty:
            return []

        # If MultiIndex columns (e.g. from bulk download), flatten to first level
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        # Resample to 4h if timeframe is 4h
        tf_lower = timeframe.lower().strip()
        if tf_lower == "4h":
            df = (
                df.resample("4h")
                .agg(
                    {
                        "Open": "first",
                        "High": "max",
                        "Low": "min",
                        "Close": "last",
                        "Volume": "sum",
                    }
                )
                .dropna()
            )

        candles: List[CandleCreate] = []
        now_utc = datetime.now(timezone.utc)

        for index, row in df.iterrows():
            try:
                # Ensure UTC datetime
                if isinstance(index, pd.Timestamp):
                    dt = index.to_pydatetime()
                elif isinstance(index, datetime):
                    dt = index
                else:
                    dt = pd.to_datetime(index).to_pydatetime()

                dt = ensure_utc_datetime(dt)
                if dt is None:
                    continue

                open_p = float(row["Open"])
                high_p = float(row["High"])
                low_p = float(row["Low"])
                close_p = float(row["Close"])
                vol = float(row.get("Volume", 0.0) or 0.0)

                # Skip NaN, infinite, or non-positive price rows
                if any(pd.isna([open_p, high_p, low_p, close_p])) or any(p <= 0.0 for p in [open_p, high_p, low_p, close_p]):
                    continue

                candle = CandleCreate(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=dt,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=vol,
                )
                candles.append(candle)
            except Exception as e:
                logger.debug(f"Skipping invalid candle row at {index}: {e}")
                continue

        # Sort ascending chronologically
        candles.sort(key=lambda c: c.timestamp)

        # Drop active in-progress candle if requested
        if drop_unclosed and candles:
            delta = get_timeframe_delta(tf_lower)
            if candles[-1].timestamp + delta > now_utc:
                candles = candles[:-1]

        if limit and len(candles) > limit:
            candles = candles[-limit:]

        return candles

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Fetch candles asynchronously from Yahoo Finance with ticker fallbacks."""
        candidates = self._get_ticker_candidates(symbol)
        tf = self._normalize_timeframe(timeframe)
        interval = self.INTERVAL_MAP[tf]

        # Determine appropriate historical lookback period
        if tf in ["1m", "5m"]:
            period = "5d"
        elif tf in ["15m", "30m"]:
            period = "5d"
        elif tf in ["1h", "4h"]:
            period = "60d"
        else:
            period = "60d"

        for ticker_str in candidates:
            def _fetch_sync() -> pd.DataFrame:
                try:
                    ticker = yf.Ticker(ticker_str)
                    if start_time and end_time:
                        return ticker.history(
                            interval=interval,
                            start=start_time,
                            end=end_time,
                            auto_adjust=False,
                        )
                    return ticker.history(
                        interval=interval,
                        period=period,
                        auto_adjust=False,
                    )
                except Exception as ex:
                    logger.debug(f"yfinance sync fetch exception for {ticker_str}: {ex}")
                    return pd.DataFrame()

            try:
                logger.info(f"Fetching Yahoo Finance market data for {symbol} using ticker '{ticker_str}' [{timeframe}]...")
                df = await asyncio.to_thread(_fetch_sync)
                candles = self._parse_df_to_candles(
                    df, symbol=symbol, timeframe=timeframe, limit=limit, drop_unclosed=drop_unclosed
                )

                if candles:
                    logger.info(
                        f"Successfully retrieved {len(candles)} closed candles for {symbol} via Yahoo Finance ({ticker_str}) [{timeframe}]."
                    )
                    return candles
                else:
                    logger.warning(
                        f"Yahoo Finance returned 0 valid candles for {symbol} using '{ticker_str}' [{timeframe}]. Trying next candidate..."
                    )
            except Exception as e:
                logger.warning(f"Yahoo Finance query failed for {symbol} ({ticker_str}): {e}")

        logger.error(f"YahooFinanceProvider: All candidate tickers exhausted for {symbol} [{timeframe}]. 0 candles retrieved.")
        return []

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        """Fetch the most recent closed candles for a given symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count, drop_unclosed=True)

    async def fetch_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Fetch real-time price quote from Yahoo Finance."""
        if not self.is_symbol_supported(symbol):
            logger.warning(f"YahooFinanceProvider: Unsupported symbol '{symbol}' for quote.")
            return None

        candidates = self._get_ticker_candidates(symbol)

        def _fetch_quote_sync() -> Optional[QuoteResponse]:
            for ticker_str in candidates:
                try:
                    ticker = yf.Ticker(ticker_str)
                    fast_info = getattr(ticker, "fast_info", None)
                    last_price = None
                    if fast_info:
                        last_price = fast_info.get("lastPrice") or fast_info.get("regularMarketPrice")

                    high = fast_info.get("dayHigh") if fast_info else None
                    low = fast_info.get("dayLow") if fast_info else None
                    vol = fast_info.get("lastVolume") if fast_info else None
                    bid = fast_info.get("bid") if fast_info else None
                    ask = fast_info.get("ask") if fast_info else None

                    if not last_price:
                        # Fallback to last 1m bar
                        df = ticker.history(period="1d", interval="1m", auto_adjust=False)
                        if not df.empty and "Close" in df.columns:
                            last_price = float(df["Close"].iloc[-1])
                            high = float(df["High"].max()) if high is None else high
                            low = float(df["Low"].min()) if low is None else low
                            vol = float(df["Volume"].sum()) if vol is None else vol

                    if last_price and float(last_price) > 0:
                        return QuoteResponse(
                            symbol=symbol,
                            price=float(last_price),
                            bid=float(bid) if bid else None,
                            ask=float(ask) if ask else None,
                            high=float(high) if high else None,
                            low=float(low) if low else None,
                            volume=float(vol) if vol else None,
                            timestamp=datetime.now(timezone.utc),
                            source="yfinance",
                        )
                except Exception as ex:
                    logger.debug(f"Yahoo quote error for {ticker_str}: {ex}")
            return None

        return await asyncio.to_thread(_fetch_quote_sync)
