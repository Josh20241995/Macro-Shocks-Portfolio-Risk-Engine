"""
tests/fixtures/market_fixtures.py

Reusable pytest fixtures for market state, events, and surprise vectors.
Import these in test files via: from python.tests.fixtures.market_fixtures import *
Or register conftest.py to make them available automatically.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.data_schema.models import (
    EventType,
    HawkishDovishScore,
    MacroEvent,
    MarketSessionState,
    PolicyStance,
    PolicySurpriseVector,
    SeverityLevel,
)
from macro_shock.event_detection.calendar import MarketCalendar


@pytest.fixture(scope="session")
def shared_calendar():
    """Session-scoped calendar to avoid repeated initialization."""
    return MarketCalendar()


@pytest.fixture
def normal_market(shared_calendar):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc),
        calendar=shared_calendar,
        stress_level=0.20,
        seed=100,
    )


@pytest.fixture
def moderate_stress_market(shared_calendar):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc),
        calendar=shared_calendar,
        stress_level=0.50,
        seed=101,
    )


@pytest.fixture
def crisis_market(shared_calendar):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc),
        calendar=shared_calendar,
        stress_level=0.90,
        seed=102,
    )


@pytest.fixture
def weekend_emergency_event():
    return MacroEvent(
        detected_at=datetime(2024, 3, 9, 19, 5, tzinfo=timezone.utc),
        event_timestamp=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        event_type=EventType.UNSCHEDULED_EMERGENCY,
        severity=SeverityLevel.CRITICAL,
        severity_score=94.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="Emergency Fed Statement — Weekend",
        is_weekend=True,
        is_after_hours=True,
        full_weekend_gap=True,
        market_session_at_event=MarketSessionState.CLOSED_WEEKEND,
        hours_until_next_open=53.5,
        minutes_since_close=1800.0,
        raw_text="Emergency measures. Systemic risk. Financial stability concerns. Crisis.",
    )


@pytest.fixture
def intraday_fomc_event():
    return MacroEvent(
        detected_at=datetime(2024, 1, 31, 18, 35, tzinfo=timezone.utc),
        event_timestamp=datetime(2024, 1, 31, 18, 30, tzinfo=timezone.utc),
        event_type=EventType.PRESS_CONFERENCE,
        severity=SeverityLevel.MEDIUM,
        severity_score=52.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="FOMC Press Conference",
        is_weekend=False,
        is_after_hours=False,
        full_weekend_gap=False,
        market_session_at_event=MarketSessionState.OPEN,
    )


@pytest.fixture
def crisis_surprise(weekend_emergency_event):
    hd = HawkishDovishScore(
        overall_score=-0.88,
        stance=PolicyStance.CRISIS_EASING,
        confidence=0.92,
        urgency_score=0.95,
        financial_stability_score=-0.85,
        crisis_language_detected=True,
        policy_reversal_language=True,
        forward_guidance_change=True,
    )
    return PolicySurpriseVector(
        event_id=weekend_emergency_event.event_id,
        rate_path_surprise=-0.85,
        financial_stability_surprise=-0.90,
        urgency_surprise=0.95,
        composite_surprise_magnitude=0.93,
        net_direction=-0.82,
        hawkish_dovish=hd,
        confidence=0.92,
        interpretation_notes="Emergency crisis easing. Maximum surprise.",
    )


@pytest.fixture
def hawkish_surprise(intraday_fomc_event):
    hd = HawkishDovishScore(
        overall_score=0.72,
        stance=PolicyStance.VERY_HAWKISH,
        confidence=0.84,
        rate_path_score=0.78,
        inflation_concern_score=0.65,
        urgency_score=0.45,
        crisis_language_detected=False,
        policy_reversal_language=False,
        forward_guidance_change=True,
    )
    return PolicySurpriseVector(
        event_id=intraday_fomc_event.event_id,
        rate_path_surprise=0.68,
        inflation_outlook_surprise=0.52,
        forward_guidance_surprise=0.40,
        urgency_surprise=0.45,
        composite_surprise_magnitude=0.68,
        net_direction=0.60,
        hawkish_dovish=hd,
        confidence=0.84,
        interpretation_notes="Significant hawkish surprise. Higher for longer signal.",
    )


@pytest.fixture
def benign_surprise(intraday_fomc_event):
    hd = HawkishDovishScore(
        overall_score=0.05,
        stance=PolicyStance.NEUTRAL,
        confidence=0.65,
        crisis_language_detected=False,
        policy_reversal_language=False,
        forward_guidance_change=False,
    )
    return PolicySurpriseVector(
        event_id=intraday_fomc_event.event_id,
        composite_surprise_magnitude=0.08,
        net_direction=0.04,
        hawkish_dovish=hd,
        confidence=0.65,
        interpretation_notes="In-line communication. No material surprise.",
    )
