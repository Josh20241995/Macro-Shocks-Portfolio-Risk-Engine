"""
event_detection/calendar.py

Market Calendar and Session Management.

Handles US and major international market schedules including:
- Equity market open/close times
- Holiday calendars
- Early close dates
- Futures session hours
- Weekend gap corridor detection

Data source: pandas_market_calendars (mcal) with custom overrides.
Fallback to hardcoded US equity schedule when mcal unavailable.
"""

from __future__ import annotations

import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# US NYSE/NASDAQ market hours (ET)
NYSE_OPEN_HOUR, NYSE_OPEN_MIN = 9, 30
NYSE_CLOSE_HOUR, NYSE_CLOSE_MIN = 16, 0

# CME Equity Futures hours (ET) — near 24h except maintenance window
CME_FUTURES_OPEN_DAY_OFFSET = 0   # Same day as previous close + 15min
CME_FUTURES_OPEN_MIN_AFTER_CLOSE = 15  # Reopens at 4:15 PM ET
CME_FUTURES_CLOSE_FOR_MAINT_HOUR = 17  # Maintenance ~5 PM ET on Fridays


class MarketCalendar:
    """
    Manages market session state and timing computations.

    Primary use cases:
    1. Determine if markets are open at a given timestamp
    2. Find the next market open after a given timestamp
    3. Find the last market close before a given timestamp
    4. Detect holiday and early-close dates
    5. Classify weekend gap corridor conditions
    """

    def __init__(
        self,
        exchange: str = "NYSE",
        holiday_file: Optional[str] = None,
        early_close_file: Optional[str] = None,
    ):
        self.exchange = exchange
        self._holidays: Set[date] = set()
        self._early_closes: Dict[date, tuple] = {}  # date -> (close_hour, close_min)

        self._load_holidays(holiday_file)
        self._load_early_closes(early_close_file)
        self._try_load_mcal()

    def _try_load_mcal(self) -> None:
        """Attempt to load pandas_market_calendars for richer calendar data."""
        self._mcal = None
        self._mcal_cache: Dict[str, object] = {}
        try:
            import pandas_market_calendars as mcal
            self._mcal = mcal.get_calendar(self.exchange)
            logger.info("market_calendar_loaded", source="pandas_market_calendars", exchange=self.exchange)
        except ImportError:
            logger.warning(
                "pandas_market_calendars_not_available",
                fallback="hardcoded US holiday schedule",
            )

    def _load_holidays(self, holiday_file: Optional[str]) -> None:
        """Load holiday dates from JSON file or use built-in defaults."""
        if holiday_file and Path(holiday_file).exists():
            with open(holiday_file) as f:
                data = json.load(f)
            for d_str in data.get("holidays", []):
                try:
                    self._holidays.add(date.fromisoformat(d_str))
                except ValueError:
                    logger.warning("invalid_holiday_date", value=d_str)
        else:
            # Built-in US Federal holidays (approximate; update annually)
            self._holidays = self._default_us_holidays()

    def _load_early_closes(self, early_close_file: Optional[str]) -> None:
        """Load early-close dates (e.g., day before Thanksgiving, Christmas Eve)."""
        if early_close_file and Path(early_close_file).exists():
            with open(early_close_file) as f:
                data = json.load(f)
            for entry in data.get("early_closes", []):
                d = date.fromisoformat(entry["date"])
                self._early_closes[d] = (entry["close_hour"], entry["close_min"])
        else:
            self._early_closes = self._default_early_closes()

    def is_trading_day(self, dt: datetime) -> bool:
        """True if the given datetime falls on a US equity trading day."""
        d = dt.astimezone(ET).date()
        if d.weekday() >= 5:  # Saturday or Sunday
            return False
        return d not in self._holidays

    def is_holiday(self, dt: datetime) -> bool:
        """True if the given datetime falls on a US market holiday."""
        return dt.astimezone(ET).date() in self._holidays

    def market_open_time(self, for_date: date) -> Optional[datetime]:
        """Returns market open datetime (UTC) for a given date, or None if closed."""
        if for_date.weekday() >= 5 or for_date in self._holidays:
            return None
        open_dt = datetime(
            for_date.year, for_date.month, for_date.day,
            NYSE_OPEN_HOUR, NYSE_OPEN_MIN, 0,
            tzinfo=ET,
        )
        return open_dt.astimezone(UTC)

    def market_close_time(self, for_date: date) -> Optional[datetime]:
        """Returns market close datetime (UTC) for a given date, or None if closed."""
        if for_date.weekday() >= 5 or for_date in self._holidays:
            return None
        close_hour, close_min = self._early_closes.get(
            for_date, (NYSE_CLOSE_HOUR, NYSE_CLOSE_MIN)
        )
        close_dt = datetime(
            for_date.year, for_date.month, for_date.day,
            close_hour, close_min, 0,
            tzinfo=ET,
        )
        return close_dt.astimezone(UTC)

    def next_market_open(self, after: datetime) -> Optional[datetime]:
        """
        Find the next NYSE cash session open after the given timestamp.
        Searches up to 10 calendar days forward.
        """
        after_et = after.astimezone(ET)
        candidate = after_et.date()

        # If it's during today's session and not yet closed, next open is tomorrow
        if self.is_trading_day(after):
            close = self.market_close_time(candidate)
            open_today = self.market_open_time(candidate)
            if open_today and after < open_today:
                return open_today  # Today's open is still in the future
            # Markets closed for today; move to next trading day
            if close and after >= close:
                candidate += timedelta(days=1)
        else:
            candidate += timedelta(days=1)

        for _ in range(10):
            if candidate.weekday() < 5 and candidate not in self._holidays:
                return self.market_open_time(candidate)
            candidate += timedelta(days=1)

        logger.error("next_market_open_not_found", after=after.isoformat())
        return None

    def last_market_close(self, before: datetime) -> Optional[datetime]:
        """
        Find the last NYSE cash session close before or at the given timestamp.
        Searches up to 10 calendar days backward.
        """
        before_et = before.astimezone(ET)
        candidate = before_et.date()

        for _ in range(10):
            if candidate.weekday() < 5 and candidate not in self._holidays:
                close = self.market_close_time(candidate)
                if close and close <= before:
                    return close
            candidate -= timedelta(days=1)

        logger.error("last_market_close_not_found", before=before.isoformat())
        return None

    def is_in_weekend_gap_corridor(self, dt: datetime) -> bool:
        """
        Returns True if the given timestamp is in the weekend gap corridor:
        Friday at or after 4pm ET through Sunday before midnight ET (i.e., before Monday open).

        This is the highest-risk timing window for policy event detection.
        """
        dt_et = dt.astimezone(ET)
        weekday = dt_et.weekday()

        if weekday == 4:  # Friday
            return dt_et.hour >= NYSE_CLOSE_HOUR
        if weekday in (5, 6):  # Saturday, Sunday
            return True
        return False

    def hours_in_gap_corridor(self, event_time: datetime) -> Optional[float]:
        """
        Returns estimated hours from event_time until next cash market open.
        Returns None if markets are currently open.
        """
        next_open = self.next_market_open(event_time)
        if next_open is None:
            return None
        delta = next_open - event_time.astimezone(UTC)
        hours = delta.total_seconds() / 3600
        return max(0.0, hours)

    def futures_already_repriced(
        self,
        event_time: datetime,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Heuristic: returns True if ES futures markets have likely had enough
        time to reprice the event (>15 minutes post-event, futures session open).
        This informs whether 'first price discovery' has already occurred.
        """
        current_time = current_time or datetime.now(UTC)
        dt_et = current_time.astimezone(ET)
        weekday = dt_et.weekday()

        # Futures closed during CME maintenance window (approx 5-6 PM ET Friday, 4-5 PM weekdays)
        if weekday < 5:  # Weekday
            in_maint = (dt_et.hour == 17 and dt_et.minute < 0) or dt_et.hour == 0
        else:
            in_maint = False

        if in_maint:
            return False

        elapsed_minutes = (current_time - event_time.astimezone(UTC)).total_seconds() / 60
        return elapsed_minutes > 30  # Give 30 min for futures to absorb event

    @staticmethod
    def _default_us_holidays() -> Set[date]:
        """
        Approximate US Federal holiday schedule for 2020-2026.
        Source: NYSE holiday calendar. Update annually.
        Production systems should load from a maintained data file.
        """
        holidays = set()
        # Format: (year, month, day)
        raw = [
            # 2024
            (2024, 1, 1), (2024, 1, 15), (2024, 2, 19), (2024, 3, 29),
            (2024, 5, 27), (2024, 6, 19), (2024, 7, 4), (2024, 9, 2),
            (2024, 11, 28), (2024, 12, 25),
            # 2025
            (2025, 1, 1), (2025, 1, 20), (2025, 2, 17), (2025, 4, 18),
            (2025, 5, 26), (2025, 6, 19), (2025, 7, 4), (2025, 9, 1),
            (2025, 11, 27), (2025, 12, 25),
            # 2026
            (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3),
            (2026, 5, 25), (2026, 6, 19), (2026, 7, 3), (2026, 9, 7),
            (2026, 11, 26), (2026, 12, 25),
        ]
        for y, m, d in raw:
            holidays.add(date(y, m, d))
        return holidays

    @staticmethod
    def _default_early_closes() -> Dict[date, tuple]:
        """
        Approximate NYSE early-close dates (1:00 PM ET).
        Update annually. 
        """
        early_closes = {}
        # Black Friday (day after Thanksgiving) and Christmas Eve (when not weekend)
        # These are approximate; verify against NYSE official calendar each year
        raw = [
            (2024, 11, 29), (2024, 12, 24),
            (2025, 11, 28), (2025, 12, 24),
        ]
        for y, m, d in raw:
            early_closes[date(y, m, d)] = (13, 0)  # 1:00 PM close
        return early_closes

    def get_trading_days(self, start: date, end: date) -> List[date]:
        """Return list of trading days in [start, end] range."""
        result = []
        current = start
        while current <= end:
            if current.weekday() < 5 and current not in self._holidays:
                result.append(current)
            current += timedelta(days=1)
        return result
