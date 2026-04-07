"""
event_detection/detector.py

Event Detection and Classification Engine.

Monitors event feeds (calendar, news, unstructured text) to detect
macro-relevant policy communications. Classifies by type, timing,
and severity. Applies special logic for after-hours, weekend, and
holiday events. This is Layer 1 (deterministic rules) in the modeling hierarchy.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog

from macro_shock.data_schema.models import (
    EventType,
    MacroEvent,
    MarketSessionState,
    SeverityLevel,
)
from macro_shock.event_detection.calendar import MarketCalendar

logger = structlog.get_logger(__name__)

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Institution and Speaker Configuration
# ---------------------------------------------------------------------------

INSTITUTION_CONFIG: Dict[str, Dict] = {
    "Federal Reserve": {
        "weight": 1.0,
        "aliases": ["Fed", "FOMC", "Federal Open Market Committee", "Federal Reserve Board"],
        "high_impact_speakers": ["Chair", "Chairman", "Chairwoman", "Vice Chair"],
        "medium_impact_speakers": ["President", "Governor"],
    },
    "U.S. Treasury": {
        "weight": 0.85,
        "aliases": ["Treasury", "Treasury Department", "Secretary of Treasury"],
        "high_impact_speakers": ["Secretary", "Under Secretary"],
        "medium_impact_speakers": ["Deputy Secretary", "Assistant Secretary"],
    },
    "White House": {
        "weight": 0.80,
        "aliases": ["President", "White House", "Administration", "Executive Office"],
        "high_impact_speakers": ["President of the United States", "Press Secretary"],
        "medium_impact_speakers": ["National Security Advisor", "Chief of Staff"],
    },
    "Bank for International Settlements": {
        "weight": 0.70,
        "aliases": ["BIS"],
        "high_impact_speakers": ["General Manager"],
        "medium_impact_speakers": [],
    },
    "International Monetary Fund": {
        "weight": 0.70,
        "aliases": ["IMF"],
        "high_impact_speakers": ["Managing Director"],
        "medium_impact_speakers": [],
    },
    "European Central Bank": {
        "weight": 0.75,
        "aliases": ["ECB", "Eurosystem"],
        "high_impact_speakers": ["President", "Vice President"],
        "medium_impact_speakers": ["Chief Economist", "Executive Board"],
    },
    "Bank of Japan": {
        "weight": 0.65,
        "aliases": ["BOJ", "Bank of Japan"],
        "high_impact_speakers": ["Governor"],
        "medium_impact_speakers": ["Deputy Governor"],
    },
}

# Phrases triggering immediate UNSCHEDULED classification
EMERGENCY_TRIGGER_PHRASES: List[str] = [
    "emergency meeting",
    "intermeeting action",
    "emergency rate cut",
    "emergency rate increase",
    "extraordinary measures",
    "market stabilization",
    "financial stability concern",
    "systemic risk",
    "circuit breaker",
    "coordinated central bank action",
    "emergency liquidity",
    "bank failure",
    "sovereign default",
    "market closure",
    "trading halt",
    "force majeure",
    "national emergency",
    "executive order",
]

# Phrases indicating financial stability concerns
FINANCIAL_STABILITY_PHRASES: List[str] = [
    "financial stability",
    "contagion",
    "systemic",
    "bank run",
    "liquidity crisis",
    "credit crunch",
    "deleveraging",
    "fire sale",
    "margin calls",
    "forced selling",
    "funding stress",
    "counterparty risk",
]

# US market session schedule (Eastern Time)
EQUITY_MARKET_OPEN = (9, 30)   # 9:30 AM ET
EQUITY_MARKET_CLOSE = (16, 0)  # 4:00 PM ET
FUTURES_REOPEN_OFFSET_MINUTES = 15  # ES opens ~15 min after close


class EventDetector:
    """
    Primary event detection and classification system.

    Ingests raw event records from multiple sources (structured calendar data,
    news headlines, transcript text) and produces classified MacroEvent objects.

    Design philosophy:
    - All classification logic is deterministic and explainable (Layer 1)
    - Conservative: prefer over-classification to under-classification
    - Weekend and after-hours events are treated as the most dangerous class
    - NLP models operate downstream; this module handles structural classification
    """

    def __init__(self, calendar: MarketCalendar, config: Optional[Dict] = None):
        self.calendar = calendar
        self.config = config or {}
        self._load_config()

    def _load_config(self) -> None:
        self.min_severity_to_process = self.config.get("min_severity_score", 10.0)
        self.after_hours_severity_boost = self.config.get("after_hours_severity_boost", 15.0)
        self.weekend_severity_boost = self.config.get("weekend_severity_boost", 25.0)
        self.emergency_severity_boost = self.config.get("emergency_severity_boost", 35.0)

    def detect_and_classify(
        self,
        raw_event: Dict,
        detection_time: Optional[datetime] = None,
    ) -> Optional[MacroEvent]:
        """
        Primary entry point. Takes a raw event dict and returns a
        classified MacroEvent, or None if below severity threshold.

        Args:
            raw_event: Dict with keys: title, description, institution,
                       speaker, event_time (ISO str), source_url, raw_text
            detection_time: When the system detected this event. Defaults to now.
        """
        detection_time = detection_time or datetime.now(timezone.utc)

        try:
            event_timestamp = self._parse_timestamp(raw_event.get("event_time", ""))
        except ValueError as e:
            logger.warning("event_timestamp_parse_failed", error=str(e), raw=raw_event)
            return None

        institution = self._normalize_institution(raw_event.get("institution", ""))
        if institution not in INSTITUTION_CONFIG:
            logger.debug("institution_not_tracked", institution=institution)
            return None

        event_type = self._classify_event_type(raw_event, event_timestamp)
        session_state = self._classify_session_state(event_timestamp)
        timing_context = self._compute_timing_context(event_timestamp)
        severity_score = self._compute_severity_score(
            raw_event, institution, event_type, session_state, timing_context
        )

        if severity_score < self.min_severity_to_process:
            logger.debug(
                "event_below_threshold",
                title=raw_event.get("title"),
                score=severity_score,
            )
            return None

        severity_level = self._score_to_level(severity_score)

        event = MacroEvent(
            detected_at=detection_time,
            event_timestamp=event_timestamp,
            event_type=event_type,
            severity=severity_level,
            severity_score=severity_score,
            institution=institution,
            speaker=raw_event.get("speaker"),
            speaker_role=raw_event.get("speaker_role"),
            title=raw_event.get("title", "Untitled Event"),
            description=raw_event.get("description"),
            source_url=raw_event.get("source_url"),
            is_scheduled=event_type not in (
                EventType.UNSCHEDULED_EMERGENCY,
                EventType.GEOPOLITICAL_SURPRISE,
            ),
            is_weekend=timing_context["is_weekend"],
            is_after_hours=timing_context["is_after_hours"],
            market_session_at_event=session_state,
            minutes_since_close=timing_context.get("minutes_since_close"),
            full_weekend_gap=timing_context["full_weekend_gap"],
            next_market_open=timing_context.get("next_open"),
            hours_until_next_open=timing_context.get("hours_until_next_open"),
            raw_text=raw_event.get("raw_text"),
            headline_summary=raw_event.get("headline_summary"),
        )

        logger.info(
            "event_classified",
            event_id=event.event_id,
            event_type=event_type,
            severity=severity_level,
            score=severity_score,
            weekend_gap=event.full_weekend_gap,
            hours_until_open=event.hours_until_next_open,
        )
        return event

    def _classify_event_type(self, raw_event: Dict, event_time: datetime) -> EventType:
        """
        Deterministic event type classification.
        Priority order: emergency signals > timing signals > calendar signals.
        """
        title = raw_event.get("title", "").lower()
        description = raw_event.get("description", "").lower()
        raw_text = raw_event.get("raw_text", "").lower()
        full_text = f"{title} {description} {raw_text}"

        # Check emergency triggers first (highest priority)
        for phrase in EMERGENCY_TRIGGER_PHRASES:
            if phrase in full_text:
                logger.info(
                    "emergency_trigger_detected",
                    phrase=phrase,
                    title=raw_event.get("title"),
                )
                return EventType.UNSCHEDULED_EMERGENCY

        # Intermeeting action detection
        if re.search(r"inter.?meeting|between.?meeting|unscheduled.?rate", full_text):
            return EventType.INTERMEETING_RATE_ACTION

        # Financial stability statement
        stability_count = sum(
            1 for phrase in FINANCIAL_STABILITY_PHRASES if phrase in full_text
        )
        if stability_count >= 2:
            return EventType.FINANCIAL_STABILITY_STATEMENT

        # Weekend event
        event_et = event_time.astimezone(ET)
        if event_et.weekday() >= 5:  # Saturday=5, Sunday=6
            return EventType.WEEKEND_POLICY_ACTION

        # After-hours detection
        hour, minute = event_et.hour, event_et.minute
        is_after_close = (hour, minute) >= EQUITY_MARKET_CLOSE
        is_before_open = (hour, minute) < EQUITY_MARKET_OPEN

        # Press conference pattern
        if "press conference" in full_text or "q&a" in full_text:
            if is_after_close or is_before_open:
                return EventType.SCHEDULED_POST_CLOSE
            return EventType.PRESS_CONFERENCE

        # Congressional testimony
        if re.search(r"congress|senate|house|testimony|hearing", full_text):
            return EventType.CONGRESSIONAL_TESTIMONY

        # Geopolitical signals
        geo_signals = [
            "war", "conflict", "attack", "invasion", "sanctions",
            "trade war", "tariff", "national security",
        ]
        if any(s in full_text for s in geo_signals):
            return EventType.GEOPOLITICAL_SURPRISE

        # Default based on timing
        if is_after_close or is_before_open:
            return EventType.SCHEDULED_POST_CLOSE

        return EventType.PRESS_CONFERENCE

    def _classify_session_state(self, event_time: datetime) -> MarketSessionState:
        event_et = event_time.astimezone(ET)
        weekday = event_et.weekday()  # 0=Monday, 6=Sunday
        hour, minute = event_et.hour, event_et.minute
        time_tuple = (hour, minute)

        if weekday >= 5:
            return MarketSessionState.CLOSED_WEEKEND

        if self.calendar.is_holiday(event_time):
            return MarketSessionState.CLOSED_HOLIDAY

        if EQUITY_MARKET_OPEN <= time_tuple < EQUITY_MARKET_CLOSE:
            return MarketSessionState.OPEN

        if (4, 0) <= time_tuple < EQUITY_MARKET_OPEN:
            return MarketSessionState.PRE_MARKET

        if EQUITY_MARKET_CLOSE <= time_tuple < (20, 0):
            return MarketSessionState.AFTER_HOURS

        return MarketSessionState.CLOSED_OVERNIGHT

    def _compute_timing_context(self, event_time: datetime) -> Dict:
        """
        Compute all timing metadata relevant to gap risk assessment.
        This is the heart of the weekend-gap corridor detection.
        """
        event_et = event_time.astimezone(ET)
        weekday = event_et.weekday()
        hour, minute = event_et.hour, event_et.minute

        is_weekend = weekday >= 5
        is_friday_after_close = (
            weekday == 4
            and (hour, minute) >= EQUITY_MARKET_CLOSE
        )
        is_after_hours = (
            not is_weekend
            and ((hour, minute) >= EQUITY_MARKET_CLOSE or (hour, minute) < EQUITY_MARKET_OPEN)
        )

        # Full weekend gap: event on Friday after close, or Saturday/Sunday
        full_weekend_gap = is_weekend or is_friday_after_close

        # Find next market open
        next_open = self.calendar.next_market_open(event_time)
        hours_until_next_open = None
        if next_open:
            delta = next_open - event_time
            hours_until_next_open = delta.total_seconds() / 3600

        # Minutes since last close
        last_close = self.calendar.last_market_close(event_time)
        minutes_since_close = None
        if last_close and last_close < event_time:
            delta = event_time - last_close
            minutes_since_close = delta.total_seconds() / 60

        return {
            "is_weekend": is_weekend,
            "is_after_hours": is_after_hours,
            "is_friday_after_close": is_friday_after_close,
            "full_weekend_gap": full_weekend_gap,
            "next_open": next_open,
            "hours_until_next_open": hours_until_next_open,
            "minutes_since_close": minutes_since_close,
            "weekday": weekday,
        }

    def _compute_severity_score(
        self,
        raw_event: Dict,
        institution: str,
        event_type: EventType,
        session_state: MarketSessionState,
        timing_context: Dict,
    ) -> float:
        """
        Compute a severity score on [0, 100].
        Higher = more market-moving potential.

        Factors:
        1. Institution weight (Fed > Treasury > ECB)
        2. Speaker seniority (Chair > President > Staff)
        3. Event type (emergency > press conference > statement)
        4. Timing (weekend > after-hours > intraday)
        5. Content signals (emergency language, financial stability)
        """
        score = 0.0

        # 1. Base institution score (0-30)
        inst_config = INSTITUTION_CONFIG.get(institution, {})
        institution_weight = inst_config.get("weight", 0.5)
        score += 30.0 * institution_weight

        # 2. Speaker seniority (0-20)
        speaker_role = raw_event.get("speaker_role", "")
        high_impact = inst_config.get("high_impact_speakers", [])
        medium_impact = inst_config.get("medium_impact_speakers", [])
        if any(role in speaker_role for role in high_impact):
            score += 20.0
        elif any(role in speaker_role for role in medium_impact):
            score += 10.0
        else:
            score += 5.0

        # 3. Event type base score (0-25)
        event_type_scores = {
            EventType.UNSCHEDULED_EMERGENCY: 25.0,
            EventType.INTERMEETING_RATE_ACTION: 25.0,
            EventType.FINANCIAL_STABILITY_STATEMENT: 22.0,
            EventType.WEEKEND_POLICY_ACTION: 20.0,
            EventType.GEOPOLITICAL_SURPRISE: 20.0,
            EventType.PRESS_CONFERENCE: 15.0,
            EventType.SCHEDULED_POST_CLOSE: 12.0,
            EventType.CONGRESSIONAL_TESTIMONY: 10.0,
            EventType.UNKNOWN: 5.0,
        }
        score += event_type_scores.get(event_type, 5.0)

        # 4. Timing multiplier (boost for after-hours/weekend)
        if timing_context["full_weekend_gap"]:
            score += self.weekend_severity_boost
        elif timing_context["is_after_hours"]:
            score += self.after_hours_severity_boost

        # 5. Emergency content boost
        full_text = " ".join([
            raw_event.get("title", ""),
            raw_event.get("description", ""),
            raw_event.get("raw_text", ""),
        ]).lower()
        for phrase in EMERGENCY_TRIGGER_PHRASES:
            if phrase in full_text:
                score += self.emergency_severity_boost
                break  # only count once

        return min(score, 100.0)

    def _score_to_level(self, score: float) -> SeverityLevel:
        if score >= 75:
            return SeverityLevel.CRITICAL
        elif score >= 55:
            return SeverityLevel.HIGH
        elif score >= 35:
            return SeverityLevel.MEDIUM
        elif score >= 15:
            return SeverityLevel.LOW
        return SeverityLevel.INFORMATIONAL

    def _normalize_institution(self, raw: str) -> str:
        """Resolve institution aliases to canonical names."""
        raw_lower = raw.lower().strip()
        for canonical, config in INSTITUTION_CONFIG.items():
            aliases = [a.lower() for a in config.get("aliases", [])]
            if raw_lower == canonical.lower() or raw_lower in aliases:
                return canonical
        return raw  # return as-is; caller will check if tracked

    def _parse_timestamp(self, time_str: str) -> datetime:
        """
        Parse ISO 8601 timestamp string to UTC datetime.
        Raises ValueError on invalid input.
        """
        if not time_str:
            raise ValueError("Empty timestamp string")
        try:
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Cannot parse timestamp '{time_str}': {e}") from e

    def batch_detect(self, raw_events: List[Dict]) -> List[MacroEvent]:
        """Process a batch of raw events. Returns only those passing threshold."""
        results = []
        for raw in raw_events:
            event = self.detect_and_classify(raw)
            if event is not None:
                results.append(event)
        results.sort(key=lambda e: e.severity_score, reverse=True)
        return results
