"""
tests/unit/test_risk_scoring.py

Unit tests for the core risk scoring modules.
Tests are isolated — no live data feeds, no external calls.
All market states use synthetic data.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.data_schema.models import (
    EventType,
    MacroEvent,
    MarketSessionState,
    PolicySurpriseVector,
    RegimeType,
    SeverityLevel,
    HawkishDovishScore,
    PolicyStance,
)
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.event_detection.detector import EventDetector
from macro_shock.market_context.vulnerability_scorer import MarketVulnerabilityScorer
from macro_shock.nlp.hawkish_dovish import LexiconScorer, PolicyLanguageIntelligence
from macro_shock.risk_scoring.composite_scorer import CompositeRiskScorer
from macro_shock.scenario_engine.scenario_tree import ScenarioTreeBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calendar():
    return MarketCalendar()

@pytest.fixture
def detector(calendar):
    return EventDetector(calendar=calendar)

@pytest.fixture
def lexicon_scorer():
    return LexiconScorer()

@pytest.fixture
def risk_scorer():
    return CompositeRiskScorer()

@pytest.fixture
def scenario_builder():
    return ScenarioTreeBuilder()

@pytest.fixture
def vulnerability_scorer():
    return MarketVulnerabilityScorer()

@pytest.fixture
def normal_market_state(calendar):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 3, 20, 15, 0, tzinfo=timezone.utc),
        calendar=calendar,
        stress_level=0.2,
        seed=42,
    )

@pytest.fixture
def stressed_market_state(calendar):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 3, 20, 15, 0, tzinfo=timezone.utc),
        calendar=calendar,
        stress_level=0.75,
        seed=42,
    )

@pytest.fixture
def weekend_event():
    return MacroEvent(
        detected_at=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        event_timestamp=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        event_type=EventType.WEEKEND_POLICY_ACTION,
        severity=SeverityLevel.CRITICAL,
        severity_score=88.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="Emergency Weekend Statement",
        is_weekend=True,
        is_after_hours=True,
        full_weekend_gap=True,
        market_session_at_event=MarketSessionState.CLOSED_WEEKEND,
        hours_until_next_open=55.0,
        minutes_since_close=1740.0,
    )

@pytest.fixture
def hawkish_surprise_vector(weekend_event):
    hd = HawkishDovishScore(
        overall_score=0.75,
        stance=PolicyStance.VERY_HAWKISH,
        confidence=0.85,
        rate_path_score=0.80,
        inflation_concern_score=0.70,
        urgency_score=0.6,
        crisis_language_detected=False,
        policy_reversal_language=False,
        forward_guidance_change=True,
    )
    return PolicySurpriseVector(
        event_id=weekend_event.event_id,
        rate_path_surprise=0.65,
        inflation_outlook_surprise=0.55,
        growth_outlook_surprise=0.10,
        balance_sheet_surprise=0.40,
        financial_stability_surprise=-0.05,
        forward_guidance_surprise=0.45,
        urgency_surprise=0.60,
        composite_surprise_magnitude=0.70,
        net_direction=0.60,
        hawkish_dovish=hd,
        confidence=0.85,
    )

@pytest.fixture
def crisis_surprise_vector(weekend_event):
    hd = HawkishDovishScore(
        overall_score=-0.85,
        stance=PolicyStance.CRISIS_EASING,
        confidence=0.90,
        rate_path_score=-0.90,
        urgency_score=0.95,
        financial_stability_score=-0.80,
        crisis_language_detected=True,
        policy_reversal_language=True,
        forward_guidance_change=True,
    )
    return PolicySurpriseVector(
        event_id=weekend_event.event_id,
        rate_path_surprise=-0.85,
        inflation_outlook_surprise=-0.30,
        financial_stability_surprise=-0.90,
        urgency_surprise=0.95,
        composite_surprise_magnitude=0.92,
        net_direction=-0.80,
        hawkish_dovish=hd,
        confidence=0.90,
    )


# ---------------------------------------------------------------------------
# Event Detection Tests
# ---------------------------------------------------------------------------

class TestEventDetector:
    def test_detects_fed_press_conference(self, detector):
        raw = {
            "title": "FOMC Press Conference",
            "institution": "Federal Reserve",
            "speaker": "Jerome Powell",
            "speaker_role": "Chair",
            "event_time": "2024-01-31T18:30:00+00:00",
            "description": "Post-FOMC press conference",
        }
        event = detector.detect_and_classify(raw)
        assert event is not None
        assert event.institution == "Federal Reserve"
        assert event.severity_score > 0

    def test_detects_weekend_event(self, detector):
        raw = {
            "title": "Emergency Federal Reserve Statement",
            "institution": "Federal Reserve",
            "speaker": "Jerome Powell",
            "speaker_role": "Chair",
            "event_time": "2024-03-09T19:00:00+00:00",  # Saturday
            "description": "Emergency weekend statement",
        }
        event = detector.detect_and_classify(raw)
        assert event is not None
        assert event.is_weekend is True
        assert event.full_weekend_gap is True

    def test_emergency_language_triggers_high_severity(self, detector):
        raw = {
            "title": "Emergency Intermeeting Rate Cut",
            "institution": "Federal Reserve",
            "speaker": "Jerome Powell",
            "speaker_role": "Chair",
            "event_time": "2024-03-15T22:00:00+00:00",
            "description": "Emergency meeting. Systemic risk concerns. Market stabilization.",
            "raw_text": "emergency meeting emergency rate cut systemic risk financial stability",
        }
        event = detector.detect_and_classify(raw)
        assert event is not None
        assert event.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
        assert event.event_type == EventType.UNSCHEDULED_EMERGENCY

    def test_unknown_institution_skipped(self, detector):
        raw = {
            "title": "Some Random Statement",
            "institution": "Random Organization",
            "event_time": "2024-01-15T18:00:00+00:00",
        }
        event = detector.detect_and_classify(raw)
        assert event is None

    def test_friday_after_close_has_weekend_gap(self, detector):
        raw = {
            "title": "Fed Chair Remarks Friday Evening",
            "institution": "Federal Reserve",
            "speaker": "Jerome Powell",
            "speaker_role": "Chair",
            "event_time": "2024-11-01T21:00:00+00:00",  # Friday 9pm UTC = 5pm ET
            "description": "Friday post-market remarks",
        }
        event = detector.detect_and_classify(raw)
        if event:  # May be below threshold depending on config
            assert event.full_weekend_gap is True


# ---------------------------------------------------------------------------
# NLP Tests
# ---------------------------------------------------------------------------

class TestLexiconScorer:
    def test_hawkish_text_scores_positive(self, lexicon_scorer):
        text = "We will raise rates as many times as necessary. Inflation is too high and persistent. Sufficiently restrictive policy must be maintained. Higher for longer."
        result = lexicon_scorer.score(text)
        assert result.overall_score > 0.2, f"Expected hawkish score, got {result.overall_score}"
        assert result.stance in (PolicyStance.HAWKISH, PolicyStance.VERY_HAWKISH)

    def test_dovish_text_scores_negative(self, lexicon_scorer):
        text = "We are ready to cut rates aggressively to support the economy. Emergency measures are warranted. We will do whatever it takes. Crisis easing now."
        result = lexicon_scorer.score(text)
        assert result.overall_score < -0.2, f"Expected dovish score, got {result.overall_score}"
        assert result.stance in (PolicyStance.DOVISH, PolicyStance.VERY_DOVISH, PolicyStance.CRISIS_EASING)

    def test_neutral_text_scores_near_zero(self, lexicon_scorer):
        text = "The economy is growing at a moderate pace. We remain data dependent and will observe incoming information carefully."
        result = lexicon_scorer.score(text)
        assert -0.35 <= result.overall_score <= 0.35

    def test_crisis_language_detected(self, lexicon_scorer):
        text = "systemic risk financial stability contagion bank failure disorderly markets liquidity crisis"
        result = lexicon_scorer.score(text)
        assert result.crisis_language_detected is True

    def test_empty_text_returns_zero(self, lexicon_scorer):
        result = lexicon_scorer.score("")
        assert result.overall_score == 0.0
        assert result.confidence == 0.0

    def test_policy_reversal_detected(self, lexicon_scorer):
        text = "We are reversing course and will reconsider our previous guidance. This is a fundamentally different assessment."
        result = lexicon_scorer.score(text)
        assert result.policy_reversal_language is True

    def test_score_is_bounded(self, lexicon_scorer):
        extreme_hawkish = " ".join(["raise rates hike rates inflation too high sufficiently restrictive"] * 20)
        result = lexicon_scorer.score(extreme_hawkish)
        assert -1.0 <= result.overall_score <= 1.0


# ---------------------------------------------------------------------------
# Market Vulnerability Tests
# ---------------------------------------------------------------------------

class TestMarketVulnerabilityScorer:
    def test_normal_market_low_vulnerability(self, vulnerability_scorer, normal_market_state):
        vuln = vulnerability_scorer.score(normal_market_state)
        assert vuln.composite < 0.60, f"Normal market should have low vulnerability, got {vuln.composite}"
        assert vuln.regime in (RegimeType.RISK_ON_EXPANSION, RegimeType.FRAGILE_RISK_ON)

    def test_stressed_market_high_vulnerability(self, vulnerability_scorer, stressed_market_state):
        vuln = vulnerability_scorer.score(stressed_market_state)
        assert vuln.composite > 0.50, f"Stressed market should have high vulnerability, got {vuln.composite}"
        assert vuln.regime in (RegimeType.RISK_OFF_CORRECTION, RegimeType.CRISIS)

    def test_amplification_factor_range(self, vulnerability_scorer, normal_market_state, stressed_market_state):
        normal_vuln = vulnerability_scorer.score(normal_market_state)
        stressed_vuln = vulnerability_scorer.score(stressed_market_state)
        assert 1.0 <= normal_vuln.amplification_factor <= 2.0
        assert stressed_vuln.amplification_factor > normal_vuln.amplification_factor

    def test_crisis_market_classified_correctly(self, vulnerability_scorer, calendar):
        crisis_state = MarketStateBuilder.build_synthetic(
            as_of=datetime(2024, 3, 20, 15, 0, tzinfo=timezone.utc),
            calendar=calendar,
            stress_level=0.95,
            seed=99,
        )
        vuln = vulnerability_scorer.score(crisis_state)
        assert vuln.regime in (RegimeType.CRISIS, RegimeType.RISK_OFF_CORRECTION)


# ---------------------------------------------------------------------------
# Scenario Tree Tests
# ---------------------------------------------------------------------------

class TestScenarioTreeBuilder:
    def test_probabilities_sum_to_one(
        self, scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer
    ):
        vuln = vulnerability_scorer.score(normal_market_state)
        tree = scenario_builder.build(weekend_event, hawkish_surprise_vector, vuln)
        total_prob = sum(s.probability for s in tree.scenarios)
        assert abs(total_prob - 1.0) < 0.01, f"Probabilities sum to {total_prob}"

    def test_crisis_scenario_has_higher_tail_probability(
        self, scenario_builder, weekend_event, crisis_surprise_vector, stressed_market_state, vulnerability_scorer
    ):
        vuln = vulnerability_scorer.score(stressed_market_state)
        tree = scenario_builder.build(weekend_event, crisis_surprise_vector, vuln)
        tail_prob = sum(s.probability for s in tree.scenarios if s.is_tail_scenario)
        assert tail_prob > 0.10, f"Expected high tail probability in crisis, got {tail_prob}"

    def test_monday_gap_estimate_present_for_weekend_event(
        self, scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer
    ):
        vuln = vulnerability_scorer.score(normal_market_state)
        tree = scenario_builder.build(weekend_event, hawkish_surprise_vector, vuln)
        assert tree.monday_gap_estimate_pct is not None

    def test_n_scenarios_is_correct(
        self, scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer
    ):
        vuln = vulnerability_scorer.score(normal_market_state)
        tree = scenario_builder.build(weekend_event, hawkish_surprise_vector, vuln)
        # Should have all 8 defined scenarios
        assert len(tree.scenarios) == 8


# ---------------------------------------------------------------------------
# Risk Scoring Tests
# ---------------------------------------------------------------------------

class TestCompositeRiskScorer:
    def _build_tree(self, scenario_builder, event, surprise, market_state, vulnerability_scorer):
        vuln = vulnerability_scorer.score(market_state)
        tree = scenario_builder.build(event, surprise, vuln)
        return tree, vuln

    def test_score_in_valid_range(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, hawkish_surprise_vector, normal_market_state
    ):
        tree, vuln = self._build_tree(scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer)
        score = risk_scorer.score(weekend_event, hawkish_surprise_vector, normal_market_state, vuln, tree)
        assert 0.0 <= score.composite_score <= 100.0

    def test_crisis_event_scores_higher_than_benign(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, hawkish_surprise_vector, crisis_surprise_vector,
        normal_market_state, stressed_market_state
    ):
        tree_h, vuln_n = self._build_tree(scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer)
        tree_c, vuln_s = self._build_tree(scenario_builder, weekend_event, crisis_surprise_vector, stressed_market_state, vulnerability_scorer)

        score_hawkish = risk_scorer.score(weekend_event, hawkish_surprise_vector, normal_market_state, vuln_n, tree_h)
        score_crisis = risk_scorer.score(weekend_event, crisis_surprise_vector, stressed_market_state, vuln_s, tree_c)

        assert score_crisis.composite_score > score_hawkish.composite_score

    def test_sub_scores_are_present(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, hawkish_surprise_vector, normal_market_state
    ):
        tree, vuln = self._build_tree(scenario_builder, weekend_event, hawkish_surprise_vector, normal_market_state, vulnerability_scorer)
        score = risk_scorer.score(weekend_event, hawkish_surprise_vector, normal_market_state, vuln, tree)
        sub_scores = [
            score.liquidity_risk, score.volatility_risk, score.rate_shock_risk,
            score.equity_downside_risk, score.credit_spread_risk, score.fx_risk,
            score.commodity_shock_risk, score.weekend_gap_risk, score.policy_ambiguity_risk,
        ]
        for ss in sub_scores:
            assert 0.0 <= ss.score <= 100.0
            assert ss.weight > 0.0
            assert ss.name  # Non-empty name

    def test_weekend_gap_risk_elevated_for_weekend_event(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, hawkish_surprise_vector, normal_market_state, calendar
    ):
        # Create an intraday event version
        intraday_event = MacroEvent(
            detected_at=datetime(2024, 1, 31, 18, 0, tzinfo=timezone.utc),
            event_timestamp=datetime(2024, 1, 31, 18, 30, tzinfo=timezone.utc),
            event_type=EventType.PRESS_CONFERENCE,
            severity=SeverityLevel.MEDIUM,
            severity_score=50.0,
            institution="Federal Reserve",
            speaker="Jerome Powell",
            speaker_role="Chair",
            title="FOMC Press Conference",
            is_weekend=False,
            is_after_hours=False,
            full_weekend_gap=False,
            market_session_at_event=MarketSessionState.OPEN,
        )

        vuln = vulnerability_scorer.score(normal_market_state)
        tree_w = scenario_builder.build(weekend_event, hawkish_surprise_vector, vuln)
        tree_i = scenario_builder.build(intraday_event, hawkish_surprise_vector, vuln)

        score_w = risk_scorer.score(weekend_event, hawkish_surprise_vector, normal_market_state, vuln, tree_w)
        score_i = risk_scorer.score(intraday_event, hawkish_surprise_vector, normal_market_state, vuln, tree_i)

        # Weekend gap risk sub-score should be higher for weekend event
        assert score_w.weekend_gap_risk.score > score_i.weekend_gap_risk.score
        # Total score should also be higher
        assert score_w.composite_score > score_i.composite_score

    def test_severity_consistent_with_score(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, crisis_surprise_vector, stressed_market_state
    ):
        vuln = vulnerability_scorer.score(stressed_market_state)
        tree = scenario_builder.build(weekend_event, crisis_surprise_vector, vuln)
        score = risk_scorer.score(weekend_event, crisis_surprise_vector, stressed_market_state, vuln, tree)

        if score.composite_score >= 75:
            assert score.severity == SeverityLevel.CRITICAL
        elif score.composite_score >= 55:
            assert score.severity == SeverityLevel.HIGH

    def test_action_level_for_high_score(
        self, risk_scorer, scenario_builder, vulnerability_scorer,
        weekend_event, crisis_surprise_vector, stressed_market_state
    ):
        vuln = vulnerability_scorer.score(stressed_market_state)
        tree = scenario_builder.build(weekend_event, crisis_surprise_vector, vuln)
        score = risk_scorer.score(weekend_event, crisis_surprise_vector, stressed_market_state, vuln, tree)

        if score.composite_score >= 65:
            assert score.recommended_action_level in ("HEDGE", "EMERGENCY_DERISKING")


# ---------------------------------------------------------------------------
# Calendar Tests
# ---------------------------------------------------------------------------

class TestMarketCalendar:
    def test_saturday_is_not_trading_day(self, calendar):
        sat = datetime(2024, 3, 9, 12, 0, tzinfo=timezone.utc)
        assert calendar.is_trading_day(sat) is False

    def test_monday_is_trading_day(self, calendar):
        mon = datetime(2024, 3, 11, 14, 0, tzinfo=timezone.utc)
        assert calendar.is_trading_day(mon) is True

    def test_next_market_open_after_friday_close_is_monday(self, calendar):
        friday_evening = datetime(2024, 3, 8, 22, 0, tzinfo=timezone.utc)  # Friday 5pm ET
        next_open = calendar.next_market_open(friday_evening)
        assert next_open is not None
        from zoneinfo import ZoneInfo
        next_open_et = next_open.astimezone(ZoneInfo("America/New_York"))
        assert next_open_et.weekday() == 0  # Monday

    def test_weekend_gap_corridor_detected(self, calendar):
        friday_after_close = datetime(2024, 3, 8, 21, 30, tzinfo=timezone.utc)  # 4:30pm ET Friday
        saturday = datetime(2024, 3, 9, 14, 0, tzinfo=timezone.utc)
        sunday = datetime(2024, 3, 10, 14, 0, tzinfo=timezone.utc)
        monday_open = datetime(2024, 3, 11, 14, 30, tzinfo=timezone.utc)  # 9:30am ET Monday

        assert calendar.is_in_weekend_gap_corridor(friday_after_close) is True
        assert calendar.is_in_weekend_gap_corridor(saturday) is True
        assert calendar.is_in_weekend_gap_corridor(sunday) is True
        assert calendar.is_in_weekend_gap_corridor(monday_open) is False
