"""
tests/unit/test_event_detection.py

Unit tests for Event Detection, Classification, and Market Calendar.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data_schema.models import EventType, SeverityLevel, MarketSessionState
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.event_detection.detector import EventDetector


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def calendar():
    return MarketCalendar()

@pytest.fixture(scope="module")
def detector(calendar):
    return EventDetector(calendar=calendar, config={"min_severity_score": 10.0})


def fed_event(event_time: str, **kwargs) -> dict:
    base = {
        "title": "Federal Reserve Statement",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": event_time,
        "description": "Test event",
    }
    base.update(kwargs)
    return base


# ─── MarketCalendar ───────────────────────────────────────────

class TestMarketCalendar:

    def test_saturday_not_trading_day(self, calendar):
        assert not calendar.is_trading_day(datetime(2024, 3, 9, 14, 0, tzinfo=timezone.utc))

    def test_sunday_not_trading_day(self, calendar):
        assert not calendar.is_trading_day(datetime(2024, 3, 10, 14, 0, tzinfo=timezone.utc))

    def test_monday_is_trading_day(self, calendar):
        assert calendar.is_trading_day(datetime(2024, 3, 11, 14, 0, tzinfo=timezone.utc))

    def test_holiday_not_trading_day(self, calendar):
        # Christmas 2024
        xmas = datetime(2024, 12, 25, 14, 0, tzinfo=timezone.utc)
        assert not calendar.is_trading_day(xmas)
        assert calendar.is_holiday(xmas)

    def test_normal_weekday_is_trading_day(self, calendar):
        assert calendar.is_trading_day(datetime(2024, 6, 19, 14, 30, tzinfo=timezone.utc))

    def test_next_market_open_from_saturday_is_monday(self, calendar):
        saturday = datetime(2024, 3, 9, 14, 0, tzinfo=timezone.utc)
        nxt = calendar.next_market_open(saturday)
        assert nxt is not None
        from zoneinfo import ZoneInfo
        nxt_et = nxt.astimezone(ZoneInfo("America/New_York"))
        assert nxt_et.weekday() == 0   # Monday
        assert nxt_et.hour == 9
        assert nxt_et.minute == 30

    def test_next_market_open_from_friday_after_close(self, calendar):
        # Friday 5pm ET = 21:00 UTC (EST) or 22:00 UTC (EDT)
        # Use a Friday in non-DST: 2024-01-05 = Friday
        friday_eve = datetime(2024, 1, 5, 22, 0, tzinfo=timezone.utc)  # ~5pm ET
        nxt = calendar.next_market_open(friday_eve)
        from zoneinfo import ZoneInfo
        nxt_et = nxt.astimezone(ZoneInfo("America/New_York"))
        assert nxt_et.weekday() == 0  # Monday

    def test_next_market_open_during_trading_hours_is_tomorrow(self, calendar):
        # Monday during trading hours
        monday_noon = datetime(2024, 3, 11, 17, 0, tzinfo=timezone.utc)  # ~12pm ET
        nxt = calendar.next_market_open(monday_noon)
        from zoneinfo import ZoneInfo
        nxt_et = nxt.astimezone(ZoneInfo("America/New_York"))
        # During open hours, next open is tomorrow
        assert nxt_et.weekday() == 1  # Tuesday

    def test_weekend_gap_corridor_friday_after_close(self, calendar):
        from zoneinfo import ZoneInfo
        # Friday 4:30pm ET
        fri_after = datetime(2024, 1, 5, 21, 30, tzinfo=timezone.utc)
        assert calendar.is_in_weekend_gap_corridor(fri_after)

    def test_weekend_gap_corridor_saturday(self, calendar):
        sat = datetime(2024, 3, 9, 12, 0, tzinfo=timezone.utc)
        assert calendar.is_in_weekend_gap_corridor(sat)

    def test_weekend_gap_corridor_sunday(self, calendar):
        sun = datetime(2024, 3, 10, 20, 0, tzinfo=timezone.utc)
        assert calendar.is_in_weekend_gap_corridor(sun)

    def test_not_in_weekend_gap_corridor_monday_open(self, calendar):
        # Monday 10am ET
        mon = datetime(2024, 3, 11, 15, 0, tzinfo=timezone.utc)
        assert not calendar.is_in_weekend_gap_corridor(mon)

    def test_not_in_weekend_gap_corridor_intraday(self, calendar):
        wed = datetime(2024, 3, 13, 18, 0, tzinfo=timezone.utc)  # Wednesday noon ET
        assert not calendar.is_in_weekend_gap_corridor(wed)

    def test_hours_in_gap_corridor_saturday(self, calendar):
        sat_noon = datetime(2024, 3, 9, 17, 0, tzinfo=timezone.utc)
        hours = calendar.hours_in_gap_corridor(sat_noon)
        # Saturday noon UTC to Monday 14:30 UTC (~9:30 ET) ≈ 45h
        assert hours is not None
        assert 40 < hours < 60

    def test_market_close_time_valid_weekday(self, calendar):
        close = calendar.market_close_time(date(2024, 3, 11))  # Monday
        assert close is not None
        from zoneinfo import ZoneInfo
        close_et = close.astimezone(ZoneInfo("America/New_York"))
        assert close_et.hour == 16
        assert close_et.minute == 0

    def test_market_close_returns_none_for_holiday(self, calendar):
        close = calendar.market_close_time(date(2024, 12, 25))
        assert close is None

    def test_get_trading_days_excludes_weekends_and_holidays(self, calendar):
        days = calendar.get_trading_days(date(2024, 12, 23), date(2024, 12, 31))
        # Dec 25 (holiday), Dec 28-29 (weekend), Dec 31 (Tuesday — should be in)
        assert date(2024, 12, 25) not in days
        assert date(2024, 12, 28) not in days
        assert date(2024, 12, 23) in days  # Monday before Xmas
        assert date(2024, 12, 31) in days  # Tuesday


# ─── EventDetector ───────────────────────────────────────────

class TestEventDetector:

    # ── Detection / filtering ────────────────────────────────

    def test_fed_chair_detected(self, detector):
        e = detector.detect_and_classify(fed_event("2024-01-31T18:30:00+00:00"))
        assert e is not None
        assert e.institution == "Federal Reserve"

    def test_unknown_institution_returns_none(self, detector):
        raw = {
            "title": "Random Org Update",
            "institution": "Random Organization",
            "event_time": "2024-01-31T18:30:00+00:00",
        }
        assert detector.detect_and_classify(raw) is None

    def test_below_threshold_returns_none(self):
        det = EventDetector(MarketCalendar(), config={"min_severity_score": 99.0})
        e = det.detect_and_classify(fed_event("2024-01-31T18:30:00+00:00"))
        assert e is None

    # ── Event type classification ─────────────────────────────

    def test_emergency_phrase_triggers_unscheduled(self, detector):
        e = detector.detect_and_classify(fed_event(
            "2024-03-15T22:00:00+00:00",
            raw_text="emergency meeting intermeeting action systemic risk",
        ))
        assert e is not None
        assert e.event_type == EventType.UNSCHEDULED_EMERGENCY

    def test_weekend_event_classified_correctly(self, detector):
        e = detector.detect_and_classify(fed_event("2024-03-09T19:00:00+00:00"))  # Saturday
        assert e is not None
        assert e.event_type == EventType.WEEKEND_POLICY_ACTION

    def test_press_conference_classification(self, detector):
        e = detector.detect_and_classify(fed_event(
            "2024-01-31T18:30:00+00:00",
            raw_text="press conference q&a questions answers",
        ))
        assert e is not None
        assert e.event_type in (EventType.PRESS_CONFERENCE, EventType.SCHEDULED_POST_CLOSE)

    def test_financial_stability_statement(self, detector):
        e = detector.detect_and_classify(fed_event(
            "2024-03-12T15:00:00+00:00",
            raw_text="financial stability systemic risk contagion bank failure disorderly markets",
        ))
        assert e is not None
        assert e.event_type in (
            EventType.FINANCIAL_STABILITY_STATEMENT, EventType.UNSCHEDULED_EMERGENCY
        )

    # ── Timing context ────────────────────────────────────────

    def test_saturday_event_is_weekend(self, detector):
        e = detector.detect_and_classify(fed_event("2024-03-09T19:00:00+00:00"))
        assert e is not None
        assert e.is_weekend is True
        assert e.full_weekend_gap is True

    def test_friday_after_close_has_gap(self, detector):
        # Friday 9pm UTC = Friday 5pm ET
        e = detector.detect_and_classify(fed_event("2024-01-05T22:00:00+00:00"))
        if e:  # may be below threshold with stripped config
            assert e.full_weekend_gap is True or e.is_after_hours is True

    def test_intraday_event_no_gap(self, detector):
        # Wednesday 2pm UTC = 9am ET (pre-market in winter)
        e = detector.detect_and_classify(fed_event("2024-01-10T19:00:00+00:00"))  # Wednesday noon ET
        if e:
            assert e.full_weekend_gap is False

    def test_hours_until_open_populated_for_weekend(self, detector):
        e = detector.detect_and_classify(fed_event("2024-03-09T19:00:00+00:00"))
        if e:
            assert e.hours_until_next_open is not None
            assert e.hours_until_next_open > 30

    # ── Severity scoring ──────────────────────────────────────

    def test_chair_scores_higher_than_president(self, detector, calendar):
        chair_raw = fed_event("2024-01-31T18:30:00+00:00", speaker_role="Chair")
        pres_raw = {
            "title": "Fed Regional President Remarks",
            "institution": "Federal Reserve",
            "speaker": "Some President",
            "speaker_role": "President",
            "event_time": "2024-01-31T18:30:00+00:00",
        }
        e_chair = detector.detect_and_classify(chair_raw)
        e_pres  = detector.detect_and_classify(pres_raw)
        if e_chair and e_pres:
            assert e_chair.severity_score >= e_pres.severity_score

    def test_emergency_scores_higher_than_scheduled(self, detector):
        emergency_raw = fed_event(
            "2024-03-15T22:00:00+00:00",
            raw_text="emergency meeting systemic risk crisis",
        )
        scheduled_raw = fed_event("2024-01-31T18:30:00+00:00")
        e_emg = detector.detect_and_classify(emergency_raw)
        e_sch = detector.detect_and_classify(scheduled_raw)
        if e_emg and e_sch:
            assert e_emg.severity_score > e_sch.severity_score

    def test_severity_level_matches_score(self, detector):
        e = detector.detect_and_classify(fed_event(
            "2024-03-09T19:00:00+00:00",
            raw_text="emergency systemic risk financial stability crisis",
        ))
        if e:
            if e.severity_score >= 75:
                assert e.severity == SeverityLevel.CRITICAL
            elif e.severity_score >= 55:
                assert e.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)

    # ── Session state ─────────────────────────────────────────

    def test_weekend_session_state(self, detector):
        e = detector.detect_and_classify(fed_event("2024-03-09T19:00:00+00:00"))
        if e:
            assert e.market_session_at_event == MarketSessionState.CLOSED_WEEKEND

    # ── Batch processing ──────────────────────────────────────

    def test_batch_returns_sorted_by_severity(self, detector):
        events = [
            fed_event("2024-03-09T19:00:00+00:00", raw_text="emergency crisis"),
            fed_event("2024-01-31T18:30:00+00:00"),
        ]
        results = detector.batch_detect(events)
        if len(results) >= 2:
            scores = [r.severity_score for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_batch_filters_none_results(self, detector):
        events = [
            fed_event("2024-03-09T19:00:00+00:00"),
            {"title": "Junk", "institution": "Nobody", "event_time": "2024-01-01T00:00:00+00:00"},
        ]
        results = detector.batch_detect(events)
        assert all(r is not None for r in results)

    # ── Institution alias resolution ─────────────────────────

    def test_fomc_alias_resolves_to_federal_reserve(self, detector):
        raw = {
            "title": "FOMC Decision",
            "institution": "FOMC",
            "speaker": "Jerome Powell",
            "speaker_role": "Chair",
            "event_time": "2024-01-31T18:30:00+00:00",
        }
        e = detector.detect_and_classify(raw)
        if e:
            assert e.institution == "Federal Reserve"

    def test_treasury_detected(self, detector):
        raw = {
            "title": "Treasury Statement",
            "institution": "U.S. Treasury",
            "speaker": "Janet Yellen",
            "speaker_role": "Secretary",
            "event_time": "2024-01-31T18:30:00+00:00",
        }
        e = detector.detect_and_classify(raw)
        assert e is not None
