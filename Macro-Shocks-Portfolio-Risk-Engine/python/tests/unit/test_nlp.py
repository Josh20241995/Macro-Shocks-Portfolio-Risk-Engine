"""
tests/unit/test_nlp.py

Unit tests for the NLP / Language Intelligence modules:
  - LexiconScorer
  - PolicyLanguageIntelligence (ensemble)
  - PolicySurpriseEngine
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data_schema.models import (
    EventType, MacroEvent, MarketSessionState, PolicyStance, SeverityLevel,
)
from macro_shock.nlp.hawkish_dovish import LexiconScorer, PolicyLanguageIntelligence
from macro_shock.nlp.policy_surprise_vector import PolicySurpriseEngine


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def scorer():
    return LexiconScorer()

@pytest.fixture
def intelligence():
    return PolicyLanguageIntelligence(use_transformer=False)

@pytest.fixture
def surprise_engine():
    return PolicySurpriseEngine()

@pytest.fixture
def fomc_event():
    return MacroEvent(
        detected_at=datetime(2024, 1, 31, 18, 30, tzinfo=timezone.utc),
        event_timestamp=datetime(2024, 1, 31, 18, 30, tzinfo=timezone.utc),
        event_type=EventType.PRESS_CONFERENCE,
        severity=SeverityLevel.HIGH,
        severity_score=60.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="FOMC Press Conference",
        is_weekend=False,
        full_weekend_gap=False,
        market_session_at_event=MarketSessionState.OPEN,
    )

@pytest.fixture
def weekend_event():
    return MacroEvent(
        detected_at=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        event_timestamp=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        event_type=EventType.UNSCHEDULED_EMERGENCY,
        severity=SeverityLevel.CRITICAL,
        severity_score=91.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="Emergency Statement",
        is_weekend=True,
        full_weekend_gap=True,
        hours_until_next_open=53.0,
        market_session_at_event=MarketSessionState.CLOSED_WEEKEND,
    )


# ─── LexiconScorer ───────────────────────────────────────────

class TestLexiconScorer:

    HAWKISH_TEXT = (
        "We will raise rates further if necessary. Inflation remains too high and "
        "above our 2 percent target. Sufficiently restrictive policy must be maintained. "
        "We have more work to do. Higher for longer is our stance."
    )

    DOVISH_TEXT = (
        "We are ready to cut rates aggressively to support the economy. "
        "Emergency measures are warranted given severe deterioration. "
        "We will do whatever it takes. Emergency rate cut is being considered. "
        "Financial stability concerns are paramount."
    )

    NEUTRAL_TEXT = (
        "The committee remains data dependent. We will monitor incoming information "
        "and act as appropriate. The path forward is uncertain."
    )

    CRISIS_TEXT = (
        "Systemic risk is present. Financial stability is at risk. "
        "Contagion is a real concern. Disorderly markets require urgent action. "
        "Emergency liquidity facilities are activated."
    )

    def test_hawkish_text_positive_score(self, scorer):
        r = scorer.score(self.HAWKISH_TEXT)
        assert r.overall_score > 0.2, f"Expected hawkish > 0.2, got {r.overall_score}"

    def test_hawkish_text_correct_stance(self, scorer):
        r = scorer.score(self.HAWKISH_TEXT)
        assert r.stance in (PolicyStance.HAWKISH, PolicyStance.VERY_HAWKISH)

    def test_dovish_text_negative_score(self, scorer):
        r = scorer.score(self.DOVISH_TEXT)
        assert r.overall_score < -0.2, f"Expected dovish < -0.2, got {r.overall_score}"

    def test_dovish_text_correct_stance(self, scorer):
        r = scorer.score(self.DOVISH_TEXT)
        assert r.stance in (PolicyStance.DOVISH, PolicyStance.VERY_DOVISH, PolicyStance.CRISIS_EASING)

    def test_neutral_text_near_zero(self, scorer):
        r = scorer.score(self.NEUTRAL_TEXT)
        assert -0.40 <= r.overall_score <= 0.40, f"Expected neutral ±0.4, got {r.overall_score}"

    def test_empty_text_zero_confidence(self, scorer):
        r = scorer.score("")
        assert r.overall_score == 0.0
        assert r.confidence == 0.0

    def test_whitespace_text_zero_confidence(self, scorer):
        r = scorer.score("   \n\t   ")
        assert r.overall_score == 0.0

    def test_crisis_language_flag(self, scorer):
        r = scorer.score(self.CRISIS_TEXT)
        assert r.crisis_language_detected is True

    def test_policy_reversal_detected(self, scorer):
        text = "We are reversing course and reconsider our guidance. Fundamentally different."
        r = scorer.score(text)
        assert r.policy_reversal_language is True

    def test_forward_guidance_change_detected(self, scorer):
        text = "We are no longer committed to previous guidance. Conditional on new data."
        r = scorer.score(text)
        assert r.forward_guidance_change is True

    def test_score_strictly_bounded(self, scorer):
        for text in [self.HAWKISH_TEXT * 10, self.DOVISH_TEXT * 10, self.CRISIS_TEXT * 10]:
            r = scorer.score(text)
            assert -1.0 <= r.overall_score <= 1.0

    def test_confidence_bounded(self, scorer):
        r = scorer.score(self.HAWKISH_TEXT)
        assert 0.0 <= r.confidence <= 1.0

    def test_hawkish_phrases_populated(self, scorer):
        r = scorer.score(self.HAWKISH_TEXT)
        assert len(r.hawkish_phrases) > 0

    def test_dovish_phrases_populated(self, scorer):
        r = scorer.score(self.DOVISH_TEXT)
        assert len(r.dovish_phrases) > 0

    def test_urgency_score_elevated_for_urgent_text(self, scorer):
        text = "We must act quickly. Immediate action required. Act now without delay."
        r = scorer.score(text)
        assert r.urgency_score > 0.3

    def test_rate_path_component_hawkish(self, scorer):
        text = "rate hike raise rates higher for longer additional increases"
        r = scorer.score(text)
        assert r.rate_path_score > 0.0

    def test_rate_path_component_dovish(self, scorer):
        text = "rate cut lower rates pause rate hikes emergency rate cut"
        r = scorer.score(text)
        assert r.rate_path_score < 0.0

    def test_diminishing_returns_for_repetition(self, scorer):
        single = scorer.score("raise rates")
        repeated = scorer.score("raise rates " * 20)
        # Repeated should score higher but not 20x higher
        assert repeated.overall_score > single.overall_score
        assert repeated.overall_score < single.overall_score * 5

    def test_method_label_lexicon(self, scorer):
        r = scorer.score("inflation is too high")
        assert r.method == "lexicon"


# ─── PolicyLanguageIntelligence ──────────────────────────────

class TestPolicyLanguageIntelligence:

    def test_analyze_returns_hd_score(self, intelligence):
        r = intelligence.analyze("We will raise rates further if necessary.")
        assert r.overall_score is not None

    def test_analyze_sections_weights_headline_higher(self, intelligence):
        """Headline should carry more weight than QA."""
        r = intelligence.analyze_sections(
            headline_summary="EMERGENCY RATE CUT — Fed slashes rates to zero",
            prepared_remarks="Moderate language about data dependency.",
            qa_section="No strong signals.",
        )
        # Strong dovish headline should dominate
        assert r.overall_score < 0.0

    def test_analyze_sections_empty_returns_ambiguous(self, intelligence):
        r = intelligence.analyze_sections()
        assert r.stance == PolicyStance.AMBIGUOUS or r.confidence < 0.2

    def test_ensemble_method_when_no_transformer(self, intelligence):
        """With use_transformer=False, method should be 'lexicon'."""
        r = intelligence.analyze("Sufficiently restrictive policy")
        assert r.method == "lexicon"

    def test_crisis_escalates_to_crisis_easing_stance(self, intelligence):
        r = intelligence.analyze(
            "Emergency rate cut. Financial stability. Systemic risk. Crisis easing."
        )
        assert r.crisis_language_detected is True
        assert r.stance in (PolicyStance.CRISIS_EASING, PolicyStance.VERY_DOVISH, PolicyStance.DOVISH)


# ─── PolicySurpriseEngine ────────────────────────────────────

class TestPolicySurpriseEngine:

    def test_crisis_event_high_magnitude(self, surprise_engine, weekend_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score(
            "Emergency crisis measures. Systemic risk. Financial stability. "
            "We will do whatever it takes. Emergency rate cut now."
        )
        vec = surprise_engine.generate(event=weekend_event, hawkish_dovish=hd)
        assert vec.composite_surprise_magnitude > 0.3

    def test_benign_event_low_magnitude(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("We remain data dependent and will monitor carefully.")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert vec.composite_surprise_magnitude < 0.6

    def test_weekend_event_amplifies_magnitude(self, surprise_engine, weekend_event, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        same_text = "Emergency measures taken. Financial stability concerns."
        hd = scorer.score(same_text)

        vec_weekend = surprise_engine.generate(event=weekend_event, hawkish_dovish=hd)
        vec_intraday = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)

        assert vec_weekend.composite_surprise_magnitude >= vec_intraday.composite_surprise_magnitude

    def test_hawkish_text_positive_net_direction(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score(
            "We will raise rates. Sufficiently restrictive. Higher for longer. "
            "Inflation too high. More work to do."
        )
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert vec.net_direction > 0.0

    def test_dovish_text_negative_net_direction(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("Cut rates. Lower rates. Emergency easing. Whatever it takes.")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert vec.net_direction < 0.0

    def test_urgency_surprise_bounded(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("Act urgently. Immediately. No time to waste. Act now.")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert 0.0 <= vec.urgency_surprise <= 1.0

    def test_all_dimensions_bounded(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("We will raise rates if necessary.")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)

        for dim in [
            vec.rate_path_surprise, vec.inflation_outlook_surprise,
            vec.growth_outlook_surprise, vec.balance_sheet_surprise,
            vec.financial_stability_surprise, vec.forward_guidance_surprise,
        ]:
            assert -1.0 <= dim <= 1.0

    def test_event_id_propagated(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("Test text")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert vec.event_id == fomc_event.event_id

    def test_interpretation_notes_populated(self, surprise_engine, fomc_event):
        from macro_shock.nlp.hawkish_dovish import LexiconScorer
        scorer = LexiconScorer()
        hd = scorer.score("Inflation is too high. We will raise rates.")
        vec = surprise_engine.generate(event=fomc_event, hawkish_dovish=hd)
        assert len(vec.interpretation_notes) > 20
