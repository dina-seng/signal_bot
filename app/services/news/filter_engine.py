"""Economic News Blackout Filter Engine."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.models.news import NewsEvent
from app.schemas.news import (
    NewsBlackoutCheckResponse,
    NewsEventResponse,
    NewsImpact,
)


class NewsFilterEngine:
    """Evaluates whether market instruments are currently in a high-volatility news blackout window."""

    def __init__(
        self,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
    ):
        self.before_minutes = before_minutes or settings.NEWS_BLACKOUT_BEFORE_MINUTES
        self.after_minutes = after_minutes or settings.NEWS_BLACKOUT_AFTER_MINUTES

    @staticmethod
    def extract_currencies_for_symbol(symbol: str) -> List[str]:
        """Extract all currencies associated with a Forex or Commodity symbol."""
        clean = symbol.replace("%2F", "/").upper().strip()
        if "/" in clean:
            parts = clean.split("/")
            return [parts[0].strip(), parts[1].strip()]

        # Fallback for symbols without slash e.g. EURUSD, XAUUSD
        if len(clean) == 6:
            return [clean[:3], clean[3:]]

        return ["USD"]

    def is_trading_allowed(
        self,
        symbol: str,
        events: List[NewsEvent],
        target_time: Optional[datetime] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
        min_impact: str = "HIGH",
    ) -> NewsBlackoutCheckResponse:
        """Evaluate blackout status for a symbol against a list of economic news events.

        Args:
            symbol: Forex instrument (e.g. 'EUR/USD').
            events: List of NewsEvent database models or schemas.
            target_time: Reference UTC datetime to evaluate (defaults to utcnow).
            before_minutes: Pre-news blackout buffer minutes.
            after_minutes: Post-news blackout buffer minutes.
            min_impact: Minimum impact level to trigger blackout ('HIGH' or 'MEDIUM').

        Returns:
            NewsBlackoutCheckResponse.
        """
        ref_time = target_time or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        else:
            ref_time = ref_time.astimezone(timezone.utc)

        b_min = before_minutes if before_minutes is not None else self.before_minutes
        a_min = after_minutes if after_minutes is not None else self.after_minutes

        symbol_currencies = set(self.extract_currencies_for_symbol(symbol))
        # Gold (XAU) is heavily sensitive to USD macro events
        if "XAU" in symbol_currencies:
            symbol_currencies.add("USD")

        active_blackout_events: List[NewsEventResponse] = []
        future_events: List[NewsEvent] = []
        past_events: List[NewsEvent] = []

        impact_filter = {"HIGH"} if min_impact.upper() == "HIGH" else {"HIGH", "MEDIUM"}

        for ev in events:
            ev_curr = ev.currency.upper().strip()
            if ev_curr not in symbol_currencies:
                continue

            ev_impact = ev.impact.upper().strip()
            if ev_impact not in impact_filter:
                continue

            ev_time = ev.scheduled_time
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=timezone.utc)
            else:
                ev_time = ev_time.astimezone(timezone.utc)

            blackout_start = ev_time - timedelta(minutes=b_min)
            blackout_end = ev_time + timedelta(minutes=a_min)

            if blackout_start <= ref_time <= blackout_end:
                active_blackout_events.append(
                    NewsEventResponse(
                        id=getattr(ev, "id", 0) or 0,
                        currency=ev.currency,
                        event_name=ev.event_name,
                        impact=NewsImpact(ev.impact.upper()),
                        scheduled_time=ev_time,
                        previous=ev.previous,
                        forecast=ev.forecast,
                        actual=ev.actual,
                        created_at=getattr(ev, "created_at", None) or ev_time,
                    )
                )

            if ev_time > ref_time:
                future_events.append(ev)
            elif ev_time <= ref_time:
                past_events.append(ev)

        # Sort nearest future event and nearest past event
        future_events.sort(key=lambda e: e.scheduled_time)
        past_events.sort(key=lambda e: e.scheduled_time, reverse=True)

        next_event_resp: Optional[NewsEventResponse] = None
        minutes_to_next: Optional[float] = None
        if future_events:
            nxt = future_events[0]
            nxt_t = nxt.scheduled_time.replace(tzinfo=timezone.utc) if nxt.scheduled_time.tzinfo is None else nxt.scheduled_time.astimezone(timezone.utc)
            minutes_to_next = round((nxt_t - ref_time).total_seconds() / 60.0, 1)
            next_event_resp = NewsEventResponse(
                id=getattr(nxt, "id", 0) or 0,
                currency=nxt.currency,
                event_name=nxt.event_name,
                impact=NewsImpact(nxt.impact.upper()),
                scheduled_time=nxt_t,
                previous=nxt.previous,
                forecast=nxt.forecast,
                actual=nxt.actual,
                created_at=getattr(nxt, "created_at", None) or nxt_t,
            )

        minutes_since_last: Optional[float] = None
        if past_events:
            pst = past_events[0]
            pst_t = pst.scheduled_time.replace(tzinfo=timezone.utc) if pst.scheduled_time.tzinfo is None else pst.scheduled_time.astimezone(timezone.utc)
            minutes_since_last = round((ref_time - pst_t).total_seconds() / 60.0, 1)

        is_blackout = len(active_blackout_events) > 0
        trading_allowed = not is_blackout

        if is_blackout:
            ev_names = ", ".join([f"{e.currency} {e.event_name}" for e in active_blackout_events])
            reason = (
                f"TRADING BLOCKED: {symbol} is inside active news blackout window ({b_min}m before / {a_min}m after) "
                f"due to high-impact release: [{ev_names}]."
            )
        else:
            if next_event_resp and minutes_to_next is not None and minutes_to_next <= 120:
                reason = (
                    f"TRADING ALLOWED: No active blackout for {symbol}. "
                    f"Next major event '{next_event_resp.currency} {next_event_resp.event_name}' in {minutes_to_next:.0f} minutes."
                )
            else:
                reason = f"TRADING ALLOWED: No conflicting high-impact economic releases active for {symbol}."

        return NewsBlackoutCheckResponse(
            symbol=symbol,
            checked_time=ref_time,
            is_blackout=is_blackout,
            trading_allowed=trading_allowed,
            reason=reason,
            blackout_events=active_blackout_events,
            next_event=next_event_resp,
            minutes_to_next_event=minutes_to_next,
            minutes_since_last_event=minutes_since_last,
        )

    def check_from_db(
        self,
        db: Session,
        symbol: str,
        target_time: Optional[datetime] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
        min_impact: str = "HIGH",
    ) -> NewsBlackoutCheckResponse:
        """Query news events from database within a +/- 24h window and evaluate blackout status."""
        ref_time = target_time or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        else:
            ref_time = ref_time.astimezone(timezone.utc)

        symbol_currencies = self.extract_currencies_for_symbol(symbol)
        if "XAU" in symbol_currencies:
            symbol_currencies.append("USD")

        window_start = ref_time - timedelta(hours=24)
        window_end = ref_time + timedelta(hours=24)

        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.currency.in_(symbol_currencies),
                NewsEvent.scheduled_time >= window_start,
                NewsEvent.scheduled_time <= window_end,
            )
            .order_by(NewsEvent.scheduled_time.asc())
        )

        db_events = list(db.scalars(stmt).all())

        return self.is_trading_allowed(
            symbol=symbol,
            events=db_events,
            target_time=ref_time,
            before_minutes=before_minutes,
            after_minutes=after_minutes,
            min_impact=min_impact,
        )
