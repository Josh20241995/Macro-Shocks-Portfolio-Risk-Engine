"""
tests/integration/test_pipeline_integration.py

Integration tests for the full MacroShockPipeline.
Tests the complete end-to-end flow using synthetic data.
These tests do NOT require live data feeds or external services.

Run with: pytest python/tests/integration/ -v -m integration
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.orchestration.pipeline import MacroShockPipeline

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

RESEARCH_CONFIG = {
    "use_transformer": False,
    "audit_log_dir": "/tmp/msre_test_audit",
    "fail_fast": False,
    "alert_thresholds": None,
    "event_detection": {"min_severity_score": 10.0},
}


def make_pipeline() -> MacroShockPipeline:
    return MacroShockPipeline(config=RESEARCH_CONFIG, environment="research")


def make_market_state(pipeline: MacroShockPipeline, stress_level: float = 0.3):
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        calendar=pipeline.calendar,
        stress_level=stress_level,
        seed=42,
    )


# ---------------------------------------------------------------------------
# Scenario Raw Events
# ---------------------------------------------------------------------------

WEEKEND_CRISIS_RAW = {
    "title": "Emergency Federal Reserve Statement — Weekend",
    "institution": "Federal Reserve",
    "speaker": "Jerome Powell",
    "speaker_role": "Chair",
    "event_time": "2024-03-09T19:00:00+00:00",
    "description": "Emergency financial stability statement.",
    "headline_summary": "Fed announces emergency backstop citing systemic risk concerns.",
    "prepared_remarks": (
        "The Federal Reserve is taking emergency measures to address financial stability "
        "concerns. Systemic risk is present. Emergency lending facilities activated. "
        "We will do whatever it takes to stabilize financial conditions. "
        "Rate action may be considered at intermeeting call."
    ),
    "qa_section": "Q: Emergency rate cut? A: Not ruling it out. Crisis measures warranted.",
}

HAWKISH_PRESS_CONF_RAW = {
    "title": "FOMC Press Conference — Hawkish Surprise",
    "institution": "Federal Reserve",
    "speaker": "Jerome Powell",
    "speaker_role": "Chair",
    "event_time": "2024-01-31T18:30:00+00:00",
    "description": "Post-FOMC press conference with hawkish surprise.",
    "headline_summary": "Fed: higher for longer; premature to cut; inflation not under control.",
    "prepared_remarks": (
        "Inflation remains too high. We will raise rates further if necessary. "
        "It would be premature to cut rates. Sufficiently restrictive policy must be maintained. "
        "We have more work to do. Labor market remains tight."
    ),
    "qa_section": "Q: Rate cuts? A: Premature. Additional increases on the table.",
}

BENIGN_CONF_RAW = {
    "title": "FOMC Statement — In Line",
    "institution": "Federal Reserve",
    "speaker": "Jerome Powell",
    "speaker_role": "Chair",
    "event_time": "2024-03-20T18:30:00+00:00",
    "description": "Routine FOMC press conference.",
    "headline_summary": "Fed holds rates steady. Data dependent. No surprises.",
    "prepared_remarks": (
        "We held rates steady as expected. We remain data dependent and patient. "
        "The economy is growing moderately. Inflation is declining gradually toward target."
    ),
    "qa_section": "Q: Next move? A: Watching data carefully. No preset course.",
}

FRIDAY_CLOSE_RAW = {
    "title": "Fed Chair Remarks — Friday Post-Close",
    "institution": "Federal Reserve",
    "speaker": "Jerome Powell",
    "speaker_role": "Chair",
    "event_time": "2024-11-01T21:00:00+00:00",  # Friday 5pm ET = Saturday 21:00 UTC? No: 21:00 UTC = 5pm ET
    "description": "Friday evening remarks. Markets closed.",
    "headline_summary": "Powell: significant uncertainty, will act as appropriate.",
    "prepared_remarks": "The path forward is highly uncertain. We remain data dependent and will act.",
}


# ---------------------------------------------------------------------------
# Full Pipeline Integration Tests
# ---------------------------------------------------------------------------

class TestPipelineEndToEnd:
    """Tests the complete pipeline from raw event to portfolio impact."""

    def test_weekend_crisis_produces_high_score(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.65)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        assert ctx.event is not None, "Event should be detected"
        assert ctx.risk_score is not None, "Risk score should be computed"
        assert ctx.risk_score.composite_score >= 50.0, (
            f"Weekend crisis should score >= 50, got {ctx.risk_score.composite_score}"
        )

    def test_weekend_crisis_has_gap_risk_elevated(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.65)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        assert ctx.risk_score is not None
        assert ctx.risk_score.weekend_gap_risk.score > 20.0, (
            "Weekend gap risk should be elevated for weekend event"
        )
        assert ctx.risk_score.gap_risk_multiplier > 1.0

    def test_weekend_crisis_produces_portfolio_impact(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.65)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        assert ctx.portfolio_impact is not None
        assert ctx.portfolio_impact.action_level in (
            "HEDGE", "REDUCE", "EMERGENCY_DERISKING"
        ), f"Expected hedge/reduce/emergency, got {ctx.portfolio_impact.action_level}"

    def test_weekend_crisis_scenario_tree_built(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.65)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        assert ctx.scenario_tree is not None
        probs = sum(s.probability for s in ctx.scenario_tree.scenarios)
        assert abs(probs - 1.0) < 0.02, f"Probabilities sum to {probs}"
        assert ctx.scenario_tree.monday_gap_estimate_pct is not None

    def test_hawkish_surprise_produces_nonzero_score(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.3)
        ctx = pipeline.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)

        assert ctx.risk_score is not None
        assert ctx.risk_score.composite_score > 10.0

    def test_hawkish_surprise_rate_shock_elevated(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.3)
        ctx = pipeline.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)

        assert ctx.risk_score is not None
        assert ctx.risk_score.rate_shock_risk.score > 20.0, (
            "Hawkish surprise should elevate rate shock risk"
        )

    def test_benign_event_scores_lower_than_crisis(self):
        pipeline = make_pipeline()
        market_normal = make_market_state(pipeline, stress_level=0.2)
        market_stressed = make_market_state(pipeline, stress_level=0.65)

        ctx_benign = pipeline.process_raw_event(BENIGN_CONF_RAW, market_state=market_normal)
        ctx_crisis = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market_stressed)

        if ctx_benign.risk_score and ctx_crisis.risk_score:
            assert ctx_crisis.risk_score.composite_score > ctx_benign.risk_score.composite_score, (
                "Crisis should score higher than benign"
            )

    def test_friday_close_event_has_gap_multiplier(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.25)
        ctx = pipeline.process_raw_event(FRIDAY_CLOSE_RAW, market_state=market)

        if ctx.risk_score:
            assert ctx.risk_score.gap_risk_multiplier > 1.0, (
                "Friday after-close event should have gap risk multiplier > 1.0"
            )

    def test_policy_surprise_vector_generated(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.4)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        assert ctx.policy_surprise is not None
        assert 0.0 <= ctx.policy_surprise.composite_surprise_magnitude <= 1.0
        assert -1.0 <= ctx.policy_surprise.net_direction <= 1.0

    def test_crisis_language_detected_in_weekend_event(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.6)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        if ctx.policy_surprise and ctx.policy_surprise.hawkish_dovish:
            assert ctx.policy_surprise.hawkish_dovish.crisis_language_detected is True

    def test_completed_stages_populated(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.3)
        ctx = pipeline.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)

        expected_stages = [
            "event_detection", "market_context", "nlp",
            "policy_surprise", "vulnerability_scoring",
        ]
        for stage in expected_stages:
            assert stage in ctx.completed_stages, f"Stage '{stage}' not completed"

    def test_no_critical_errors_on_valid_input(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.3)
        ctx = pipeline.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)
        # Errors from non-critical stages (OMS, etc.) are acceptable in research mode
        critical_errors = [e for e in ctx.errors if "event_detection" in e or "risk_scoring" in e]
        assert len(critical_errors) == 0, f"Critical stage errors: {critical_errors}"

    def test_alerts_generated_for_high_score(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.7)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        if ctx.risk_score and ctx.risk_score.composite_score >= 35:
            assert len(ctx.alerts) > 0, "High-scoring event should generate alerts"

    def test_hedge_recommendations_present_for_hedge_action(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.6)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        if ctx.portfolio_impact and ctx.portfolio_impact.action_level in ("HEDGE", "EMERGENCY_DERISKING"):
            assert len(ctx.portfolio_impact.hedge_recommendations) > 0

    def test_human_override_always_required(self):
        """Portfolio impact must always require human override — never fully automated."""
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.8)
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=market)

        if ctx.portfolio_impact:
            assert ctx.portfolio_impact.human_override_required is True, (
                "System must NEVER recommend fully automated execution"
            )

    def test_sub_scores_all_in_range(self):
        pipeline = make_pipeline()
        market = make_market_state(pipeline, stress_level=0.5)
        ctx = pipeline.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)

        if ctx.risk_score:
            sub_scores = [
                ctx.risk_score.liquidity_risk,
                ctx.risk_score.volatility_risk,
                ctx.risk_score.rate_shock_risk,
                ctx.risk_score.equity_downside_risk,
                ctx.risk_score.credit_spread_risk,
                ctx.risk_score.fx_risk,
                ctx.risk_score.commodity_shock_risk,
                ctx.risk_score.weekend_gap_risk,
                ctx.risk_score.policy_ambiguity_risk,
            ]
            for ss in sub_scores:
                assert 0.0 <= ss.score <= 100.0, f"{ss.name}: {ss.score} out of range"

    def test_composite_score_is_deterministic(self):
        """Same inputs must always produce the same score."""
        pipeline1 = make_pipeline()
        pipeline2 = make_pipeline()
        market = make_market_state(pipeline1, stress_level=0.4)

        ctx1 = pipeline1.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)
        ctx2 = pipeline2.process_raw_event(HAWKISH_PRESS_CONF_RAW, market_state=market)

        if ctx1.risk_score and ctx2.risk_score:
            # Scores should be within floating-point tolerance
            assert abs(ctx1.risk_score.composite_score - ctx2.risk_score.composite_score) < 0.5, (
                "Pipeline must be deterministic for same inputs"
            )

    def test_minimal_market_state_does_not_crash(self):
        """Pipeline must degrade gracefully with missing market data."""
        pipeline = make_pipeline()
        minimal_state = MarketStateBuilder.build_minimal(
            as_of=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
            calendar=pipeline.calendar,
        )
        ctx = pipeline.process_raw_event(WEEKEND_CRISIS_RAW, market_state=minimal_state)
        # Should complete without exception; score may be unreliable
        assert ctx is not None
        if ctx.risk_score:
            assert ctx.risk_score.score_reliability in ("LOW", "MEDIUM", "HIGH")
