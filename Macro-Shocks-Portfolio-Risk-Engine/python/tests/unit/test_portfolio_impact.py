"""
tests/unit/test_portfolio_impact.py

Unit tests for the Portfolio Impact Translation Engine.
Validates hedge recommendations, exposure guidance, action levels,
and critical safety invariants (PM override always required).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data_schema.models import (
    AlertLevel, AssetClass, CompositeRiskScore, EventType, HawkishDovishScore,
    MacroEvent, MarketSessionState, PolicyStance, PolicySurpriseVector,
    RegimeType, ScenarioOutcome, ScenarioTree, SeverityLevel, SubRiskScore,
)
from macro_shock.portfolio_impact.impact_translator import PortfolioImpactTranslator


# ─── Helpers ─────────────────────────────────────────────────

def _sub(name: str, score: float, weight: float = 0.11) -> SubRiskScore:
    return SubRiskScore(name=name, score=score, weight=weight, primary_driver=f"{name} test driver")


def make_score(composite: float, severity: SeverityLevel, action: str,
               regime: RegimeType = RegimeType.FRAGILE_RISK_ON,
               gap_mult: float = 1.0) -> CompositeRiskScore:
    w = 1.0 / 9
    gap_score = min(composite * 1.2, 100) if gap_mult > 1.0 else 5.0
    return CompositeRiskScore(
        event_id="test-evt",
        composite_score=composite,
        severity=severity,
        regime=regime,
        gap_risk_multiplier=gap_mult,
        recommended_action_level=action,
        summary=f"Test {composite}",
        liquidity_risk=_sub("Liquidity Risk", composite * 0.9, w),
        volatility_risk=_sub("Volatility Risk", composite * 0.85, w),
        rate_shock_risk=_sub("Rate Shock Risk", composite * 0.95, w),
        equity_downside_risk=_sub("Equity Downside Risk", composite, w),
        credit_spread_risk=_sub("Credit Spread Risk", composite * 0.8, w),
        fx_risk=_sub("FX Risk", composite * 0.6, w),
        commodity_shock_risk=_sub("Commodity Shock Risk", composite * 0.5, w),
        weekend_gap_risk=_sub("Weekend Gap Risk", gap_score, w),
        policy_ambiguity_risk=_sub("Policy Ambiguity Risk", composite * 0.4, w),
    )


def make_tree(event_id: str = "test-evt", include_tail: bool = False,
              monday_gap: float = None) -> ScenarioTree:
    scenarios = [
        ScenarioOutcome(
            name="Benign", description="In line", probability=0.40,
            equity_impact_pct=-0.5, yield_10y_change_bps=3.0, vix_change=0.5,
            yield_2y_change_bps=4.0, credit_hy_change_bps=5.0,
            dxy_change_pct=0.1, gold_change_pct=-0.2, oil_change_pct=0.0,
            is_tail_scenario=False, liquidity_impairment=0.0,
            trading_halt_probability=0.0, forced_deleveraging_risk=0.0,
        ),
    ]
    if include_tail:
        scenarios.append(ScenarioOutcome(
            name="Disorderly Risk-Off", description="Tail", probability=0.60,
            equity_impact_pct=-8.5, yield_10y_change_bps=18.0, vix_change=20.0,
            yield_2y_change_bps=28.0, credit_hy_change_bps=220.0,
            dxy_change_pct=2.0, gold_change_pct=3.5, oil_change_pct=-4.0,
            is_tail_scenario=True, liquidity_impairment=0.75,
            trading_halt_probability=0.08, forced_deleveraging_risk=0.65,
        ))
    tree = ScenarioTree(
        event_id=event_id,
        regime=RegimeType.FRAGILE_RISK_ON,
        scenarios=scenarios,
        expected_equity_impact_pct=-3.5 if include_tail else -0.5,
        expected_yield_change_bps=12.0 if include_tail else 2.0,
        expected_vix_change=8.0 if include_tail else 0.5,
        tail_loss_5pct=-9.0 if include_tail else -1.5,
        tail_loss_1pct=-15.0 if include_tail else -3.0,
        monday_gap_estimate_pct=monday_gap,
        monday_gap_confidence=0.75 if monday_gap else None,
    )
    return tree


def make_event(is_weekend: bool = False, action: str = "HEDGE") -> MacroEvent:
    return MacroEvent(
        event_id="test-evt",
        detected_at=datetime.now(timezone.utc),
        event_timestamp=datetime.now(timezone.utc),
        event_type=EventType.WEEKEND_POLICY_ACTION if is_weekend else EventType.PRESS_CONFERENCE,
        severity=SeverityLevel.HIGH,
        severity_score=70.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="Test Event",
        is_weekend=is_weekend,
        full_weekend_gap=is_weekend,
        hours_until_next_open=52.0 if is_weekend else None,
        market_session_at_event=MarketSessionState.CLOSED_WEEKEND if is_weekend else MarketSessionState.OPEN,
    )


def make_market(calendar=None):
    from macro_shock.data.ingestion import MarketStateBuilder
    from macro_shock.event_detection.calendar import MarketCalendar
    cal = calendar or MarketCalendar()
    return MarketStateBuilder.build_synthetic(
        as_of=datetime(2024, 3, 9, 19, 0, tzinfo=timezone.utc),
        calendar=cal, stress_level=0.45, seed=42,
    )


# ─── Tests ────────────────────────────────────────────────────

class TestPortfolioImpactTranslator:

    @pytest.fixture
    def translator(self):
        return PortfolioImpactTranslator()

    @pytest.fixture
    def market(self):
        return make_market()

    # ── Safety invariants ─────────────────────────────────────

    def test_human_override_always_required(self, translator, market):
        """CRITICAL INVARIANT: PM override must always be true."""
        for action in ["NO_ACTION", "MONITOR", "REDUCE", "HEDGE", "EMERGENCY_DERISKING"]:
            score = make_score(60.0, SeverityLevel.HIGH, action)
            tree = make_tree()
            event = make_event()
            report = translator.generate(event, score, tree, market)
            assert report.human_override_required is True, \
                f"human_override_required must be True for action={action}"

    def test_all_hedges_require_pm_approval(self, translator, market):
        """Every hedge recommendation must require PM authorization."""
        score = make_score(75.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_tree(include_tail=True)
        event = make_event(is_weekend=True)
        report = translator.generate(event, score, tree, market)
        for hedge in report.hedge_recommendations:
            assert hedge.requires_pm_approval is True

    # ── Action level mapping ───────────────────────────────────

    def test_low_score_produces_no_action_or_monitor(self, translator, market):
        score = make_score(10.0, SeverityLevel.INFORMATIONAL, "NO_ACTION")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.action_level in ("NO_ACTION", "MONITOR")

    def test_medium_score_produces_reduce_or_monitor(self, translator, market):
        score = make_score(42.0, SeverityLevel.MEDIUM, "REDUCE")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.action_level in ("REDUCE", "MONITOR", "HEDGE")

    def test_high_score_produces_hedge_or_emergency(self, translator, market):
        score = make_score(70.0, SeverityLevel.HIGH, "HEDGE")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.action_level in ("HEDGE", "EMERGENCY_DERISKING")

    def test_critical_score_produces_emergency(self, translator, market):
        score = make_score(85.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_tree(include_tail=True)
        event = make_event(is_weekend=True)
        report = translator.generate(event, score, tree, market)
        assert report.action_level == "EMERGENCY_DERISKING"

    # ── Kill switch ────────────────────────────────────────────

    def test_kill_switch_above_threshold(self, translator, market):
        score = make_score(92.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_tree(include_tail=True)
        event = make_event(is_weekend=True)
        report = translator.generate(event, score, tree, market)
        assert report.trigger_kill_switch is True

    def test_no_kill_switch_for_low_score(self, translator, market):
        score = make_score(40.0, SeverityLevel.MEDIUM, "REDUCE")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.trigger_kill_switch is False

    # ── Hedge recommendations ──────────────────────────────────

    def test_hedges_present_for_hedge_action(self, translator, market):
        score = make_score(68.0, SeverityLevel.HIGH, "HEDGE")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert len(report.hedge_recommendations) > 0

    def test_no_hedges_for_no_action(self, translator, market):
        score = make_score(8.0, SeverityLevel.INFORMATIONAL, "NO_ACTION")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert len(report.hedge_recommendations) == 0

    def test_equity_hedge_included_when_equity_risk_high(self, translator, market):
        score = make_score(72.0, SeverityLevel.HIGH, "HEDGE")
        # Boost equity downside score
        score.equity_downside_risk = SubRiskScore(
            name="Equity Downside Risk", score=75.0, weight=0.18,
            primary_driver="High equity downside"
        )
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        equity_hedges = [h for h in report.hedge_recommendations
                         if h.asset_class == AssetClass.EQUITY]
        assert len(equity_hedges) > 0

    def test_hedge_urgency_pre_open_for_weekend(self, translator, market):
        score = make_score(75.0, SeverityLevel.CRITICAL, "HEDGE")
        tree = make_tree(include_tail=True)
        event = make_event(is_weekend=True)
        report = translator.generate(event, score, tree, market)
        if report.hedge_recommendations:
            urgencies = {h.urgency for h in report.hedge_recommendations}
            assert "PRE-OPEN" in urgencies or "IMMEDIATE" in urgencies

    # ── Exposure guidance ──────────────────────────────────────

    def test_gross_exposure_reduction_for_emergency(self, translator, market):
        score = make_score(82.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        if report.recommended_gross_exposure_change is not None:
            assert report.recommended_gross_exposure_change < 0  # negative = reduce

    def test_no_exposure_change_for_no_action(self, translator, market):
        score = make_score(5.0, SeverityLevel.INFORMATIONAL, "NO_ACTION")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.recommended_gross_exposure_change is None or \
               report.recommended_gross_exposure_change == 0.0

    # ── Guidance text ──────────────────────────────────────────

    def test_equity_guidance_populated(self, translator, market):
        score = make_score(60.0, SeverityLevel.HIGH, "HEDGE")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert len(report.equity_guidance) > 10

    def test_rates_guidance_populated(self, translator, market):
        score = make_score(60.0, SeverityLevel.HIGH, "HEDGE")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert len(report.rates_guidance) > 10

    # ── Alert level ────────────────────────────────────────────

    def test_alert_level_critical_for_high_score(self, translator, market):
        score = make_score(80.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_tree(include_tail=True)
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.alert_level == AlertLevel.CRITICAL

    def test_alert_level_low_for_low_score(self, translator, market):
        score = make_score(12.0, SeverityLevel.LOW, "MONITOR")
        tree = make_tree()
        event = make_event()
        report = translator.generate(event, score, tree, market)
        assert report.alert_level in (AlertLevel.LOW, AlertLevel.MEDIUM)

    # ── Monday gap note ────────────────────────────────────────

    def test_monday_gap_note_in_weekend_report(self, translator, market):
        score = make_score(75.0, SeverityLevel.CRITICAL, "HEDGE")
        tree = make_tree(include_tail=True, monday_gap=-5.2)
        event = make_event(is_weekend=True)
        report = translator.generate(event, score, tree, market)
        # Notes should mention Monday gap
        assert "Monday" in report.notes or "gap" in report.notes.lower()
