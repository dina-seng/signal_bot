"""Yahoo Finance Market Data Provider for Forex and Commodities."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf
from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider


class YahooFinanceProvider(BaseMarketDataProvider):
    """Fetches real-time and historical forex/commodity OHLCV candles from Yahoo Finance."""

    # Ticker mapping for standard symbols
    SYMBOL_MAP: Dict[str, str] = {
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "XAU/USD": "GC=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "XAUUSD": "GC=F",
    }

    # Timeframe mapping to yfinance intervals
    INTERVAL_MAP: Dict[str, str] = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",  # Will resample from 1h
        "1d": "1d",
    }

    def is_symbol_supported(self, symbol: str) -> bool:
        normalized = symbol.replace(" ", "").upper()
        return normalized in self.SYMBOL_MAP

    def _get_ticker(self, symbol: str) -> str:
        normalized = symbol.replace(" ", "").upper()
        ticker = self.SYMBOL_MAP.get(normalized)
        if not ticker:
            # Try appending =X if 6 letters (e.g. AUDUSD -> AUDUSD=X)
            if len(normalized) == 6 and normalized.isalpha():
                return f"{normalized}=X"
            raise ValueError(f"Unsupported symbol '{symbol}' for YahooFinanceProvider")
        return ticker

    def _normalize_timeframe(self, timeframe: str) -> str:
        tf = timeframe.lower().strip()
        if tf not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(self.INTERVAL_MAP.keys())}")
        return tf

    def _parse_df_to_candles(
        self, df: pd.DataFrame, symbol: str, timeframe: str, limit: int
    ) -> List[CandleCreate]:
        """Convert a yfinance DataFrame into validated CandleCreate models."""
        if df.empty:
            return []

        # If MultiIndex columns, flatten
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        # Resample to 4h if timeframe is 4h
        if timeframe.lower() == "4h":
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

        for index, row in df.iterrows():
            try:
                # Ensure UTC datetime
                if isinstance(index, pd.Timestamp):
                    dt = index.to_pydatetime()
                elif isinstance(index, datetime):
                    dt = index
                else:
                    dt = pd.to_datetime(index).to_pydatetime()

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)

                open_p = float(row["Open"])
                high_p = float(row["High"])
                low_p = float(row["Low"])
                close_p = float(row["Close"])
                vol = float(row.get("Volume", 0.0) or 0.0)

                # Skip NaN or non-positive price rows
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

        # Sort chronologically ascending
        candles.sort(key=lambda c: c.timestamp)

        if limit and len(candles) > limit:
            candles = candles[-limit:]

        return candles

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[CandleCreate]:
        """Fetch candles asynchronously from Yahoo Finance."""
        ticker_str = self._get_ticker(symbol)
        tf = self._normalize_timeframe(timeframe)
        interval = self.INTERVAL_MAP[tf]

        # In yfinance, 15m allows max 60 days, 1h allows 730 days
        period = "30d" if tf in ["1m", "5m", "15m", "30m"] else "60d"

        def _fetch():
            ticker = yf.Ticker(ticker_str)
            if start_time and end_time:
                return ticker.history(
                    interval=interval,
                    start=start_time,
                    end=end_time,
                    auto_adjust=False,
                )
            else:
                return ticker.history(
                    interval=interval,
                    period=period,
                    auto_adjust=False,
                )

        try:
            logger.info(f"Fetching market data for {symbol} ({ticker_str}) - {timeframe} from Yahoo Finance")
            df = await asyncio.to_thread(_fetch)
            candles = self._parse_df_to_candles(df, symbol, timeframe, limit)
            logger.info(f"Successfully retrieved {len(candles)} candles for {symbol} ({timeframe})")
            return candles
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol} ({timeframe}) from Yahoo Finance: {e}")
            return []

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        """Fetch the most recent candles for a symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count)
